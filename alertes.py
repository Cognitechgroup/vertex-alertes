# Alertes Vertex, version nuage (tourne sur GitHub Actions toutes les 5 minutes, PC éteint ou allumé).
# Stdlib seulement. Aucun nom de client n'est écrit dans le dépôt : les alertes partent seulement vers Ahmed (ntfy / Telegram / WhatsApp CallMeBot).
#
# 1. Formulaires d'onboarding finis : lecture SEULE de la boîte pro (IMAP, rien n'est marqué lu), mails « Formulaire de démarrage (...) ».
# 2. Appels réservés : lecture de l'agenda pro via son adresse secrète au format iCal (ICAL_URL). Nouvel événement « Kickoff » ou avec invité externe.
# 3. Rappels : 1 h puis 15 min avant chaque appel (« Kickoff » ou « X Vertex Acquisition »), le 2e en priorité urgente.
# Mémoire : state.json (restauré par le cache GitHub). Premier passage = on enregistre sans alerter (jamais de spam de l'historique).
# Variables : MES_ADRESSES (adresses d'Ahmed, séparées par des virgules), MERCURY_TOKEN (jeton lecture seule), SMTP_HOST, SMTP_USER, SMTP_PASS, (IMAP_HOST, IMAP_PORT), ICAL_URL, NTFY_TOPIC, (TG_NOTIF_TOKEN, TG_NOTIF_CHAT), (WA_NOTIF_PHONE, WA_NOTIF_KEY).
import datetime as dt, email, imaplib, json, os, re, sys, urllib.parse, urllib.request
from email.header import decode_header, make_header
from zoneinfo import ZoneInfo

ETAT = "state.json"
MOI = {a.strip().lower() for a in os.environ.get("MES_ADRESSES", "").split(",") if a.strip()}
SUJET = re.compile(r"^Formulaire de d[ée]marrage \((onboarding-(?:conciergerie|clinic))\) : (.+)$", re.S)
TEST = re.compile(r"\btest\b|ne pas traiter", re.I)
PARIS, BKK = ZoneInfo("Europe/Paris"), ZoneInfo("Asia/Bangkok")
E = os.environ.get


def pousser(msg, urgent=False):
    """True si au moins un canal a livré."""
    ok = False
    topic = E("NTFY_TOPIC")
    if topic:
        try:
            titre = msg.splitlines()[0].encode("ascii", "ignore").decode() or "Alerte Vertex"
            req = urllib.request.Request("https://ntfy.sh/" + topic, data=msg.encode("utf-8"),
                                         headers={"Title": titre, "Priority": "urgent" if urgent else "high",
                                                  "Tags": "rotating_light" if urgent else "bell"})
            urllib.request.urlopen(req, timeout=30).read()
            ok = True
        except Exception as ex:
            print("ntfy KO", type(ex).__name__)
    if E("TG_NOTIF_TOKEN") and E("TG_NOTIF_CHAT"):
        try:
            d = urllib.parse.urlencode({"chat_id": E("TG_NOTIF_CHAT"), "text": msg}).encode()
            ok = ('"ok":true' in urllib.request.urlopen(f"https://api.telegram.org/bot{E('TG_NOTIF_TOKEN')}/sendMessage", d, timeout=30).read().decode()) or ok
        except Exception as ex:
            print("telegram KO", type(ex).__name__)
    if E("WA_NOTIF_PHONE") and E("WA_NOTIF_KEY"):
        try:
            u = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode({"phone": E("WA_NOTIF_PHONE"), "text": msg, "apikey": E("WA_NOTIF_KEY")})
            rep = urllib.request.urlopen(u, timeout=30).read().decode("utf-8", "replace")
            ok = (bool(re.search(r"queued|sent", rep, re.I)) and not re.search(r"error|invalid", rep, re.I)) or ok
        except Exception as ex:
            print("whatsapp KO", type(ex).__name__)
    return ok


def hh(d):
    return f"{d.astimezone(PARIS):%a %d/%m %H:%M} Paris = {d.astimezone(BKK):%H:%M} Bangkok"


# ---------- formulaires ----------
def formulaires():
    M = imaplib.IMAP4_SSL(E("IMAP_HOST") or E("SMTP_HOST"), int(E("IMAP_PORT") or 993), timeout=30)
    M.login(E("SMTP_USER"), E("SMTP_PASS"))
    M.select("INBOX", readonly=True)
    depuis = (dt.date.today() - dt.timedelta(days=3)).strftime("%d-%b-%Y")
    _, d = M.search(None, "SINCE", depuis, "SUBJECT", '"Formulaire de d"')
    out = []
    for num in d[0].split():
        _, data = M.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(data[0][1])
        sujet = str(make_header(decode_header(msg.get("Subject", "")))).replace("\r", "").replace("\n", " ").strip()
        m = SUJET.match(sujet)
        if not m or TEST.search(m.group(2)):
            continue
        corps = ""
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                corps = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                break
        champs = {}
        for l in corps.splitlines():
            if " : " in l:
                k, v = l.split(" : ", 1)
                champs[k.strip().lower()] = v.strip()
        try:
            recu = email.utils.parsedate_to_datetime(msg.get("Date"))
        except Exception:
            recu = dt.datetime.now(dt.timezone.utc)
        out.append((msg.get("Message-ID", sujet + str(num)), m.group(1), m.group(2).strip(), champs, recu))
    M.logout()
    return out


def trouver(champs, *mots):
    for k, v in champs.items():
        if any(w in k for w in mots) and v:
            return v
    return "non renseigné"


# ---------- agenda ----------
def lire_ical(url):
    brut = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
    brut = re.sub(r"\r?\n[ \t]", "", brut)
    evts = []
    for bloc in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", brut, re.S):
        if "RRULE" in bloc:
            continue
        def val(nom):
            m = re.search(r"^" + nom + r"((?:;[^:\r\n]*)?):(.*)$", bloc, re.M)
            return (m.group(1), m.group(2).strip()) if m else ("", "")
        _, uid = val("UID")
        _, resume = val("SUMMARY")
        par, ds = val("DTSTART")
        if not uid or not re.match(r"\d{8}T\d{6}", ds or ""):
            continue
        tz = re.search(r"TZID=([^;:]+)", par)
        d = dt.datetime.strptime(ds[:15], "%Y%m%dT%H%M%S")
        d = d.replace(tzinfo=dt.timezone.utc) if ds.endswith("Z") else d.replace(tzinfo=ZoneInfo(tz.group(1)) if tz else PARIS)
        _, statut = val("STATUS")
        if statut == "CANCELLED":
            continue
        invites = {m.lower() for m in re.findall(r"mailto:([^\r\n;]+)", "\n".join(re.findall(r"^ATTENDEE.*$", bloc, re.M)), re.I)}
        evts.append({"uid": uid, "titre": resume.replace("\\,", ",").replace("\\n", " "), "debut": d, "externes": invites - MOI})
    return evts


def est_reservation(e):
    return "X Vertex Acquisition" not in e["titre"] and ("kickoff" in e["titre"].lower() or bool(e["externes"]))


def est_appel(e):
    return "kickoff" in e["titre"].lower() or "X Vertex Acquisition" in e["titre"] or bool(e["externes"])


# ---------- virements (Mercury, jeton LECTURE SEULE) ----------
def api_mercury(chemin):
    req = urllib.request.Request("https://api.mercury.com/api/v1" + chemin, headers={"Authorization": "Bearer " + E("MERCURY_TOKEN"), "Accept": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8"))


def entrees_mercury():
    """Renvoie [(id, montant, expéditeur, statut)] des dernières entrées d'argent (montant > 0)."""
    trs = []
    try:
        trs = api_mercury("/transactions?limit=50").get("transactions", [])
    except Exception:
        for cpt in api_mercury("/accounts").get("accounts", []):
            trs += api_mercury(f"/account/{cpt['id']}/transactions?limit=50").get("transactions", [])
    return [(t["id"], float(t.get("amount", 0)), t.get("counterpartyName") or t.get("bankDescription") or "expéditeur inconnu", t.get("status", ""))
            for t in trs if float(t.get("amount", 0)) > 0 and t.get("status") != "failed"]


def main():
    etat = json.load(open(ETAT, encoding="utf-8")) if os.path.exists(ETAT) else {}
    premier = not etat
    vus = set(etat.get("vus", []))
    rappels = set(etat.get("rappels", []))
    maintenant = dt.datetime.now(dt.timezone.utc)

    # formulaires
    try:
        for mid, form, nom, champs, recu in formulaires():
            if mid in vus:
                continue
            if premier and (maintenant - recu) > dt.timedelta(minutes=30):
                vus.add(mid)
                continue
            niche = "Conciergerie" if form == "onboarding-conciergerie" else "Clinique"
            txt = f"Onboarding fini : {nom} ({niche})\nTél : {trouver(champs, 'phone', 'téléphone', 'telephone', 'whatsapp', 'mobile')}\nEmail : {trouver(champs, 'email', 'mail')}\nRéponses dans la boîte pro."
            if pousser(txt):
                vus.add(mid)
    except Exception as ex:
        print("boîte mail illisible :", type(ex).__name__)

    # agenda
    if E("ICAL_URL"):
        ical_premier = premier or not etat.get("ical")
        try:
            evts = lire_ical(E("ICAL_URL"))
            for e in evts:
                if e["debut"] < maintenant - dt.timedelta(hours=1):
                    continue
                cle = "rdv|" + e["uid"]
                if est_reservation(e) and cle not in vus:
                    if ical_premier:
                        vus.add(cle)
                    elif pousser(f"Appel réservé : {', '.join(sorted(e['externes'])) or e['titre']}\n{hh(e['debut'])}\n{e['titre']}"):
                        vus.add(cle)
                if not est_appel(e):
                    continue
                reste = (e["debut"] - maintenant).total_seconds() / 60
                for minutes, lo, hi, urgent in ((60, 40, 80, False), (15, 2, 22, True)):
                    k = f"{e['uid']}|{minutes}"
                    if lo <= reste <= hi and k not in rappels:
                        txt = (f"APPEL DANS {minutes} MIN : {e['titre']}\n{hh(e['debut'])}" if urgent else f"Appel dans 1 h : {e['titre']}\n{hh(e['debut'])}")
                        if pousser(txt, urgent):
                            rappels.add(k)
        except Exception as ex:
            print("agenda illisible :", type(ex).__name__)

    # virements reçus
    if E("MERCURY_TOKEN"):
        mercury_premier = premier or not etat.get("mercury")
        try:
            for tid, montant, qui, statut in entrees_mercury():
                cle = "vir|" + tid
                if cle in vus:
                    continue
                if mercury_premier:
                    vus.add(cle)
                elif pousser(f"Virement reçu : {montant:,.2f} $ de {qui}\nCompte pro Mercury ({statut or 'reçu'})"):
                    vus.add(cle)
        except Exception as ex:
            print("Mercury illisible :", type(ex).__name__)

    json.dump({"vus": sorted(vus)[-500:], "rappels": sorted(rappels)[-500:], "ical": bool(E("ICAL_URL")) or bool(etat.get("ical")), "mercury": bool(E("MERCURY_TOKEN")) or bool(etat.get("mercury"))}, open(ETAT, "w", encoding="utf-8"))
    print("OK", "(premier passage, rien alerté)" if premier else "")


if __name__ == "__main__":
    main()
