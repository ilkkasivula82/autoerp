"""Monivuokraajuus: käyttäjä ei koskaan näe eikä muuta toisen liikkeen dataa.

Testeissä on kaksi liikettä (A ja B), joilla kummallakin on rivi jokaisessa
liikekohtaisessa taulussa. Käyttäjä A yrittää lukea ja muuttaa B:n rivejä
kaikkien reittien kautta.
"""

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase
from django.urls import reverse

from autot.models import (
    Ajoneuvo,
    AjoneuvonVaruste,
    Kierto,
    Kulu,
    Kuntoraportti,
    Kuva,
    Rengassarja,
    Tehtava,
    Tehtavapohja,
    Varuste,
    Varustekategoria,
    Vaurio,
    Yritys,
)
from liikkeet.models import Kayttaja
from liikkeet.rajaus import (
    LiikeEiAktiivinen,
    LiikeManager,
    LiikkeenMalli,
    VaaraLiike,
    aktiivinen_liike_id,
    liike_kaytossa,
)

from .apu import SALASANA, kuvatiedosto, luo_liike

HTMX = {"HTTP_HX_REQUEST": "true"}


def liikemallit():
    return [m for m in apps.get_models() if issubclass(m, LiikkeenMalli)]


class Pohja(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Sama rekisteri ja VIN molemmissa liikkeissä: tunnistus ei saa sekoittaa niitä.
        cls.a = luo_liike("Liike A", "a", rek="SAM-111", vin="SAMAVIN000000001")
        cls.b = luo_liike("Liike B", "b", rek="SAM-111", vin="SAMAVIN000000001")

    def setUp(self):
        self.client.force_login(self.a.admin)


class RakenneTestit(TestCase):
    def test_jokainen_taulu_kuuluu_liikkeelle(self):
        """Kaikki sovelluksen mallit ovat liikekohtaisia (paitsi Liike itse ja Kayttaja, jolla on liike-kenttä)."""
        for malli in apps.get_app_config("autot").get_models():
            with self.subTest(malli=malli.__name__):
                self.assertTrue(issubclass(malli, LiikkeenMalli))
                self.assertIsInstance(malli._default_manager, LiikeManager)
                kentta = malli._meta.get_field("liike")
                self.assertFalse(kentta.null)
        self.assertFalse(Kayttaja._meta.get_field("liike").null)

    def test_ilman_liiketta_kysely_ei_palauta_mitaan_vaan_nostaa_virheen(self):
        luo_liike("Liike C", "c")
        self.assertIsNone(aktiivinen_liike_id())
        for malli in liikemallit():
            with self.subTest(malli=malli.__name__):
                with self.assertRaises(LiikeEiAktiivinen):
                    list(malli.objects.all())
                with self.assertRaises(LiikeEiAktiivinen):
                    malli.objects.count()
                with self.assertRaises(LiikeEiAktiivinen):
                    malli.objects.exists()
                with self.assertRaises(LiikeEiAktiivinen):
                    malli.objects.update()
                with self.assertRaises(LiikeEiAktiivinen):
                    malli.objects.all().delete()
        with self.assertRaises(LiikeEiAktiivinen):
            list(Kayttaja.liikkeen.all())

    def test_ilman_liiketta_luotu_kysely_ei_toimi_myohemminkaan(self):
        """Moduulitasolla luotu kysely ei saa vuotaa, vaikka liike aktivoitaisiin myöhemmin."""
        c = luo_liike("Liike C", "c")
        kysely = Kierto.objects.all()
        with liike_kaytossa(c.liike), self.assertRaises(LiikeEiAktiivinen):
            list(kysely)
        with liike_kaytossa(c.liike):
            # Alikyselynä tyhjä: ei rivejä
            self.assertEqual(Kulu.objects.filter(kierto__in=kysely).count(), 0)

    def test_tallennus_ilman_liiketta_vaatii_liikkeen(self):
        with self.assertRaises(LiikeEiAktiivinen):
            Yritys(nimi="X").save()


class ManageriTestit(Pohja):
    def test_oletusmanageri_rajaa_aktiiviseen_liikkeeseen(self):
        for malli in liikemallit():
            with self.subTest(malli=malli.__name__):
                with liike_kaytossa(self.a.liike):
                    a_rivit = set(malli.objects.values_list("liike_id", flat=True))
                with liike_kaytossa(self.b.liike):
                    b_rivit = set(malli.objects.values_list("liike_id", flat=True))
                self.assertEqual(a_rivit, {self.a.liike.pk})
                self.assertEqual(b_rivit, {self.b.liike.pk})

    def test_toisen_liikkeen_rivia_ei_loydy_id_lla(self):
        with liike_kaytossa(self.a.liike):
            for nimi in ["kierto", "kulu", "tehtava", "kuva", "yritys", "ajoneuvo", "varuste", "vaurio"]:
                olio = getattr(self.b, nimi)
                with self.subTest(nimi=nimi):
                    self.assertFalse(type(olio).objects.filter(pk=olio.pk).exists())

    def test_kaanteiset_relaatiot_rajautuvat(self):
        with liike_kaytossa(self.a.liike):
            self.assertEqual(self.a.kierto.kulut.count(), 1)
            self.assertEqual(Kayttaja.liikkeen.count(), 2)

    def test_toisen_liikkeen_rivin_tallennus_estetaan(self):
        with liike_kaytossa(self.a.liike):
            self.b.yritys.nimi = "Kaapattu"
            with self.assertRaises(VaaraLiike):
                self.b.yritys.save()
            with self.assertRaises(VaaraLiike):
                self.b.kulu.delete()
            with self.assertRaises(VaaraLiike):
                Kayttaja.objects.get(pk=self.b.myyja.pk).save()
        with liike_kaytossa(self.b.liike):
            self.assertEqual(Yritys.objects.get(pk=self.b.yritys.pk).nimi, "Liike B Toimittaja Oy")
            self.assertTrue(Kulu.objects.filter(pk=self.b.kulu.pk).exists())

    def test_viittaus_toisen_liikkeen_riviin_estetaan(self):
        with liike_kaytossa(self.a.liike):
            yritykset = [
                lambda: Kulu.objects.create(kierto=self.b.kierto, summa_veroton=1),
                lambda: Kulu.objects.create(kierto_id=self.b.kierto.pk, summa_veroton=1),
                lambda: Kierto.objects.create(ajoneuvo=self.a.ajoneuvo, toimittaja=self.b.yritys, tila="hylatty"),
                lambda: Tehtava.objects.create(kierto=self.a.kierto, otsikko="x", vastuu=self.b.myyja),
                lambda: Varuste.objects.create(kategoria=self.b.kategoria, nimi="x"),
                lambda: AjoneuvonVaruste.objects.create(ajoneuvo=self.a.ajoneuvo, varuste=self.b.varuste),
                lambda: Vaurio.objects.create(kierto=self.a.kierto, kohta="x", kuva=self.b.kuva),
            ]
            for i, luonti in enumerate(yritykset):
                with self.subTest(i=i), self.assertRaises(VaaraLiike):
                    luonti()

    def test_konteksti_palautuu(self):
        self.assertIsNone(aktiivinen_liike_id())
        with liike_kaytossa(self.a.liike):
            with liike_kaytossa(self.b.liike):
                self.assertEqual(aktiivinen_liike_id(), self.b.liike.pk)
            self.assertEqual(aktiivinen_liike_id(), self.a.liike.pk)
        self.assertIsNone(aktiivinen_liike_id())


class LukuTestit(Pohja):
    """Käyttäjä A pyytää B:n rivejä: aina 404, eikä B:n tietoja näy missään."""

    def test_kortti_ja_valilehdet(self):
        kid = self.b.kierto.pk
        self.assertEqual(self.client.get(reverse("autot:kortti", args=[kid])).status_code, 404)
        for v in ["yhteenveto", "kauppa", "ajoneuvo", "kulut", "kunto", "kuvat", "varusteet", "tehtavat", "historia"]:
            with self.subTest(v=v):
                self.assertEqual(self.client.get(reverse("autot:valilehti", args=[kid, v]), **HTMX).status_code, 404)
                self.assertEqual(self.client.get(reverse("autot:kortti", args=[kid]) + f"?v={v}").status_code, 404)

    def test_kuva(self):
        default_storage.save(self.b.kuva.avain, ContentFile(b"salainen"))
        for url in [
            reverse("autot:kuva", args=[self.b.kuva.pk]),
            reverse("autot:kuva_koko", args=[self.b.kuva.pk, "pieni"]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_yritys(self):
        self.assertEqual(self.client.get(reverse("autot:yritys", args=[self.b.yritys.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("autot:yritykset") + f"?muokkaa={self.b.yritys.pk}").status_code, 404)

    def test_listat_eivat_nayta_toisen_liikkeen_tietoja(self):
        urlit = [
            reverse("autot:etusivu"),
            reverse("autot:lista") + "?n=kaikki",
            reverse("autot:lista") + "?n=kaikki&q=SAM",
            reverse("autot:tehtavat") + "?nayta=kaikki",
            reverse("autot:yritykset"),
            reverse("autot:raportit") + "?alku=2000-01-01&loppu=2100-01-01",
            reverse("autot:kayttajat"),
            reverse("autot:tehtavapohjat"),
            reverse("autot:varusteet"),
            reverse("autot:asetukset"),
            reverse("autot:kortti", args=[self.a.kierto.pk]) + "?v=historia",
            reverse("autot:kortti", args=[self.a.kierto.pk]) + "?v=tehtavat",
            reverse("autot:kortti", args=[self.a.kierto.pk]) + "?v=kunto",
            reverse("autot:kortti", args=[self.a.kierto.pk]) + "?v=varusteet",
        ]
        for url in urlit:
            with self.subTest(url=url):
                vastaus = self.client.get(url)
                self.assertEqual(vastaus.status_code, 200)
                sisalto = vastaus.content.decode()
                for vieras in ["Liike B", "Malli-b", "Kulu b", "Tehtävä b", "Vaurio b", "Loki b", "@b.fi"]:
                    self.assertNotIn(vieras, sisalto)
                self.assertNotIn(f"/autot/{self.b.kierto.pk}/", sisalto)

    def test_palaavan_auton_tunnistus_ei_katso_toista_liiketta(self):
        # Luodaan B:lle auto, jota A:lla ei ole
        with liike_kaytossa(self.b.liike):
            Ajoneuvo.objects.create(rekisterinumero="BBB-999", vin="BVIN000000000009", merkki="Saab", malli="9-5")
        for parametrit in ["?rekisterinumero=BBB-999", "?vin=BVIN000000000009"]:
            with self.subTest(p=parametrit):
                vastaus = self.client.get(reverse("autot:tarkista") + parametrit, **HTMX)
                self.assertNotIn("Saab", vastaus.content.decode())

    def test_uusi_auto_samalla_vinilla_ei_liity_toisen_liikkeen_ajoneuvoon(self):
        with liike_kaytossa(self.b.liike):
            Ajoneuvo.objects.create(vin="BVIN000000000009", merkki="Saab", malli="9-5")
        self.client.post(
            reverse("autot:uusi"),
            {"vin": "BVIN000000000009", "merkki": "Saab", "malli": "9-5", "alv_kasittely": "marginaali"},
        )
        with liike_kaytossa(self.a.liike):
            uusi = Ajoneuvo.objects.get(vin="BVIN000000000009")
        self.assertEqual(uusi.liike_id, self.a.liike.pk)
        self.assertEqual(Ajoneuvo.kaikki.filter(vin="BVIN000000000009").count(), 2)


class KirjoitusTestit(Pohja):
    """Käyttäjä A yrittää muuttaa B:n rivejä: 404 tai hylätty lomake, eikä B:n data muutu."""

    def assert_b_ennallaan(self):
        with liike_kaytossa(self.b.liike):
            k = Kierto.objects.get(pk=self.b.kierto.pk)
            self.assertEqual(k.tila, "myynnissa")
            self.assertEqual(k.ostohinta, 1_000_000)
            self.assertEqual(k.asiakas_id, None)
            self.assertEqual(Kulu.objects.count(), 1)
            self.assertEqual(Tehtava.objects.get(pk=self.b.tehtava.pk).tehty, False)
            self.assertEqual(Kuva.objects.count(), 1)
            self.assertEqual(Rengassarja.objects.count(), 1)
            self.assertEqual(Vaurio.objects.get(pk=self.b.vaurio.pk).korjattu, False)
            self.assertEqual(AjoneuvonVaruste.objects.count(), 1)
            self.assertEqual(Yritys.objects.get(pk=self.b.yritys.pk).nimi, "Liike B Toimittaja Oy")
            self.assertEqual(Ajoneuvo.objects.get(pk=self.b.ajoneuvo.pk).merkki, "Volvo")
            self.assertEqual(Kuntoraportti.objects.get(pk=self.b.raportti.pk).avaimet, 2)
            self.assertEqual(Varuste.objects.get(pk=self.b.varuste.pk).aktiivinen, True)
            self.assertTrue(Tehtavapohja.objects.filter(pk=self.b.pohja.pk).exists())
            self.assertTrue(Varustekategoria.objects.filter(pk=self.b.kategoria.pk).exists())
            self.assertEqual(Kayttaja.liikkeen.get(pk=self.b.myyja.pk).rooli, "myynti")

    def test_kierron_toiminnot_404(self):
        b, kid = self.b, self.b.kierto.pk
        pyynnot = [
            ("autot:vaihda_tila", [kid], {"tila": "varattu"}),
            ("autot:palaa", [kid], {}),
            ("autot:tallenna_ajoneuvo", [kid], {"merkki": "Kaapattu", "malli": "x"}),
            ("autot:tallenna_kauppa", [kid], {"ostohinta": "1", "alv_kasittely": "alv"}),
            (
                "autot:lisaa_kulu",
                [kid],
                {"tyyppi": "muu", "summa": "5", "summa_on": "veroton", "alv_prosentti": "0", "pvm": "2026-01-01"},
            ),
            ("autot:poista_kulu", [kid, b.kulu.pk], {}),
            ("autot:tallenna_kunto", [kid, "tarjous"], {"tarjous-avaimet": "9"}),
            ("autot:lisaa_rengas", [kid], {"tyyppi": "kesa", "sijainti": "alla"}),
            ("autot:poista_rengas", [kid, b.rengas.pk], {}),
            ("autot:lisaa_vaurio", [kid], {"kohta": "x"}),
            ("autot:vaurio_korjattu", [kid, b.vaurio.pk], {}),
            ("autot:lataa_kuvat", [kid], {"tyyppi": "ulko"}),
            ("autot:tallenna_varusteet", [kid], {"varuste": []}),
            ("autot:kopioi_varusteet", [kid], {"lahde": self.a.kierto.pk}),
            ("autot:lisaa_tehtava", [kid], {"otsikko": "x"}),
            ("autot:poista_tehtava", [kid, b.tehtava.pk], {}),
            ("autot:kuittaa", [b.tehtava.pk], {}),
            ("autot:aseta_paakuva", [b.kuva.pk], {}),
            ("autot:vaihda_kuvatyyppi", [b.kuva.pk], {"tyyppi": "sisa"}),
            ("autot:siirra_kuva", [b.kuva.pk, "alas"], {}),
            ("autot:poista_kuva", [b.kuva.pk], {}),
        ]
        for nimi, args, data in pyynnot:
            for otsakkeet in ({}, HTMX):
                with self.subTest(nimi=nimi, htmx=bool(otsakkeet)):
                    vastaus = self.client.post(reverse(nimi, args=args), data, **otsakkeet)
                    self.assertEqual(vastaus.status_code, 404)
        self.assert_b_ennallaan()

    def test_oman_kierron_kautta_toisen_liikkeen_aliriviin(self):
        """Oma kierto, mutta B:n kulun/renkaan/vaurion/tehtävän id: 404."""
        kid = self.a.kierto.pk
        for nimi, args in [
            ("autot:poista_kulu", [kid, self.b.kulu.pk]),
            ("autot:poista_rengas", [kid, self.b.rengas.pk]),
            ("autot:vaurio_korjattu", [kid, self.b.vaurio.pk]),
            ("autot:poista_tehtava", [kid, self.b.tehtava.pk]),
        ]:
            with self.subTest(nimi=nimi):
                self.assertEqual(self.client.post(reverse(nimi, args=args)).status_code, 404)
        self.assert_b_ennallaan()

    def test_varusteiden_kopiointi_toisen_liikkeen_autosta(self):
        vastaus = self.client.post(
            reverse("autot:kopioi_varusteet", args=[self.a.kierto.pk]), {"lahde": self.b.kierto.pk}
        )
        self.assertEqual(vastaus.status_code, 404)

    def test_toisen_liikkeen_varusteet_ohitetaan(self):
        self.client.post(
            reverse("autot:tallenna_varusteet", args=[self.a.kierto.pk]),
            {"varuste": [self.a.varuste.pk, self.b.varuste.pk]},
        )
        with liike_kaytossa(self.a.liike):
            self.assertEqual(
                list(AjoneuvonVaruste.objects.filter(ajoneuvo=self.a.ajoneuvo).values_list("varuste_id", flat=True)),
                [self.a.varuste.pk],
            )
        self.assert_b_ennallaan()

    def test_lomakkeet_eivat_hyvaksy_toisen_liikkeen_valintoja(self):
        kid = self.a.kierto.pk
        # Toimittaja ja asiakas B:ltä
        vastaus = self.client.post(
            reverse("autot:tallenna_kauppa", args=[kid]),
            {"toimittaja": self.b.yritys.pk, "asiakas": self.b.asiakas.pk, "alv_kasittely": "marginaali"},
            **HTMX,
        )
        self.assertEqual(vastaus.status_code, 422)
        # Tilasiirto myydyksi B:n asiakkaalle
        self.client.post(
            reverse("autot:vaihda_tila", args=[kid]),
            {"tila": "myyty", "asiakas": self.b.asiakas.pk, "myyntihinta": "15000"},
        )
        # Tehtävän vastuuhenkilö B:ltä
        vastaus = self.client.post(
            reverse("autot:lisaa_tehtava", args=[kid]), {"otsikko": "x", "vastuu": self.b.myyja.pk}, **HTMX
        )
        self.assertEqual(vastaus.status_code, 422)
        # Tehtäväpohja B:n käyttäjälle
        self.client.post(reverse("autot:tehtavapohjat"), {"tila": "ostettu", "otsikko": "y", "vastuu": self.b.myyja.pk})
        # Uusi auto B:n toimittajalta
        self.client.post(
            reverse("autot:uusi"),
            {"merkki": "Kia", "malli": "Ceed", "toimittaja": self.b.yritys.pk, "alv_kasittely": "marginaali"},
        )
        with liike_kaytossa(self.a.liike):
            k = Kierto.objects.get(pk=kid)
            self.assertIsNone(k.asiakas_id)
            self.assertEqual(k.tila, "myynnissa")
            self.assertEqual(k.toimittaja_id, self.a.yritys.pk)
            self.assertFalse(Tehtava.objects.filter(otsikko="x").exists())
            self.assertFalse(Tehtavapohja.objects.filter(otsikko="y").exists())
            self.assertFalse(Ajoneuvo.objects.filter(merkki="Kia").exists())
        self.assert_b_ennallaan()

    def test_hallinta_404(self):
        self.client.post(reverse("autot:yritykset"), {"id": self.b.yritys.pk, "nimi": "Kaapattu", "tyyppi": "muu"})
        self.client.post(
            reverse("autot:kayttajat"),
            {"id": self.b.myyja.pk, f"k{self.b.myyja.pk}-nimi": "X", f"k{self.b.myyja.pk}-rooli": "admin"},
        )
        self.client.post(reverse("autot:varusteet"), {"toiminto": "nakyvyys", "id": self.b.varuste.pk})
        self.client.post(
            reverse("autot:varusteet"),
            {"toiminto": "nimea", "id": self.b.varuste.pk, "nimi": "X", "kategoria": self.a.kategoria.pk},
        )
        self.client.post(
            reverse("autot:varusteet"), {"toiminto": "varuste", "kategoria": self.b.kategoria.pk, "nimet": "Vieras"}
        )
        self.client.post(reverse("autot:tehtavapohjat"), {"toiminto": "poista", "id": self.b.pohja.pk})
        for data in [
            {"id": self.b.yritys.pk, "nimi": "Kaapattu", "tyyppi": "muu"},
        ]:
            self.assertEqual(self.client.post(reverse("autot:yritykset"), data).status_code, 404)
        self.assertEqual(Varuste.kaikki.filter(nimi="Vieras").count(), 0)
        self.assert_b_ennallaan()

    def test_asetukset_muuttavat_vain_omaa_liiketta(self):
        self.client.post(reverse("autot:asetukset"), {"toiminto": "liike", "nimi": "Uusi nimi", "alv_prosentti": "24"})
        self.b.liike.refresh_from_db()
        self.a.liike.refresh_from_db()
        self.assertEqual(self.a.liike.nimi, "Uusi nimi")
        self.assertEqual(self.b.liike.nimi, "Liike B")

    def test_kuvan_lataus_tallentuu_omalle_liikkeelle(self):
        self.client.post(
            reverse("autot:lataa_kuvat", args=[self.a.kierto.pk]), {"tyyppi": "ulko", "kuvat": [kuvatiedosto()]}
        )
        with liike_kaytossa(self.a.liike):
            uusi = Kuva.objects.exclude(pk=self.a.kuva.pk).get()
        self.assertTrue(uusi.avain.startswith(f"liike_{self.a.liike.pk}/"))


class KirjautuminenTestit(Pohja):
    def test_kirjautumaton_ohjataan_kirjautumaan(self):
        self.client.logout()
        for url in [
            reverse("autot:etusivu"),
            reverse("autot:kortti", args=[self.a.kierto.pk]),
            reverse("autot:kuva", args=[self.a.kuva.pk]),
        ]:
            with self.subTest(url=url):
                vastaus = self.client.get(url)
                self.assertEqual(vastaus.status_code, 302)
                self.assertTrue(vastaus["Location"].startswith(reverse("kirjaudu")))

    def test_liike_vaihtuu_kayttajan_mukana(self):
        self.client.logout()
        self.assertTrue(self.client.login(username="admin@b.fi", password=SALASANA))
        self.assertEqual(self.client.get(reverse("autot:kortti", args=[self.b.kierto.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("autot:kortti", args=[self.a.kierto.pk])).status_code, 404)

    def test_liike_ei_jaa_voimaan_pyynnon_jalkeen(self):
        self.client.get(reverse("autot:etusivu"))
        self.assertIsNone(aktiivinen_liike_id())

    def test_passivoitu_kayttaja_ei_nae_mitaan(self):
        Kayttaja.objects.filter(pk=self.a.admin.pk).update(is_active=False)
        vastaus = self.client.get(reverse("autot:kortti", args=[self.a.kierto.pk]))
        self.assertEqual(vastaus.status_code, 302)
