"""Katelaskennan, rahamuunnosten ja tilasiirtojen yksikkötestit (ei tietokantaa)."""

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from autot import logiikka
from autot.logiikka import laske_kate

ALV = Decimal("25.5")


def kate(**kwargs):
    oletukset = dict(alv_kasittely="marginaali", kulut_veroton=0, alv_prosentti=ALV)
    oletukset.update(kwargs)
    return laske_kate(**oletukset)


class MarginaaliverotusTestit(SimpleTestCase):
    def test_perustapaus(self):
        # Osto 10 000 €, myynti 12 510 € -> marginaali 2 510 €, vero 2510 * 25,5 / 125,5 = 510 €
        k = kate(ostohinta=1_000_000, myyntihinta=1_251_000)
        self.assertEqual(k.marginaalivero, 51_000)
        self.assertEqual(k.nettomyynti, 1_200_000)
        self.assertEqual(k.verollinen_myynti, 1_251_000)
        self.assertEqual(k.kate, 200_000)

    def test_kulut_eivat_pienenna_veropohjaa_mutta_pienentavat_katetta(self):
        ilman = kate(ostohinta=1_000_000, myyntihinta=1_251_000)
        kuluilla = kate(ostohinta=1_000_000, myyntihinta=1_251_000, kulut_veroton=80_000)
        self.assertEqual(kuluilla.marginaalivero, ilman.marginaalivero)
        self.assertEqual(kuluilla.kate, ilman.kate - 80_000)
        self.assertEqual(kuluilla.hankintameno, 1_080_000)

    def test_tappiollisesta_kaupasta_ei_veroa(self):
        k = kate(ostohinta=1_500_000, myyntihinta=1_400_000, kulut_veroton=20_000)
        self.assertEqual(k.marginaalivero, 0)
        self.assertEqual(k.nettomyynti, 1_400_000)
        self.assertEqual(k.kate, -120_000)

    def test_nollamarginaali(self):
        k = kate(ostohinta=1_000_000, myyntihinta=1_000_000)
        self.assertEqual(k.marginaalivero, 0)
        self.assertEqual(k.kate, 0)

    def test_pyoristys_senttiin(self):
        # Marginaali 1,00 € -> vero 0,2031... € -> 20 senttiä
        self.assertEqual(kate(ostohinta=0, myyntihinta=100).marginaalivero, 20)
        # Marginaali 2,51 € -> vero tasan 0,51 €
        self.assertEqual(kate(ostohinta=0, myyntihinta=251).marginaalivero, 51)
        # Marginaali 10,04 € -> vero 2,0401... € -> 2,04 €
        self.assertEqual(kate(ostohinta=0, myyntihinta=1004).marginaalivero, 204)

    def test_puolikas_sentti_pyoristyy_ylospain(self):
        # Kannalla 100 % vero on puolet marginaalista: 1 c -> 0,5 c -> 1 c ja 5 c -> 2,5 c -> 3 c.
        # Pankkiirin pyöristys (Pythonin round) antaisi 0 ja 2.
        self.assertEqual(kate(ostohinta=0, myyntihinta=1, alv_prosentti=Decimal("100")).marginaalivero, 1)
        self.assertEqual(kate(ostohinta=0, myyntihinta=5, alv_prosentti=Decimal("100")).marginaalivero, 3)

    def test_jalkikulut(self):
        # Kulut 1 000 €, joista 300 € myynnin jälkeen
        k = kate(ostohinta=1_000_000, myyntihinta=1_251_000, kulut_veroton=100_000, jalkikulut=30_000)
        self.assertEqual(k.kate, 100_000)
        self.assertEqual(k.kate_myyntihetki, 130_000)
        self.assertEqual(k.kulut_ennen_myyntia, 70_000)

    def test_kateprosentti_nettomyynnista(self):
        k = kate(ostohinta=1_000_000, myyntihinta=1_251_000)
        self.assertEqual(k.kate_prosentti, Decimal("200000") * 100 / Decimal("1200000"))

    def test_eri_alv_kanta(self):
        # 24 %: marginaali 1 240 € -> vero 240 €
        k = kate(ostohinta=1_000_000, myyntihinta=1_124_000, alv_prosentti=Decimal("24"))
        self.assertEqual(k.marginaalivero, 24_000)
        self.assertEqual(k.kate, 100_000)

    def test_alv_prosentti_liukulukuna_tai_tekstina(self):
        a = kate(ostohinta=0, myyntihinta=125_500, alv_prosentti=25.5)
        b = kate(ostohinta=0, myyntihinta=125_500, alv_prosentti="25.5")
        self.assertEqual(a.marginaalivero, 25_500)
        self.assertEqual(b.marginaalivero, 25_500)


class NormaaliAlvTestit(SimpleTestCase):
    def test_kaikki_verottomina(self):
        k = kate(alv_kasittely="alv", ostohinta=2_000_000, myyntihinta=2_300_000, kulut_veroton=50_000)
        self.assertEqual(k.marginaalivero, 0)
        self.assertEqual(k.nettomyynti, 2_300_000)
        self.assertEqual(k.kate, 250_000)

    def test_verollinen_myynti(self):
        k = kate(alv_kasittely="alv", ostohinta=0, myyntihinta=2_000_000)
        self.assertEqual(k.verollinen_myynti, 2_510_000)

    def test_tappio(self):
        k = kate(alv_kasittely="alv", ostohinta=2_000_000, myyntihinta=1_900_000, kulut_veroton=10_000)
        self.assertEqual(k.kate, -110_000)

    def test_sama_hinta_eri_kasittely(self):
        """Marginaalissa myyntihinta on verollinen, ALV-kaupassa veroton: kate eroaa."""
        m = kate(ostohinta=1_000_000, myyntihinta=1_251_000)
        a = kate(alv_kasittely="alv", ostohinta=1_000_000, myyntihinta=1_251_000)
        self.assertEqual(m.kate, 200_000)
        self.assertEqual(a.kate, 251_000)


class KatePuuttuvillaTiedoilla(SimpleTestCase):
    def test_ilman_ostohintaa(self):
        self.assertIsNone(kate(ostohinta=None, myyntihinta=1_000_000))

    def test_ilman_myyntihintaa(self):
        self.assertIsNone(kate(ostohinta=1_000_000, myyntihinta=None))

    def test_tuntematon_kasittely(self):
        with self.assertRaises(ValueError):
            kate(alv_kasittely="jotain", ostohinta=1, myyntihinta=2)

    def test_arvio_lippu(self):
        self.assertTrue(kate(ostohinta=1, myyntihinta=2, arvio=True).arvio)
        self.assertFalse(kate(ostohinta=1, myyntihinta=2).arvio)


class RahaTestit(SimpleTestCase):
    def test_euro_senteiksi(self):
        tapaukset = {
            "12 500,50": 1_250_050,
            "12500.5": 1_250_050,
            "12500": 1_250_000,
            "1.250,50": 125_050,
            "12 500 €": 1_250_000,
            "0,005": 1,  # puoli senttiä ylöspäin
            "0,004": 0,
            "-10,10": -1010,
            "": None,
            "   ": None,
            None: None,
        }
        for syote, odotettu in tapaukset.items():
            with self.subTest(syote=syote):
                self.assertEqual(logiikka.euro_senteiksi(syote), odotettu)

    def test_euro_senteiksi_virheellinen(self):
        for syote in ["abc", "12,5,5", "NaN", "Infinity"]:
            with self.subTest(syote=syote), self.assertRaises(ValueError):
                logiikka.euro_senteiksi(syote)

    def test_ei_liukulukuvirheita(self):
        # float(0.29) * 100 = 28.999999999999996
        self.assertEqual(logiikka.euro_senteiksi("0,29"), 29)
        self.assertEqual(logiikka.euro_senteiksi("1,15"), 115)

    def test_euro_muotoilu(self):
        self.assertEqual(logiikka.euro(1_250_050), "12 501 €")
        self.assertEqual(logiikka.euro(1_250_050, desimaalit=True), "12 500,50 €")
        self.assertEqual(logiikka.euro(-1_250_049), "-12 500 €")
        self.assertEqual(logiikka.euro(5, desimaalit=True), "0,05 €")
        self.assertEqual(logiikka.euro(None), "–")

    def test_euro_input(self):
        self.assertEqual(logiikka.euro_input(1_250_000), "12500")
        self.assertEqual(logiikka.euro_input(1_250_050), "12500,50")
        self.assertEqual(logiikka.euro_input(5), "0,05")
        self.assertEqual(logiikka.euro_input(None), "")
        # Edestakaisin
        for sentit in [0, 1, 99, 100, 123_456, -250]:
            self.assertEqual(logiikka.euro_senteiksi(logiikka.euro_input(sentit)), sentit)

    def test_verottomaksi_ja_verolliseksi(self):
        self.assertEqual(logiikka.verottomaksi(12_550, Decimal("25.5")), 10_000)
        self.assertEqual(logiikka.verottomaksi(12_400, Decimal("25.5")), 9_880)
        self.assertEqual(logiikka.verolliseksi(10_000, Decimal("25.5")), 12_550)
        self.assertEqual(logiikka.verolliseksi(10_000, Decimal("0")), 10_000)


class TilaTestit(SimpleTestCase):
    def test_sallitut_siirrot(self):
        self.assertTrue(logiikka.siirto_sallittu("tarjottu", "ostettu"))
        self.assertTrue(logiikka.siirto_sallittu("myyty", "myynnissa"))
        self.assertFalse(logiikka.siirto_sallittu("tarjottu", "myyty"))
        self.assertFalse(logiikka.siirto_sallittu("toimitettu", "tarjottu"))

    def test_jokainen_siirto_osoittaa_tunnettuun_tilaan(self):
        for vanha, uudet in logiikka.SIIRROT.items():
            self.assertIn(vanha, logiikka.TILA_NIMI)
            for uusi in uudet:
                self.assertIn(uusi, logiikka.TILA_NIMI)

    def test_taaksepain(self):
        self.assertTrue(logiikka.on_taaksepain("myyty", "myynnissa"))
        self.assertFalse(logiikka.on_taaksepain("myynnissa", "myyty"))
        self.assertFalse(logiikka.on_taaksepain("tarjottu", "hylatty"))
        self.assertFalse(logiikka.on_taaksepain("hylatty", "tarjottu"))

    def test_jalkikulu(self):
        myyty = date(2026, 5, 10)
        self.assertTrue(logiikka.on_jalkikulu(date(2026, 5, 11), myyty))
        self.assertFalse(logiikka.on_jalkikulu(date(2026, 5, 10), myyty))
        self.assertFalse(logiikka.on_jalkikulu(date(2026, 5, 11), None))


class RekisteriTestit(SimpleTestCase):
    def test_normalisointi(self):
        for syote in ["abc123", "ABC 123", "abc-123", " Abc-123 "]:
            with self.subTest(syote=syote):
                self.assertEqual(logiikka.normalisoi_rekisteri(syote), "ABC-123")
        self.assertEqual(logiikka.normalisoi_rekisteri("äö-1"), "ÄÖ-1")
        self.assertEqual(logiikka.normalisoi_rekisteri("CD-1234"), "CD-1234")  # ei tunnettu muoto
        self.assertEqual(logiikka.normalisoi_rekisteri(None), "")

    def test_hakuavain(self):
        self.assertEqual(logiikka.rekisteri_hakuavain("abc-123"), logiikka.rekisteri_hakuavain("ABC 123"))
