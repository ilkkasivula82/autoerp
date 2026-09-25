"""Toiminnallisuus näkymien kautta: uusi auto, palaava auto, tilasiirrot, kulut, kuvat, tehtävät."""

from datetime import timedelta
from io import StringIO

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from autot import palvelut
from autot.models import Ajoneuvo, Kierto, Kulu, Kuva, Muutosloki, Tehtava, Tilahistoria, Yritys
from liikkeet.models import Kayttaja, Liike
from liikkeet.rajaus import liike_kaytossa

from .apu import SALASANA, kuvatiedosto, luo_liike

HTMX = {"HTTP_HX_REQUEST": "true"}


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

    def kortti(self, kid, v=None):
        return reverse("autot:kortti", args=[kid]) + (f"?v={v}" if v else "")


class KirjautuminenTestit(TestCase):
    def test_sahkoposti_ei_ole_kirjainkokoriippuvainen(self):
        d = luo_liike("L", "l")
        vastaus = self.client.post(reverse("kirjaudu"), {"username": "ADMIN@L.FI", "password": SALASANA})
        self.assertRedirects(vastaus, reverse("autot:etusivu"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), d.admin.pk)

    def test_vaara_salasana(self):
        luo_liike("L", "l")
        vastaus = self.client.post(reverse("kirjaudu"), {"username": "admin@l.fi", "password": "väärä"})
        self.assertContains(vastaus, "Väärä sähköposti tai salasana.")

    def test_uloskirjautuminen(self):
        d = luo_liike("L", "l")
        self.client.force_login(d.admin)
        self.client.post(reverse("kirjaudu_ulos"))
        self.assertEqual(self.client.get(reverse("autot:etusivu")).status_code, 302)


class UusiAutoTestit(Pohja):
    def test_uusi_tarjous(self):
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "rekisterinumero": "xyz 987",
                "vin": "wvwzzz1",
                "merkki": "Skoda",
                "malli": "Octavia",
                "km": "120000",
                "toimittaja": self.d.yritys.pk,
                "ostokanava": "huutokauppa",
                "tarjottu_hinta": "9 500",
                "alv_kasittely": "marginaali",
            },
        )
        k = Kierto.objects.select_related("ajoneuvo").get(ajoneuvo__merkki="Skoda")
        self.assertRedirects(vastaus, self.kortti(k.pk))
        self.assertEqual(k.ajoneuvo.rekisterinumero, "XYZ-987")
        self.assertEqual(k.ajoneuvo.vin, "WVWZZZ1")
        self.assertEqual(k.tila, "tarjottu")
        self.assertEqual(k.tarjottu_hinta, 950_000)
        self.assertEqual(k.km, 120_000)
        self.assertEqual(k.tarjottu_pvm, timezone.localdate())
        self.assertEqual(k.luonut, self.d.admin)
        self.assertEqual(list(k.tilahistoria.values_list("uusi_tila", flat=True)), ["tarjottu"])
        # Tehtäväpohjien tehtävät syntyivät
        self.assertEqual(k.tehtavat.count(), 2)

    def test_ostettu_heti_vaatii_ostohinnan(self):
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "heti_ostettu": "on",
                "alv_kasittely": "marginaali",
            },
        )
        self.assertEqual(vastaus.status_code, 200)
        self.assertContains(vastaus, "Anna ostohinta")
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "heti_ostettu": "on",
                "ostohinta": "8000",
                "alv_kasittely": "alv",
            },
        )
        k = Kierto.objects.get(ajoneuvo__merkki="Kia")
        self.assertEqual(
            (k.tila, k.ostohinta, k.alv_kasittely, k.ostopvm), ("ostettu", 800_000, "alv", timezone.localdate())
        )

    def test_virheellinen_summa(self):
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "tarjottu_hinta": "paljon",
                "alv_kasittely": "marginaali",
            },
        )
        self.assertContains(vastaus, "Anna summa euroina")
        self.assertFalse(Ajoneuvo.objects.filter(merkki="Kia").exists())

    def test_avoin_auto_avataan_eika_luoda_toista(self):
        # apu.luo_liike: autolla ABC-123 on avoin kierros
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "rekisterinumero": "abc123",
                "merkki": "Volvo",
                "malli": "x",
                "alv_kasittely": "marginaali",
            },
        )
        self.assertRedirects(vastaus, self.kortti(self.d.kierto.pk))
        self.assertEqual(Kierto.objects.filter(ajoneuvo=self.d.ajoneuvo).count(), 1)

    def test_tarkista_nayttaa_aiemman_auton(self):
        vastaus = self.client.get(reverse("autot:tarkista") + "?rekisterinumero=abc 123", **HTMX)
        self.assertContains(vastaus, "Tämä auto on ollut meillä aiemmin")
        self.assertContains(vastaus, "Autolla on jo avoin kierros")
        vastaus = self.client.get(reverse("autot:tarkista") + "?rekisterinumero=ZZZ-999", **HTMX)
        self.assertNotContains(vastaus, "aiemmin")


class PalaavaAutoTestit(Pohja):
    def myy(self, kierto):
        palvelut.siirra_tila(kierto, "myyty", self.d.admin, asiakas=self.d.asiakas, myyntihinta=1_500_000)
        palvelut.siirra_tila(kierto, "toimitettu", self.d.admin)

    def test_palaava_auto_saa_uuden_kierroksen(self):
        self.myy(self.d.kierto)
        vanha_kate = self.d.kierto.kate().kate
        vastaus = self.client.post(
            reverse("autot:uusi"),
            {
                "vin": self.d.ajoneuvo.vin.lower(),
                "merkki": "Volvo",
                "malli": "Uusi malli",
                "km": "150000",
                "alv_kasittely": "marginaali",
            },
        )
        uusi = Kierto.objects.exclude(pk=self.d.kierto.pk).get(ajoneuvo=self.d.ajoneuvo)
        self.assertRedirects(vastaus, self.kortti(uusi.pk))
        self.assertEqual(uusi.tila, "tarjottu")
        self.assertEqual(uusi.km, 150_000)
        self.assertEqual(Ajoneuvo.objects.count(), 1)
        # Ajoneuvon tieto päivittyi ja muutos kirjattiin
        self.d.ajoneuvo.refresh_from_db()
        self.assertEqual(self.d.ajoneuvo.malli, "Uusi malli")
        self.assertTrue(Muutosloki.objects.filter(kohde="ajoneuvo", kohde_id=self.d.ajoneuvo.pk, uusi="Uusi malli"))
        # Vanha kierros ja sen kate säilyivät
        self.d.kierto.refresh_from_db()
        self.assertEqual(self.d.kierto.tila, "toimitettu")
        self.assertEqual(self.d.kierto.kate().kate, vanha_kate)
        # Varusteet kuuluvat ajoneuvolle, joten ne näkyvät uudella kierroksella
        vastaus = self.client.get(self.kortti(uusi.pk, "varusteet"))
        self.assertEqual(vastaus.context["valitut"], {self.d.varuste.pk})

    def test_palaa_painike(self):
        self.myy(self.d.kierto)
        vastaus = self.client.post(reverse("autot:palaa", args=[self.d.kierto.pk]))
        uusi = Kierto.objects.exclude(pk=self.d.kierto.pk).get(ajoneuvo=self.d.ajoneuvo)
        self.assertRedirects(vastaus, self.kortti(uusi.pk, "kauppa"))
        # Toista avointa kierrosta ei voi avata
        self.client.post(reverse("autot:palaa", args=[self.d.kierto.pk]))
        self.assertEqual(Kierto.objects.filter(ajoneuvo=self.d.ajoneuvo).count(), 2)

    def test_tietokanta_estaa_kaksi_avointa_kierrosta(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Kierto.objects.create(ajoneuvo=self.d.ajoneuvo, tila="tarjottu")
        # Päättyneitä kierroksia saa olla monta
        Kierto.objects.create(ajoneuvo=self.d.ajoneuvo, tila="hylatty")
        Kierto.objects.create(ajoneuvo=self.d.ajoneuvo, tila="hylatty")


class TilasiirtoTestit(Pohja):
    def siirra(self, **data):
        return self.client.post(reverse("autot:vaihda_tila", args=[self.d.kierto.pk]), data, follow=True)

    def test_kielletty_siirto(self):
        vastaus = self.siirra(tila="tarjottu")
        self.assertContains(vastaus, "Tilasiirto ei ole sallittu.")
        self.d.kierto.refresh_from_db()
        self.assertEqual(self.d.kierto.tila, "myynnissa")

    def test_myynti_vaatii_ostajan_ja_hinnan(self):
        vastaus = self.siirra(tila="myyty", myyntihinta="13000")
        self.assertContains(vastaus, "Anna ostaja ja myyntihinta")
        self.d.kierto.refresh_from_db()
        self.assertEqual(self.d.kierto.tila, "myynnissa")

    def test_myynti(self):
        vastaus = self.siirra(tila="myyty", asiakas=self.d.asiakas.pk, myyntihinta="13 000,50", laskunumero="L-1")
        self.assertContains(vastaus, "Tila: Myyty.")
        k = Kierto.objects.get(pk=self.d.kierto.pk)
        self.assertEqual(
            (k.tila, k.myyntihinta, k.asiakas, k.myyntipvm, k.laskunumero),
            ("myyty", 1_300_050, self.d.asiakas, timezone.localdate(), "L-1"),
        )
        self.assertEqual(Tilahistoria.objects.filter(kierto=k).last().uusi_tila, "myyty")
        kentat = set(Muutosloki.objects.filter(kohde="kierto", kohde_id=k.pk).values_list("kentta", flat=True))
        self.assertTrue({"tila", "myyntihinta", "ostaja"} <= kentat)
        # Myyty-vaiheen tehtävät
        self.assertTrue(Tehtava.objects.filter(kierto=k, tila_vaihe="myyty").exists())

    def test_osto_vaatii_ostohinnan(self):
        kierto = palvelut.avaa_kierto(
            Ajoneuvo.objects.create(merkki="Kia", malli="Rio"), self.d.admin, tarjottu_hinta=None
        )
        with self.assertRaises(palvelut.SiirtoVirhe):
            palvelut.siirra_tila(kierto, "ostettu", self.d.admin)
        palvelut.siirra_tila(kierto, "ostettu", self.d.admin, ostohinta=500_000)
        self.assertEqual((kierto.tila, kierto.ostohinta, kierto.ostopvm), ("ostettu", 500_000, timezone.localdate()))

    def test_hylkays_ja_palautus(self):
        kierto = palvelut.avaa_kierto(Ajoneuvo.objects.create(merkki="Kia", malli="Rio"), self.d.admin)
        palvelut.siirra_tila(kierto, "hylatty", self.d.admin, hylkayksen_syy="Liian kallis")
        self.assertEqual((kierto.tila, kierto.hylkayksen_syy), ("hylatty", "Liian kallis"))
        palvelut.siirra_tila(kierto, "tarjottu", self.d.admin)
        self.assertEqual(kierto.tila, "tarjottu")

    def test_taaksepain_siirto_ei_vaadi_tietoja(self):
        palvelut.siirra_tila(self.d.kierto, "myyty", self.d.admin, asiakas=self.d.asiakas, myyntihinta=1)
        palvelut.siirra_tila(self.d.kierto, "myynnissa", self.d.admin)
        self.assertEqual(self.d.kierto.tila, "myynnissa")

    def test_vaihekestot(self):
        historia = list(self.d.kierto.tilahistoria.all())
        historia[0].aika = timezone.now() - timedelta(days=5)
        kestot = palvelut.vaihekestot(historia)
        self.assertEqual(kestot[0][1], 5)


class KuluJaKateTestit(Pohja):
    def test_verollinen_kulu_muunnetaan_verottomaksi(self):
        vastaus = self.client.post(
            reverse("autot:lisaa_kulu", args=[self.d.kierto.pk]),
            {
                "tyyppi": "kuljetus",
                "summa": "125,50",
                "summa_on": "verollinen",
                "alv_prosentti": "25,5",
                "pvm": "2026-03-01",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 200)
        self.assertContains(vastaus, "Kulu lisätty.")
        kulu = Kulu.objects.get(tyyppi="kuljetus")
        self.assertEqual(kulu.summa_veroton, 10_000)
        self.assertEqual(kulu.luonut, self.d.admin)
        self.assertTrue(Muutosloki.objects.filter(kentta="kulu lisätty").exists())

    def test_virheellinen_kulu_nayttaa_virheen(self):
        vastaus = self.client.post(
            reverse("autot:lisaa_kulu", args=[self.d.kierto.pk]),
            {
                "tyyppi": "kuljetus",
                "summa": "",
                "summa_on": "veroton",
                "alv_prosentti": "25,5",
                "pvm": "2026-03-01",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 422)
        self.assertEqual(Kulu.objects.count(), 1)

    def test_jalkikulu_pienentaa_lopullista_katetta(self):
        Kulu.objects.filter(pk=self.d.kulu.pk).update(pvm=timezone.localdate() - timedelta(days=20))
        palvelut.siirra_tila(
            self.d.kierto,
            "myyty",
            self.d.admin,
            asiakas=self.d.asiakas,
            myyntihinta=1_251_000,
            myyntipvm=timezone.localdate() - timedelta(days=10),
        )
        ennen = self.d.kierto.kate()
        vastaus = self.client.post(
            reverse("autot:lisaa_kulu", args=[self.d.kierto.pk]),
            {
                "tyyppi": "reklamaatio",
                "summa": "300",
                "summa_on": "veroton",
                "alv_prosentti": "25,5",
                "pvm": timezone.localdate().isoformat(),
            },
            follow=True,
        )
        self.assertContains(vastaus, "Jälkikulu kirjattu")
        kierto = Kierto.objects.get(pk=self.d.kierto.pk)
        jalkeen = kierto.kate()
        self.assertEqual(jalkeen.jalkikulut, 30_000)
        self.assertEqual(jalkeen.kate, ennen.kate - 30_000)
        self.assertEqual(jalkeen.kate_myyntihetki, ennen.kate)
        # Annotaatio antaa saman tuloksen kuin rivikohtainen laskenta
        annotoitu = Kierto.objects.kulusummilla().get(pk=kierto.pk)
        self.assertEqual(annotoitu.kulusummat(), (42_300, 30_000))
        self.assertEqual(annotoitu.kate(), jalkeen)

    def test_kulun_poisto(self):
        self.client.post(reverse("autot:poista_kulu", args=[self.d.kierto.pk, self.d.kulu.pk]))
        self.assertFalse(Kulu.objects.exists())
        self.assertTrue(Muutosloki.objects.filter(kentta="kulu poistettu").exists())

    def test_kate_nakyy_kortilla(self):
        vastaus = self.client.get(self.kortti(self.d.kierto.pk))
        kate = vastaus.context["kate"]
        self.assertTrue(kate.arvio)  # myymätön: arvio pyyntihinnalla
        self.assertEqual(kate.myynti, 1_300_000)
        self.assertContains(vastaus, "arvio pyyntihinnalla")


class KauppaJaAjoneuvoTestit(Pohja):
    def test_hintamuutos_kirjataan_lokiin(self):
        vastaus = self.client.post(
            reverse("autot:tallenna_kauppa", args=[self.d.kierto.pk]),
            {
                "toimittaja": self.d.yritys.pk,
                "ostohinta": "10000",
                "pyyntihinta": "14 900",
                "alv_kasittely": "marginaali",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 200)
        self.d.kierto.refresh_from_db()
        self.assertEqual(self.d.kierto.pyyntihinta, 1_490_000)
        loki = Muutosloki.objects.get(kentta="pyyntihinta")
        self.assertEqual((loki.vanha, loki.uusi, loki.kayttaja), ("13 000,00 €", "14 900,00 €", self.d.admin))
        # Ostohinta ei muuttunut (10 000 € = 1 000 000 senttiä), joten siitä ei kirjattu uutta riviä
        self.assertFalse(Muutosloki.objects.filter(kentta="ostohinta").exclude(uusi="Loki t").exists())

    def test_ajoneuvon_tiedot(self):
        self.client.post(
            reverse("autot:tallenna_ajoneuvo", args=[self.d.kierto.pk]),
            {
                "rekisterinumero": "def 456",
                "merkki": "Volvo",
                "malli": "V70",
                "kayttovoima": "02",
            },
        )
        self.d.ajoneuvo.refresh_from_db()
        self.assertEqual(
            (self.d.ajoneuvo.rekisterinumero, self.d.ajoneuvo.malli, self.d.ajoneuvo.kayttovoima),
            ("DEF-456", "V70", "02"),
        )
        self.assertTrue(Muutosloki.objects.filter(kohde="ajoneuvo", kentta="rekisterinumero", uusi="DEF-456"))

    def test_tuntematon_koodi_hylataan(self):
        vastaus = self.client.post(
            reverse("autot:tallenna_ajoneuvo", args=[self.d.kierto.pk]),
            {
                "merkki": "Volvo",
                "malli": "V70",
                "kayttovoima": "XX",
            },
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 422)


class KuvaTestit(Pohja):
    def test_lataus_pienennys_ja_naytto(self):
        vastaus = self.client.post(
            reverse("autot:lataa_kuvat", args=[self.d.kierto.pk]),
            {
                "tyyppi": "sisa",
                "kuvat": [kuvatiedosto("a.jpg", (3000, 2000)), kuvatiedosto("b.jpg")],
            },
            **HTMX,
        )
        self.assertContains(vastaus, "2 kuvaa lisätty.")
        kuvat = list(Kuva.objects.filter(tyyppi="sisa").order_by("jarjestys"))
        self.assertEqual(len(kuvat), 2)
        from PIL import Image

        with default_storage.open(kuvat[0].avain) as f:
            self.assertEqual(max(Image.open(f).size), 2000)
        with default_storage.open(kuvat[0].avain[:-4] + "_t.jpg") as f:
            self.assertEqual(max(Image.open(f).size), 480)
        vastaus = self.client.get(reverse("autot:kuva_koko", args=[kuvat[0].pk, "pieni"]))
        self.assertEqual(vastaus.status_code, 200)
        self.assertEqual(vastaus["Content-Type"], "image/jpeg")

    def test_rikkinainen_kuva(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        vastaus = self.client.post(
            reverse("autot:lataa_kuvat", args=[self.d.kierto.pk]),
            {
                "tyyppi": "ulko",
                "kuvat": [SimpleUploadedFile("x.jpg", b"ei kuva")],
            },
            follow=True,
        )
        self.assertContains(vastaus, "ei voitu lukea")
        self.assertEqual(Kuva.objects.count(), 1)

    def test_paakuva_ja_poisto(self):
        self.client.post(
            reverse("autot:lataa_kuvat", args=[self.d.kierto.pk]), {"tyyppi": "ulko", "kuvat": [kuvatiedosto()]}
        )
        uusi = Kuva.objects.exclude(pk=self.d.kuva.pk).get()
        self.client.post(reverse("autot:aseta_paakuva", args=[uusi.pk]))
        self.assertEqual(list(Kuva.objects.filter(paakuva=True)), [uusi])
        avain = uusi.avain
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("autot:poista_kuva", args=[uusi.pk]))
        self.assertFalse(Kuva.objects.filter(pk=uusi.pk).exists())
        self.assertFalse(default_storage.exists(avain))

    def test_vaurio_kuvalla(self):
        self.client.post(
            reverse("autot:lisaa_vaurio", args=[self.d.kierto.pk]),
            {
                "kohta": "Konepelti",
                "arvioitu_korjaus": "250",
                "kuvatiedosto": kuvatiedosto(),
            },
        )
        vaurio = self.d.kierto.vauriot.get(kohta="Konepelti")
        self.assertEqual(vaurio.arvioitu_korjaus, 25_000)
        self.assertEqual(vaurio.kuva.tyyppi, "vaurio")


class KuntoJaVarusteTestit(Pohja):
    def test_kuntoraportit_ja_erot(self):
        self.client.post(
            reverse("autot:tallenna_kunto", args=[self.d.kierto.pk, "saapuminen"]),
            {
                "saapuminen-avaimet": "1",
                "saapuminen-maalipinta": "3",
                "saapuminen-tuulilasi": "ehja",
            },
        )
        vastaus = self.client.get(self.kortti(self.d.kierto.pk, "kunto"))
        rivit = {r["nimi"]: r["ero"] for r in vastaus.context["kuntorivit"]}
        self.assertTrue(rivit["Avaimet (kpl)"])  # tarjous 2, saapuminen 1
        self.assertFalse(rivit["Tuulilasi"])  # tarjousvaiheessa ei tietoa

    def test_varusteet_ja_kopiointi(self):
        from autot.models import AjoneuvonVaruste, Varuste

        toinen = Varuste.objects.exclude(pk=self.d.varuste.pk).first()
        self.client.post(reverse("autot:tallenna_varusteet", args=[self.d.kierto.pk]), {"varuste": [toinen.pk]})
        self.assertEqual(list(self.d.ajoneuvo.varusteet.all()), [toinen])
        auto2 = Ajoneuvo.objects.create(merkki="Volvo", malli="V90")
        k2 = palvelut.avaa_kierto(auto2, self.d.admin)
        self.client.post(reverse("autot:kopioi_varusteet", args=[k2.pk]), {"lahde": self.d.kierto.pk})
        self.assertEqual(
            list(AjoneuvonVaruste.objects.filter(ajoneuvo=auto2).values_list("varuste", flat=True)), [toinen.pk]
        )


class TehtavaTestit(Pohja):
    def test_kuittaus_htmx(self):
        vastaus = self.client.post(reverse("autot:kuittaa", args=[self.d.tehtava.pk]), {"nayta_auto": "1"}, **HTMX)
        self.assertContains(vastaus, 'class="tehtava tehty"')
        t = Tehtava.objects.get(pk=self.d.tehtava.pk)
        self.assertTrue(t.tehty)
        self.assertEqual(t.tehnyt, self.d.admin)
        self.client.post(reverse("autot:kuittaa", args=[t.pk]), **HTMX)
        self.assertFalse(Tehtava.objects.get(pk=t.pk).tehty)

    def test_kuittaus_ei_ohjaa_ulkopuolelle(self):
        vastaus = self.client.post(
            reverse("autot:kuittaa", args=[self.d.tehtava.pk]), {"takaisin": "https://paha.example/"}
        )
        self.assertEqual(vastaus["Location"], self.kortti(self.d.kierto.pk, "tehtavat"))

    def test_omat_tehtavat_roolin_mukaan(self):
        Tehtava.objects.create(kierto=self.d.kierto, otsikko="Roolille", rooli="myynti")
        Tehtava.objects.create(kierto=self.d.kierto, otsikko="Toiselle roolille", rooli="talous")
        self.client.force_login(self.d.myyja)
        vastaus = self.client.get(reverse("autot:etusivu"))
        self.assertContains(vastaus, "Roolille")
        self.assertContains(vastaus, "Tehtävä t")  # nimetty suoraan myyjälle
        self.assertNotContains(vastaus, "Toiselle roolille")

    def test_tehtavan_lisays_ja_poisto(self):
        self.client.post(
            reverse("autot:lisaa_tehtava", args=[self.d.kierto.pk]),
            {"otsikko": "Vie katsastukseen", "vastuu": self.d.myyja.pk},
            **HTMX,
        )
        t = Tehtava.objects.get(otsikko="Vie katsastukseen")
        self.assertEqual((t.vastuu, t.tila_vaihe, t.luonut), (self.d.myyja, "myynnissa", self.d.admin))
        self.client.post(reverse("autot:poista_tehtava", args=[self.d.kierto.pk, t.pk]), **HTMX)
        self.assertFalse(Tehtava.objects.filter(pk=t.pk).exists())


class OikeusTestit(Pohja):
    def test_vain_admin_hallitsee_kayttajia_ja_asetuksia(self):
        self.client.force_login(self.d.myyja)
        self.assertEqual(self.client.get(reverse("autot:kayttajat")).status_code, 403)
        self.assertEqual(self.client.get(reverse("autot:asetukset")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("autot:asetukset"), {"toiminto": "liike", "nimi": "X", "alv_prosentti": "1"}
            ).status_code,
            403,
        )

    def test_uusi_kayttaja_kuuluu_omaan_liikkeeseen(self):
        self.client.post(
            reverse("autot:kayttajat"),
            {
                "uusi-nimi": "Uusi Käyttäjä",
                "uusi-sahkoposti": "Uusi@T.fi",
                "uusi-rooli": "osto",
                "uusi-salasana": "pitka-salasana",
            },
        )
        uusi = Kayttaja.objects.get(sahkoposti="uusi@t.fi")
        self.assertEqual(uusi.liike, self.d.liike)
        self.assertTrue(uusi.check_password("pitka-salasana"))

    def test_admin_ei_voi_poistaa_omia_oikeuksiaan(self):
        pk = self.d.admin.pk
        self.client.post(reverse("autot:kayttajat"), {"id": pk, f"k{pk}-nimi": "A", f"k{pk}-rooli": "myynti"})
        self.assertEqual(Kayttaja.objects.get(pk=pk).rooli, "admin")


class SivutTestit(TestCase):
    """Demoliikkeen kaikki sivut. Ei peri Pohjaa: testi kirjautuu demoliikkeen käyttäjänä."""

    def kortti(self, kid, v):
        return reverse("autot:kortti", args=[kid]) + f"?v={v}"

    def test_kaikki_sivut_ja_valilehdet_aukeavat(self):
        call_command("demodata", "--nimi", "Demo", "--sahkopostipaate", "demo.test", stdout=StringIO())
        demo = Liike.objects.get(nimi="Demo")
        self.client.force_login(Kayttaja.objects.get(sahkoposti="admin@demo.test"))
        urlit = [
            reverse("autot:etusivu"),
            reverse("autot:lista"),
            reverse("autot:lista") + "?n=tarjotut",
            reverse("autot:lista") + "?n=myydyt",
            reverse("autot:lista") + "?tila=myynnissa&q=golf",
            reverse("autot:uusi"),
            reverse("autot:tehtavat"),
            reverse("autot:yritykset"),
            reverse("autot:raportit"),
            reverse("autot:kayttajat"),
            reverse("autot:varusteet"),
            reverse("autot:tehtavapohjat"),
            reverse("autot:asetukset"),
        ]
        with liike_kaytossa(demo):
            kierrot = list(Kierto.objects.values_list("pk", flat=True))
            urlit.append(reverse("autot:yritys", args=[Yritys.objects.first().pk]))
        self.assertEqual(len(kierrot), 10)
        for kid in kierrot:
            for v in [
                "yhteenveto",
                "kauppa",
                "ajoneuvo",
                "kulut",
                "kunto",
                "kuvat",
                "varusteet",
                "tehtavat",
                "historia",
            ]:
                urlit.append(self.kortti(kid, v))
        for url in urlit:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for v in ["kulut", "historia"]:
            vastaus = self.client.get(reverse("autot:valilehti", args=[kierrot[0], v]), **HTMX)
            self.assertContains(vastaus, 'id="valilehdet" hx-swap-oob="true"')
            self.assertNotContains(vastaus, "<html")

    def test_raportin_luvut(self):
        call_command("demodata", "--nimi", "Demo", "--sahkopostipaate", "demo.test", stdout=StringIO())
        self.client.force_login(Kayttaja.objects.get(sahkoposti="admin@demo.test"))
        vastaus = self.client.get(reverse("autot:raportit") + "?alku=2000-01-01&loppu=2100-01-01")
        yht = vastaus.context["yht"]
        # Demossa neljä myytyä: Mercedes, Audi (vanha kierros), Peugeot, Tesla
        self.assertEqual(yht["n"], 4)
        self.assertEqual(yht["kate"], sum(r.kate_.kate for r in vastaus.context["rivit"]))


class KomentoTestit(TestCase):
    def test_demodata_ja_korvaus(self):
        call_command("demodata", stdout=StringIO())
        with self.assertRaisesMessage(Exception, "on jo olemassa"):
            call_command("demodata", stdout=StringIO())
        call_command("demodata", "--korvaa", stdout=StringIO())
        self.assertEqual(Liike.objects.filter(nimi="Demo Autot Oy").count(), 1)
        liike = Liike.objects.get(nimi="Demo Autot Oy")
        with liike_kaytossa(liike):
            self.assertEqual(Kierto.objects.count(), 10)
            self.assertEqual(Ajoneuvo.objects.count(), 9)

    def test_luo_liike(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"ADMIN_SALASANA": "hyva-salasana-1"}):
            call_command("luo_liike", "--nimi", "N247 Finland Oy", "--sahkoposti", "Admin@N247.fi", stdout=StringIO())
        liike = Liike.objects.get(nimi="N247 Finland Oy")
        admin = Kayttaja.objects.get(sahkoposti="admin@n247.fi")
        self.assertEqual((admin.liike, admin.rooli), (liike, "admin"))
        with liike_kaytossa(liike):
            from autot.models import Koodi, Tehtavapohja, Varuste

            self.assertTrue(Koodi.objects.exists())
            self.assertTrue(Varuste.objects.exists())
            self.assertTrue(Tehtavapohja.objects.exists())
            self.assertFalse(Kierto.objects.exists())


class TerveysTestit(TestCase):
    def test_terveystarkistus_ilman_kirjautumista(self):
        vastaus = self.client.get("/terveys/")
        self.assertEqual(vastaus.status_code, 200)
        self.assertEqual(vastaus.content, b"ok")
