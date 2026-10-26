"""Test du rappel « Call dans 5 min » (26/10/2026, après le call Johnny sans notification).
Lancer depuis cloud-alertes : python -X utf8 -m unittest test_rappels"""
import datetime as dt, os, tempfile, unittest

os.environ["ICAL_URL"] = "http://exemple.invalide/agenda.ics"
os.environ["MES_ADRESSES"] = "moi@exemple.fr"
import alertes


class Rappels(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        alertes.ETAT = os.path.join(self.dossier, "state.json")
        self.envois = []
        alertes.pousser = lambda msg, urgent=False: self.envois.append(msg) or True
        alertes.formulaires = alertes.mails_evenements = lambda *a, **k: self.fail("boîte mail lue pendant un passage agenda seul")
        alertes.leads_clients = lambda *a, **k: self.fail("leads lus pendant un passage agenda seul")
        # le premier passage n'alerte rien (état vide) : on le fait avant
        self.debut = None
        alertes.lire_ical = lambda url: []
        alertes.main(complet=False, rattrapage=True, boucle=True)

    def evenement(self, dans_min):
        d = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=dans_min)
        alertes.lire_ical = lambda url: [{"uid": "johnny", "titre": "Pierre Baribeau and Johnny Demetriou", "debut": d,
                                          "externes": {"johnny@nousify.ai"}, "chez_moi": False}]

    def test_pas_avant_5_min_en_boucle(self):
        self.evenement(8)
        alertes.main(complet=False, rattrapage=False, boucle=True)
        self.assertEqual(self.envois, [])

    def test_une_seule_fois_a_5_min(self):
        self.evenement(5)
        alertes.main(complet=False, rattrapage=False, boucle=True)
        alertes.main(complet=False, rattrapage=False, boucle=True)
        self.assertEqual(len(self.envois), 1)
        self.assertIn("Call dans 5 min", self.envois[0])

    def test_rattrapage_apres_redemarrage(self):
        self.evenement(8)
        alertes.main(complet=False, rattrapage=True, boucle=True)
        self.assertEqual(len(self.envois), 1)

    def test_appel_deja_commence_pas_de_rappel(self):
        self.evenement(-3)  # le cas du 26/10 : le contrôle est passé après l'heure
        alertes.main(complet=False, rattrapage=True, boucle=True)
        self.assertEqual(self.envois, [])


if __name__ == "__main__":
    unittest.main()
