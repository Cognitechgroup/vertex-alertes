# Alertes Vertex, version nuage (tourne sur GitHub Actions toutes les 5 minutes, PC éteint ou allumé).
# Stdlib seulement. Aucun nom de client n'est écrit dans le dépôt : les alertes partent seulement vers Ahmed (ntfy / Telegram / WhatsApp CallMeBot).
#
# 1. Brief reçu (formulaire d'onboarding envoyé) : lecture SEULE de la boîte pro (IMAP, rien n'est marqué lu), mails « Formulaire de démarrage (onboarding-<niche>) ».
# 2. Call booké : lecture de l'agenda pro via son adresse secrète au format iCal (ICAL_URL). Nouvel événement « Kickoff » ou avec invité externe, organisé par l'agenda d'Ahmed (pas les calls qu'il réserve chez d'autres).
# 3. Rappels : 1 h puis 15 min avant chaque appel (« Kickoff » ou « X Vertex Acquisition »), le 2e en priorité urgente.
# Mémoire : state.json (restauré par le cache GitHub). Premier passage = on enregistre sans alerter (jamais de spam de l'historique).
# Variables : MES_ADRESSES (adresses d'Ahmed, séparées par des virgules), MERCURY_TOKEN (jeton lecture seule), SMTP_HOST, SMTP_USER, SMTP_PASS, (IMAP_HOST, IMAP_PORT), ICAL_URL, NTFY_TOPIC, (TG_NOTIF_TOKEN, TG_NOTIF_CHAT), (WA_NOTIF_PHONE, WA_NOTIF_KEY).
import datetime as dt, email, imaplib, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from email.header import decode_header, make_header
from zoneinfo import ZoneInfo

ETAT = "state.json"
MOI = {a.strip().lower() for a in os.environ.get("MES_ADRESSES", "").split(",") if a.strip()}
SUJET = re.compile(r"^Formulaire de d[ée]marrage \((onboarding-[\w-]+)\) : (.+)$", re.S)  # toute niche future (onboarding-<niche>) est alertée sans toucher au code
TEST = re.compile(r"\btest\b|ne pas traiter", re.I)
ESSAI_ALERTES = re.compile(r"test alertes", re.I)  # faux client « TEST ALERTES … » : alerté quand même (contrôle de bout en bout), ignoré par tous les scripts du PC
MUETS = {"onboarding-whatsapp-code", "onboarding-whatsapp-numero"}  # coupés le 24/10 sur ordre d'Ahmed : le code reste dans le mail et la fiche client
# Ahmed (24/10/2026, « je t'ai toujours demandé 4 trucs ») : paiement reçu, contrat signé, brief reçu, call booké.


def ignorer(nom):
    return bool(TEST.search(nom)) and not ESSAI_ALERTES.search(nom)
PARIS = ZoneInfo("Europe/Paris")
LOCAL = ZoneInfo(os.environ.get("ALERTE_TZ") or "Asia/Bangkok")  # heure du pays où est Ahmed (Chine à partir du 01/11 : ALERTE_TZ=Asia/Shanghai)
E = os.environ.get


def pousser(msg, urgent=False):
    """True si au moins un canal a livré."""
    ok = False
    topic = E("NTFY_TOPIC")
    if topic:
        try:
            titre = unicodedata.normalize("NFKD", msg.splitlines()[0]).encode("ascii", "ignore").decode().strip() or "Alerte Vertex"
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
    if envoyer_wa(E("WA_TO"), msg):
        ok = True
    return ok


def envoyer_wa(to, msg, lang="fr"):
    """WhatsApp officiel (Cloud API, modèle approuvé) vers `to` (chiffres avec indicatif, sans +). True si Meta accepte le message."""
    if not (E("WA_CLOUD_TOKEN") and E("WA_CLOUD_PHONE_ID") and to):
        return False
    lignes = [l.strip() for l in msg.splitlines() if l.strip()]
    if lang == "en":
        modeles = [(E("WA_TEMPLATE_EN") or "alerte_vertex_v2_en", "en_US")]
    else:
        # modèle propre à 3 champs d'abord ; tant que Meta ne l'a pas approuvé, l'ancien modèle à 1 champ prend le relais
        modeles = [(m, E("WA_TEMPLATE_LANG") or "fr") for m in ([E("WA_TEMPLATE")] if E("WA_TEMPLATE") else ["alerte_vertex_v2", "alerte_vertex"])]
    for modele, code in modeles:
        try:
            if modele == "alerte_vertex":
                champs = [" | ".join(lignes)[:900]]
            else:
                champs = [lignes[0][:200], (lignes[1] if len(lignes) > 1 else "-")[:300], (" / ".join(lignes[2:]) or "-")[:900]]
            corps = {"messaging_product": "whatsapp", "to": to, "type": "template",
                     "template": {"name": modele, "language": {"code": code},
                     "components": [{"type": "body", "parameters": [{"type": "text", "text": c} for c in champs]}]}}
            req = urllib.request.Request(f"https://graph.facebook.com/v21.0/{E('WA_CLOUD_PHONE_ID')}/messages", json.dumps(corps).encode(),
                                         {"Authorization": "Bearer " + E("WA_CLOUD_TOKEN"), "Content-Type": "application/json"})
            if '"messages"' in urllib.request.urlopen(req, timeout=30).read().decode():
                return True
        except Exception as ex:
            print("whatsapp Meta KO", modele, type(ex).__name__, getattr(ex, "code", ""))
    return False


def hh(d):
    return f"{d.astimezone(LOCAL):%a %d/%m %H:%M}"


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
        if not m or ignorer(m.group(2)):
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


def texte_onboarding(form, nom, champs):
    """Texte de l'alerte « Brief reçu » (formulaire de démarrage envoyé, toute niche)."""
    niche = {"onboarding-conciergerie": "Conciergerie", "onboarding-clinic": "Clinique"}.get(form,form.replace("onboarding-", "").replace("-", " ").capitalize())
    return f"📋 Brief reçu\n{nom} ({niche})\nTél : {trouver(champs, 'phone', 'téléphone', 'telephone', 'whatsapp', 'mobile')}\nEmail : {trouver(champs, 'email', 'mail')}\nRéponses dans la boîte pro"


def trouver(champs, *mots):
    for k, v in champs.items():
        if any(w in k for w in mots) and v:
            return v
    return "non renseigné"


# ---------- paiements Stripe et contrats signés (mails reçus sur la boîte pro) ----------
MONTANT = re.compile(r"\d[\d   .,]*\s?(?:€|\$|EUR|USD)|(?:€|\$)\s?\d[\d.,]*")
PAIEMENT = re.compile(r"^Paiement de (.+?) effectu[ée] par (.+?) en faveur", re.S)
SUJET_CONTRAT = re.compile(r"^Contrat(?: [\w -]+?)? accept[ée] en ligne : (.+)$", re.S)  # « Contrat accepté », « Contrat conciergerie accepté », « Contrat <niche> accepté »


def mails_evenements():
    """[(id, texte)] : paiements Stripe reçus (avec montant) et contrats acceptés en ligne, 3 derniers jours."""
    M = imaplib.IMAP4_SSL(E("IMAP_HOST") or E("SMTP_HOST"), int(E("IMAP_PORT") or 993), timeout=30)
    M.login(E("SMTP_USER"), E("SMTP_PASS"))
    M.select("INBOX", readonly=True)
    depuis = (dt.date.today() - dt.timedelta(days=3)).strftime("%d-%b-%Y")
    out = []
    for crit in (("FROM", "stripe.com"), ("SUBJECT", '"accept"')):
        _, d = M.search(None, "SINCE", depuis, *crit)
        for num in d[0].split():
            _, data = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID DATE)])")
            msg = email.message_from_bytes(data[0][1])
            sujet = " ".join(str(make_header(decode_header(msg.get("Subject", "")))).split())
            mid = msg.get("Message-ID", sujet + str(num))
            try:
                vieux = dt.datetime.now(dt.timezone.utc) - email.utils.parsedate_to_datetime(msg.get("Date")) > dt.timedelta(hours=12)
            except Exception:
                vieux = False
            if vieux:  # mail de plus de 12 h jamais alerté (ex. paiement de Nicolas du 22/10 avant la correction) : noté vu, pas d'alerte en retard
                out.append((mid, None))
                continue
            c = SUJET_CONTRAT.match(sujet)
            if c and not ignorer(c.group(1)):
                out.append((mid, "✅ Contrat signé\n" + c.group(1).strip() + "\nPaiement Stripe attendu"))
            # vrai sujet Stripe (Nicolas, 22/10) : « Paiement de 750,00 € effectué par … en faveur de … » (« effectué » n'était pas reconnu : alerte jamais partie)
            elif "stripe.com" in msg.get("From", "").lower() and MONTANT.search(sujet) and (PAIEMENT.match(sujet) or re.search(r"re[çc]u|received|succe|r[ée]ussi|paid|pay[ée]|effectu", sujet, re.I)):
                pay = PAIEMENT.match(sujet)
                out.append((mid, "💰 Paiement reçu\n" + (f"{pay.group(1).strip()} de {pay.group(2).strip()}" if pay else MONTANT.search(sujet).group(0).strip()) + "\nStripe"))
    M.logout()
    return out


# ---------- agenda ----------
def lire_ical(url):
    brut = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
    brut = re.sub(r"\r?\n[ \t]", "", brut)
    proprio = re.search(r"^X-WR-CALNAME:(.+)$", brut, re.M)
    proprio = proprio.group(1).strip().lower() if proprio else ""  # l'agenda Google porte l'adresse de son propriétaire
    print("agenda : propriétaire", "reconnu" if "@" in proprio else "NON reconnu", "/ adresses d'Ahmed :", len(MOI))
    evts = []
    for bloc in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", brut, re.S):
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
        if statut == "CANCELLED" or re.match(r"(canceled|cancelled|annul[ée]+)\s*:", resume, re.I):  # Calendly garde l'événement annulé, titre « Canceled: … »
            continue
        invites = {m.lower() for m in re.findall(r"mailto:([^\r\n;]+)", "\n".join(re.findall(r"^ATTENDEE.*$", bloc, re.M)), re.I)}
        orga = re.search(r"^ORGANIZER[^\r\n]*?mailto:([^\r\n;]+)", bloc, re.M | re.I)
        orga = orga.group(1).strip().lower() if orga else ""
        base = {"uid": uid, "titre": resume.replace("\\,", ",").replace("\\n", " "), "debut": d,
                "externes": invites - MOI - {proprio}, "chez_moi": not orga or orga in MOI or orga == proprio}
        _, regle = val("RRULE")
        if not regle:
            evts.append(base)
            continue
        # événement répété (ex. Billions chaque jeudi) : seulement le rappel 5 min, jamais « call booké » ; répétition hebdomadaire seule gérée
        r = dict(x.split("=", 1) for x in regle.split(";") if "=" in x)
        if r.get("FREQ") != "WEEKLY":
            continue
        fin = dt.datetime.strptime(r["UNTIL"][:15], "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc) if "UNTIL" in r and "T" in r["UNTIL"] else None
        pas = dt.timedelta(weeks=int(r.get("INTERVAL", 1)))
        maintenant, occ = dt.datetime.now(dt.timezone.utc), d
        while occ < maintenant - dt.timedelta(hours=1):
            occ += pas
        if occ <= maintenant + dt.timedelta(days=3) and (not fin or occ <= fin):
            evts.append(dict(base, uid=f"{uid}|{occ:%Y%m%d}", debut=occ, repete=True))
    return evts


def est_reservation(e):
    """Un client a réservé chez Ahmed. Les calls qu'Ahmed réserve chez quelqu'un d'autre (organisateur externe) ne comptent pas."""
    return not e.get("repete") and e.get("chez_moi", True) and "X Vertex Acquisition" not in e["titre"] and ("kickoff" in e["titre"].lower() or bool(e["externes"]))


def est_appel(e):
    if ESSAI_ALERTES.search(e["titre"]):  # réservation d'essai : alertée une fois (call booké), jamais de rappel 1 h / 15 min
        return False
    # Ahmed (24/10) : « juste un appel call dans 5 min, peu importe le call dans mon agenda » : tout événement titré, sauf les blocs « Busy »
    return bool(e["titre"].strip()) and e["titre"].strip().lower() != "busy"


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


# ---------- leads Meta des clients (alerte sur le WhatsApp du client) ----------
# Secret LEADS_CLIENTS = liste JSON : [{"nom": "Enjoy Nice", "page_id": "123", "wa": "33612345678", "lang": "fr", "token": "(facultatif, sinon META_LEADS_TOKEN)", "copie_ahmed": true}]
META = "https://graph.facebook.com/v21.0"
CLES_BASE = {"full_name", "first_name", "last_name", "phone_number", "phone", "email"}


def api_meta(chemin, token, **params):
    params["access_token"] = token
    return json.loads(urllib.request.urlopen(f"{META}/{chemin}?" + urllib.parse.urlencode(params), timeout=30).read().decode("utf-8"))


def tel_international(brut):
    """+33612345678 depuis « 06 12 34 56 78 », « p:+33612345678 » ou « 33612345678 » ; None si illisible."""
    t = re.sub(r"[^\d+]", "", (brut or "").replace("p:", ""))
    if t.startswith("00"):
        t = "+" + t[2:]
    ch = t[1:] if t.startswith("+") else ("33" + t[1:] if t.startswith("0") and len(t) == 10 else t)
    return "+" + ch if 8 <= len(ch) <= 15 else None


def texte_lead(client, lead):
    champs = {f.get("name", "").lower(): " ".join(f.get("values", [])).strip() for f in lead.get("field_data", [])}
    nom = champs.get("full_name") or " ".join(x for x in (champs.get("first_name"), champs.get("last_name")) if x) or "nom non renseigné"
    brut = champs.get("phone_number") or champs.get("phone") or ""
    tel = tel_international(brut) or brut or "téléphone non renseigné"
    # toutes les réponses du formulaire, lues comme dans LeadFactory : « ma_question » devient « Ma question », « plus_de_10 » devient « plus de 10 »
    reponses = []
    for k, v in champs.items():
        if v and k not in CLES_BASE:
            q = re.sub(r"\s+", " ", k.replace("_", " ")).strip()
            reponses.append(f"{q[:1].upper() + q[1:]} : {v.replace('_', ' ')}")
    en = client.get("lang") == "en"
    lignes = ["🔔 New lead" if en else "🔔 Nouveau lead", f"{nom}, {tel}"]
    if champs.get("email"):
        lignes.append(champs["email"])
    return "\n".join(lignes + reponses)


def leads_clients(vus, init, maintenant, api=api_meta, envoyer=envoyer_wa, prevenir=pousser):
    """Lit les nouveaux leads des formulaires Meta de chaque client et prévient son WhatsApp (copie sur les canaux d'Ahmed).
    Premier passage d'un client : les leads de plus de 30 min sont notés sans alerte. Un lead est noté vu après UNE tentative ; un échec de livraison au client prévient Ahmed une fois."""
    try:
        clients = json.loads(E("LEADS_CLIENTS") or "[]")
    except ValueError:
        print("LEADS_CLIENTS illisible")
        return
    for c in clients:
        pid, nom = str(c.get("page_id", "")), c.get("nom", "client")
        token = c.get("token") or E("META_LEADS_TOKEN")
        if not (pid and token):
            print("lead client sans page ou sans jeton :", nom)
            continue
        premier = pid not in init
        try:
            try:
                forms = api(f"{pid}/leadgen_forms", token, fields="id,name", limit=50).get("data", [])
            except urllib.error.HTTPError:
                token = api(pid, token, fields="access_token")["access_token"]  # jeton de Page tiré du jeton système
                forms = api(f"{pid}/leadgen_forms", token, fields="id,name", limit=50).get("data", [])
            for f in forms:
                for lead in api(f"{f['id']}/leads", token, fields="id,created_time,field_data", limit=25).get("data", []):
                    cle = "lead|" + str(lead["id"])
                    if cle in vus:
                        continue
                    try:
                        cree = dt.datetime.strptime(lead["created_time"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
                    except (KeyError, ValueError):
                        cree = maintenant
                    if premier and (maintenant - cree) > dt.timedelta(minutes=30):
                        vus.add(cle)
                        continue
                    texte = texte_lead(c, lead)
                    livre = bool(c.get("wa")) and envoyer(str(c["wa"]), texte, c.get("lang", "fr"))
                    titre = texte.splitlines()[0]
                    if livre:
                        if c.get("copie_ahmed", False):  # copie à Ahmed coupée le 24/10 (« non pas celui-là »)
                            prevenir(texte.replace(titre, f"{titre} · {nom}", 1))
                    else:
                        prevenir(f"⚠️ Lead pour {nom} NON livré sur son WhatsApp\n" + texte.replace(titre + "\n", "", 1))
                    vus.add(cle)
            init.add(pid)
        except Exception as ex:
            print("leads illisibles pour", nom, type(ex).__name__, getattr(ex, "code", ""))


def main(complet=True, rattrapage=True, boucle=False):
    """Un passage. complet=False : seulement l'agenda (passage à la minute). rattrapage : fenêtre large (9 min) pour ne rien perdre au redémarrage."""
    etat = json.load(open(ETAT, encoding="utf-8")) if os.path.exists(ETAT) else {}
    premier = not etat
    vus = set(etat.get("vus", []))
    rappels = set(etat.get("rappels", []))
    maintenant = dt.datetime.now(dt.timezone.utc)

    # formulaires
    try:
        for mid, form, nom, champs, recu in (formulaires() if complet else []):
            if mid in vus:
                continue
            if premier and (maintenant - recu) > dt.timedelta(minutes=30):
                vus.add(mid)
                continue
            if form in MUETS:
                vus.add(mid)
                continue
            if pousser(texte_onboarding(form, nom, champs)):
                vus.add(mid)
    except Exception as ex:
        print("boîte mail illisible :", type(ex).__name__)

    # paiements Stripe + contrats signés
    try:
        for mid, txt in (mails_evenements() if complet else []):
            if mid in vus:
                continue
            if premier or not etat.get("evt") or txt is None:
                vus.add(mid)
            elif pousser(txt, urgent=txt.startswith("💰")):
                vus.add(mid)
    except Exception as ex:
        print("mails paiement/contrat illisibles :", type(ex).__name__)

    # agenda
    if E("ICAL_URL"):
        ical_premier = premier or not etat.get("ical")
        try:
            evts = lire_ical(E("ICAL_URL"))
            if E("TEST_RAPPEL_MIN"):  # essai de bout en bout (26/10/2026) : faux appel dans N min, titre sans « test alertes » pour que le rappel parte
                evts.append({"uid": "essai-rappel", "titre": "ESSAI rappel call (a ignorer)", "debut": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=float(E("TEST_RAPPEL_MIN"))), "externes": set(), "chez_moi": False})
            for e in evts:
                if e["debut"] < maintenant - dt.timedelta(hours=1):
                    continue
                cle = "rdv|" + e["uid"]
                if est_reservation(e) and cle not in vus:
                    if ical_premier:
                        vus.add(cle)
                    elif pousser(f"📞 Call booké\n{', '.join(sorted(e['externes'])) or e['titre']}\n{hh(e['debut'])} / {e['titre']}"):
                        vus.add(cle)
                if not est_appel(e):
                    continue
                reste = (e["debut"] - maintenant).total_seconds() / 60
                k = f"{e['uid']}|5"
                # un seul rappel par appel. En boucle (passage à la minute) : à 5 min ; au 1er passage d'une boucle ou en passage isolé : jusqu'à 9 min (rien de perdu)
                seuil = 5.5 if (boucle and not rattrapage) else 9
                if 0 <= reste <= seuil and k not in rappels:
                    if pousser(f"⏰ Call dans {max(1, round(reste))} min\n{e['titre']}\n{hh(e['debut'])}", True):
                        rappels.add(k)
                        print(f"RAPPEL livré {dt.datetime.now(dt.timezone.utc):%H:%M:%S} UTC, appel dans {reste:.1f} min")
                    else:
                        print("RAPPEL NON LIVRÉ, nouvel essai au prochain passage")
        except Exception as ex:
            print("agenda illisible :", type(ex).__name__)

    # virements reçus
    if complet and E("MERCURY_TOKEN") and E("ALERTE_MERCURY"):  # coupé par Ahmed le 24/10 (« pas la peine ») ; ALERTE_MERCURY=1 pour le remettre
        mercury_premier = premier or not etat.get("mercury")
        try:
            for tid, montant, qui, statut in entrees_mercury():
                cle = "vir|" + tid
                if cle in vus:
                    continue
                if mercury_premier:
                    vus.add(cle)
                elif pousser(f"🏦 Virement reçu\n{montant:,.2f} $ de {qui}\nCompte pro Mercury ({statut or 'reçu'})"):
                    vus.add(cle)
        except Exception as ex:
            print("Mercury illisible :", type(ex).__name__)

    # leads des formulaires Meta de chaque client
    init = set(etat.get("leads_init", []))
    try:
        if complet:
            leads_clients(vus, init, maintenant)
    except Exception as ex:
        print("leads clients KO :", type(ex).__name__)

    json.dump({"leads_init": sorted(init), "vus": sorted(vus)[-2000:], "rappels": sorted(rappels)[-500:],"ical": bool(E("ICAL_URL")) or bool(etat.get("ical")), "mercury": bool(E("MERCURY_TOKEN")) or bool(etat.get("mercury")), "evt": True}, open(ETAT, "w", encoding="utf-8"))
    print("OK", "(premier passage, rien alerté)" if premier else "")


def boucle(duree_min):
    """Passage à la minute pendant duree_min (le PC d'Ahmed peut dormir, le nuage ne dort pas) : agenda chaque minute, le reste toutes les 5 min.
    Cause du 26/10/2026 : le déclenchement venait du PC (en veille) et le planificateur de GitHub n'a passé qu'une fois en 3 h, le rappel du call de 20 h 30 est tombé dans le trou."""
    fin = time.time() + duree_min * 60
    i = 0
    while True:
        debut = time.time()
        try:
            main(complet=(i % 5 == 0), rattrapage=(i == 0), boucle=True)
        except Exception as ex:
            print("passage KO :", type(ex).__name__)
        i += 1
        if time.time() + 60 > fin:
            break
        time.sleep(max(1, 60 - (time.time() - debut)))


if __name__ == "__main__":
    if E("BOUCLE_MIN"):
        boucle(float(E("BOUCLE_MIN")))
    else:
        main()
