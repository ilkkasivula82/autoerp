"""Osto- ja myyntisopimukset: auto varastoon sopimuksella, myynti vaihtoautoineen, tulostettava sopimus."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autot import palvelut
from autot.models import Ajoneuvo, Kierto, Muutosloki, Sopimus, SopimusRivi, Yritys
from liikkeet.rajaus import liike_kaytossa

from .apu import luo_liike

HTMX = {"HTTP_HX_REQUEST": "true"}


def lomakedata(**muut):
    """Sopimuslomakkeen POST-data (etuliitteet s-, kohde-, vaihto-)."""
    data = {
        "s-pvm": "2026-09-01",
        "s-maksutapa": "tilisiirto",
        "s-tunnistus": "ajokortti",
        "kohde-hinta": "10 000",
        "kohde-alv_kasittely": "marginaali",
        "vaihto-TOTAL_FORMS": "2",
        "vaihto-INITIAL_FORMS": "0",
        "vaihto-MIN_NUM_FORMS": "0",
        "vaihto-MAX_NUM_FORMS": "1000",
    }
    data.update(muut)
    return data


class Pohja(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d = luo_liike("Testiliike", "t")

    def setUp(self):
        self.client.force_login(self.d.admin)
        self._liike = liike_kaytossa(self.d.liike)
        self._liike.__enter__()

    def tearDown(self):
        self._liike.__exit__(None, None, None)

    def tarjous(self, rek="TAR-111", **kentat):
        a = Ajoneuvo.objects.create(rekisterinumero=rek, merkki="Skoda", malli="Octavia")
        return palvelut.avaa_kierto(a, self.d.admin, **kentat)

    def varastoauto(self, rek="VAR-222", **kentat):
        a = Ajoneuvo.objects.create(rekisterinumero=rek, merkki="Volkswagen", malli="Golf")
        kentat.setdefault("ostohinta", 820_000)
        return palvelut.avaa_kierto(a, self.d.admin, tila="myynnissa", **kentat)


class OstosopimusTestit(Pohja):
    def test_tarjottu_auto_varastoon_ostosopimuksella(self):
        k = self.tarjous(tarjottu_hinta=1_400_000)
        lomake = self.client.get(reverse("autot:ostosopimus", args=[k.pk]))
        self.assertEqual(lomake.context["kohde"]["hinta"].value(), "14000")  # esitäytetty pyydetyllä hinnalla

        vastaus = self.client.post(
            reverse("autot:ostosopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.yritys.pk,
                    "kohde-hinta": "13 500",
                    "kohde-km": "143000",
                    "kohde-kolaroitu": "ei",
                }
            ),
        )
        sopimus = Sopimus.objects.get(tyyppi="osto", rivit__kierto=k)
        self.assertRedirects(vastaus, reverse("autot:sopimus", args=[sopimus.pk]))
        k.refresh_from_db()
        self.assertEqual(
            (k.tila, k.ostohinta, k.ostopvm, k.toimittaja, k.km),
            ("ostettu", 1_350_000, sopimus.pvm, self.d.yritys, 143_000),
        )
        self.assertEqual(sopimus.numero, 2)  # apudatassa on jo sopimus nro 1
        self.assertEqual(sopimus.laatija, self.d.admin)
        rivi = sopimus.rivit.get()
        self.assertEqual(
            (rivi.hinta, rivi.rekisterinumero, rivi.merkki_malli, rivi.kolaroitu),
            (1_350_000, "TAR-111", "Skoda Octavia", "ei"),
        )
        self.assertTrue(Muutosloki.objects.filter(kohde_id=k.pk, kentta="ostosopimus").exists())
        self.assertTrue(k.tehtavat.filter(tila_vaihe="ostettu").exists())

    def test_alv_auton_ostohinta_verottomana(self):
        k = self.tarjous()
        self.client.post(
            reverse("autot:ostosopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-vp_nimi": "Leasing Oy",
                    "kohde-hinta": "12 550",
                    "kohde-alv_kasittely": "alv",
                }
            ),
        )
        k.refresh_from_db()
        self.assertEqual((k.ostohinta, k.alv_kasittely), (1_000_000, "alv"))
        self.assertEqual(SopimusRivi.objects.get(kierto=k).hinta, 1_255_000)

    def test_uusi_vastapuoli_lisataan_rekisteriin(self):
        k = self.tarjous()
        self.client.post(
            reverse("autot:ostosopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-vp_nimi": "Jarkko Myyjä",
                    "s-vp_tunnus": "010180-123A",
                    "s-vp_lahiosoite": "Tie 1",
                    "s-vp_tilinumero": "FI56 1325 3000 1060 54",
                }
            ),
        )
        yritys = Yritys.objects.get(nimi="Jarkko Myyjä")
        self.assertEqual(
            (yritys.y_tunnus, yritys.tilinumero, yritys.tyyppi), ("010180-123A", "FI56 1325 3000 1060 54", "yksityinen")
        )
        sopimus = Sopimus.objects.get(vastapuoli=yritys)
        self.assertEqual(sopimus.vp_lahiosoite, "Tie 1")

    def test_valittu_vastapuoli_taydentaa_ja_paivittyy(self):
        Yritys.objects.filter(pk=self.d.yritys.pk).update(puhelin="040 111", postitoimipaikka="Tampere")
        k = self.tarjous()
        self.client.post(
            reverse("autot:ostosopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.yritys.pk,
                    "s-vp_tilinumero": "FI00 123",
                }
            ),
        )
        sopimus = Sopimus.objects.get(rivit__kierto=k)
        self.assertEqual(
            (sopimus.vp_nimi, sopimus.vp_puhelin, sopimus.vp_postitoimipaikka, sopimus.vp_tilinumero),
            ("Testiliike Toimittaja Oy", "040 111", "Tampere", "FI00 123"),
        )
        self.assertEqual(Yritys.objects.get(pk=self.d.yritys.pk).tilinumero, "FI00 123")

    def test_vastapuoli_pakollinen(self):
        k = self.tarjous()
        vastaus = self.client.post(reverse("autot:ostosopimus", args=[k.pk]), lomakedata())
        self.assertEqual(vastaus.status_code, 422)
        self.assertContains(vastaus, "Valitse vastapuoli", status_code=422)
        k.refresh_from_db()
        self.assertEqual(k.tila, "tarjottu")

    def test_toista_ostosopimusta_ei_voi_tehda(self):
        # Apudatan autolla on jo ostosopimus
        vastaus = self.client.post(
            reverse("autot:ostosopimus", args=[self.d.kierto.pk]),
            lomakedata(**{"s-valittu": self.d.yritys.pk}),
            follow=True,
        )
        self.assertContains(vastaus, "Autolle ei voi tehdä ostosopimusta")
        self.assertEqual(Sopimus.objects.count(), 1)

    def test_ostosopimus_varastoautolle_ilman_sopimusta(self):
        k = self.varastoauto()
        self.client.post(
            reverse("autot:ostosopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.yritys.pk,
                    "kohde-hinta": "8 300",
                }
            ),
        )
        k.refresh_from_db()
        self.assertEqual((k.tila, k.ostohinta), ("myynnissa", 830_000))


class MyyntisopimusTestit(Pohja):
    def test_myynti_vaihtoautolla(self):
        """Golf 10 000 €, Corolla vaihdossa 3 000 €: asiakas maksaa 7 000 €, Corolla varastoon 3 000 €:lla."""
        golf = self.varastoauto(pyyntihinta=1_050_000)
        vastaus = self.client.post(
            reverse("autot:myyntisopimus", args=[golf.pk]),
            lomakedata(
                **{
                    "s-vp_nimi": "Matti Ostaja",
                    "kohde-hinta": "10 000",
                    "vaihto-0-rekisterinumero": "yyy321",
                    "vaihto-0-merkki": "Toyota",
                    "vaihto-0-malli": "Corolla",
                    "vaihto-0-km": "210000",
                    "vaihto-0-hinta": "3 000",
                    "vaihto-0-alv_kasittely": "marginaali",
                }
            ),
        )
        sopimus = Sopimus.objects.get(tyyppi="myynti")
        self.assertRedirects(vastaus, reverse("autot:sopimus", args=[sopimus.pk]))
        self.assertEqual(sopimus.summat().maksettava, 700_000)

        golf.refresh_from_db()
        asiakas = Yritys.objects.get(nimi="Matti Ostaja")
        self.assertEqual(
            (golf.tila, golf.myyntihinta, golf.asiakas, golf.myyntipvm), ("myyty", 1_000_000, asiakas, sopimus.pvm)
        )

        corolla = Kierto.objects.get(ajoneuvo__rekisterinumero="YYY-321")
        self.assertEqual(
            (corolla.tila, corolla.ostohinta, corolla.toimittaja, corolla.ostokanava, corolla.km),
            ("ostettu", 300_000, asiakas, "vaihto", 210_000),
        )
        self.assertEqual([r.rooli for r in sopimus.rivit.all()], ["kohde", "vaihto"])

        tuloste = self.client.get(reverse("autot:sopimus", args=[sopimus.pk]))
        self.assertContains(tuloste, "MYYNTISOPIMUS")
        self.assertContains(tuloste, "Toyota Corolla")
        self.assertContains(tuloste, "7 000,00 €")

    def test_palaava_auto_vaihdossa(self):
        """Vaihtoauto, joka on ollut meillä aiemmin: uusi kierros samalle ajoneuvolle."""
        vanha = self.varastoauto(rek="PAL-001")
        palvelut.siirra_tila(vanha, "myyty", self.d.admin, asiakas=self.d.asiakas, myyntihinta=900_000)
        golf = self.varastoauto(rek="GOL-002")
        self.client.post(
            reverse("autot:myyntisopimus", args=[golf.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "vaihto-0-rekisterinumero": "PAL 001",
                    "vaihto-0-merkki": "Volkswagen",
                    "vaihto-0-malli": "Golf",
                    "vaihto-0-hinta": "5 000",
                }
            ),
        )
        self.assertEqual(Ajoneuvo.objects.filter(rekisterinumero="PAL-001").count(), 1)
        self.assertEqual(Kierto.objects.filter(ajoneuvo=vanha.ajoneuvo).count(), 2)

    def test_vaihtoauto_jo_varastossa_ei_tallenna_mitaan(self):
        varastossa = self.varastoauto(rek="ON-123")
        golf = self.varastoauto(rek="GOL-003")
        vastaus = self.client.post(
            reverse("autot:myyntisopimus", args=[golf.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "vaihto-0-rekisterinumero": "ON-123",
                    "vaihto-0-merkki": "VW",
                    "vaihto-0-malli": "Golf",
                    "vaihto-0-hinta": "5 000",
                }
            ),
        )
        self.assertContains(vastaus, "avoin kierros", status_code=422)
        golf.refresh_from_db()
        self.assertEqual(golf.tila, "myynnissa")
        self.assertFalse(Sopimus.objects.filter(tyyppi="myynti").exists())
        self.assertEqual(Kierto.objects.filter(ajoneuvo=varastossa.ajoneuvo).count(), 1)

    def test_keskenerainen_vaihtorivi_hylataan(self):
        golf = self.varastoauto()
        vastaus = self.client.post(
            reverse("autot:myyntisopimus", args=[golf.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "vaihto-0-merkki": "Toyota",
                }
            ),
        )
        self.assertEqual(vastaus.status_code, 422)
        self.assertContains(vastaus, "Pakollinen vaihtoajoneuvolle", status_code=422)
        golf.refresh_from_db()
        self.assertEqual(golf.tila, "myynnissa")

    def test_alv_auton_myyntihinta_verottomana(self):
        k = self.varastoauto(alv_kasittely="alv", ostohinta=1_000_000)
        self.client.post(
            reverse("autot:myyntisopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "kohde-hinta": "15 060",
                }
            ),
        )
        k.refresh_from_db()
        self.assertEqual(k.myyntihinta, 1_200_000)
        sopimus = Sopimus.objects.get(tyyppi="myynti")
        tuloste = self.client.get(reverse("autot:sopimus", args=[sopimus.pk]))
        self.assertContains(tuloste, "3 060,00 €")  # ALV:n osuus

    def test_maksun_jakautuminen(self):
        k = self.varastoauto()
        self.client.post(
            reverse("autot:myyntisopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "s-toimistokulut": "199",
                    "s-etumaksu": "2 000",
                    "s-rahoitettava": "5 000",
                    "s-rahoitusyhtio": "Rahoitus Oy",
                    "s-maksutapa": "rahoitus",
                }
            ),
        )
        s = Sopimus.objects.get(tyyppi="myynti")
        self.assertEqual((s.summat().kateishinta, s.summat().toimituksessa), (1_019_900, 319_900))
        k.refresh_from_db()
        self.assertEqual(k.myyntihinta, 1_000_000)  # toimistokulut eivät ole auton myyntihintaa
        tuloste = self.client.get(reverse("autot:sopimus", args=[s.pk]))
        self.assertContains(tuloste, "Maksetaan toimituksen yhteydessä")
        self.assertContains(tuloste, "Rahoitus Oy")

    def test_tarjottua_autoa_ei_voi_myyda(self):
        k = self.tarjous()
        vastaus = self.client.get(reverse("autot:myyntisopimus", args=[k.pk]), follow=True)
        self.assertContains(vastaus, "Vain varastossa olevan auton voi myydä")

    def test_myyntisopimus_ilman_vaihtoa_ja_ehdot(self):
        self.d.liike.myyntiehdot = "1. Omat myyntiehdot."
        self.d.liike.save()
        k = self.varastoauto()
        self.client.post(
            reverse("autot:myyntisopimus", args=[k.pk]),
            lomakedata(
                **{
                    "s-valittu": self.d.asiakas.pk,
                    "s-vp2_nimi": "Maija Ostaja",
                }
            ),
        )
        s = Sopimus.objects.get(tyyppi="myynti")
        tuloste = self.client.get(reverse("autot:sopimus", args=[s.pk]))
        self.assertContains(tuloste, "Ei vaihtoajoneuvoa")
        self.assertContains(tuloste, "Omat myyntiehdot")
        self.assertContains(tuloste, "Maija Ostaja")


class KirjausTestit(Pohja):
    def test_uusi_auto_ostosopimukseen(self):
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "kirjaus": "ostosopimus",
                "alv_kasittely": "marginaali",
                "tarjottu_hinta": "9000",
            },
        )
        k = Kierto.objects.get(ajoneuvo__merkki="Kia")
        self.assertRedirects(vastaus, reverse("autot:ostosopimus", args=[k.pk]))
        self.assertEqual(k.tila, "tarjottu")

    def test_suoraan_varastoon_vaatii_ostohinnan(self):
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "kirjaus": "varasto",
                "alv_kasittely": "marginaali",
            },
        )
        self.assertContains(vastaus, "Anna ostohinta")
        self.assertFalse(Kierto.objects.filter(ajoneuvo__merkki="Kia").exists())

    def test_varastoauton_ostohintaa_ei_voi_poistaa(self):
        vastaus = self.client.post(
            reverse("autot:tallenna_kauppa", args=[self.d.kierto.pk]),
            {
                "toimittaja": self.d.yritys.pk,
                "ostohinta": "",
                "alv_kasittely": "marginaali",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 422)
        self.assertContains(vastaus, "pitää olla ostohinta", status_code=422)
        self.d.kierto.refresh_from_db()
        self.assertEqual(self.d.kierto.ostohinta, 1_000_000)

    def test_tarjotun_auton_ostohinta_saa_puuttua(self):
        k = self.tarjous()
        vastaus = self.client.post(
            reverse("autot:tallenna_kauppa", args=[k.pk]),
            {
                "ostohinta": "",
                "alv_kasittely": "marginaali",
                "tarjottu_hinta": "9 000",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 200)


class NakymaTestit(Pohja):
    def test_lista_ja_kortti(self):
        vastaus = self.client.get(reverse("autot:sopimukset"))
        self.assertContains(vastaus, "Testiliike Toimittaja Oy")
        self.assertEqual(self.client.get(reverse("autot:sopimukset") + "?tyyppi=myynti").context["rivit"], [])
        kortti = self.client.get(reverse("autot:kortti", args=[self.d.kierto.pk]))
        self.assertContains(kortti, reverse("autot:sopimus", args=[self.d.sopimus.pk]))
        self.assertContains(kortti, "Tee myyntisopimus")
        self.assertNotContains(kortti, "Tee ostosopimus")

    def test_vastapuolen_tiedot_htmx(self):
        Yritys.objects.filter(pk=self.d.asiakas.pk).update(lahiosoite="Asiakaskatu 5")
        vastaus = self.client.get(reverse("autot:vastapuoli") + f"?s-valittu={self.d.asiakas.pk}", **HTMX)
        self.assertContains(vastaus, 'value="Asiakaskatu 5"')
        self.assertContains(vastaus, 'id="vastapuolen-tiedot"')

    def test_sopimusnumerot_juoksevat(self):
        for rek in ["A-1", "B-2"]:
            k = self.tarjous(rek=rek)
            self.client.post(reverse("autot:ostosopimus", args=[k.pk]), lomakedata(**{"s-valittu": self.d.yritys.pk}))
        self.assertEqual(sorted(Sopimus.objects.values_list("numero", flat=True)), [1, 2, 3])

    def test_sopimuksen_tulostesivu(self):
        vastaus = self.client.get(reverse("autot:sopimus", args=[self.d.sopimus.pk]))
        self.assertContains(vastaus, "OSTOSOPIMUS")
        self.assertContains(vastaus, "window.print()")
        self.assertEqual(vastaus.context["summat"].maksettava, 1_000_000)
        self.assertEqual(timezone.localdate(), self.d.sopimus.pvm)
