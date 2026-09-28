"""Kuvien vakiopaikat, raahaa ja pudota -lataus ja kuvat uutta autoa lisättäessä."""

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from autot import palvelut
from autot.models import Kierto, Kuva
from liikkeet.rajaus import liike_kaytossa

from .apu import kuvatiedosto, luo_liike

HTMX = {"HTTP_HX_REQUEST": "true"}


class Pohja(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d = luo_liike("Testiliike", "t")

    def setUp(self):
        self.client.force_login(self.d.admin)
        self._liike = liike_kaytossa(self.d.liike)
        self._liike.__enter__()
        # Apudatan kuva ilman tiedostoa pois, jotta pääkuvasäännöt näkyvät selvästi
        Kuva.objects.filter(pk=self.d.kuva.pk).update(paakuva=False)

    def tearDown(self):
        self._liike.__exit__(None, None, None)

    def lataa(self, paikka="", tiedostot=None, **muut):
        data = {"paikka": paikka, "kuvat": tiedostot or [kuvatiedosto()], **muut}
        return self.client.post(reverse("autot:lataa_kuvat", args=[self.d.kierto.pk]), data, **HTMX)


class VakiopaikkaTestit(Pohja):
    def test_kuva_vakiopaikalle(self):
        vastaus = self.lataa("etu_vasen")
        self.assertContains(vastaus, "Kuva lisätty: Edestä vasemmalta.")
        kuva = Kuva.objects.get(paikka="etu_vasen")
        self.assertEqual((kuva.tyyppi, kuva.jarjestys), ("ulko", 0))
        self.assertTrue(kuva.paakuva)  # ensimmäinen etu_vasen-kuva pääkuvaksi

    def test_sisakuvan_tyyppi_paikasta(self):
        self.lataa("mittaristo", tyyppi="ulko")
        self.assertEqual(Kuva.objects.get(paikka="mittaristo").tyyppi, "sisa")
        self.assertFalse(Kuva.objects.get(paikka="mittaristo").paakuva)

    def test_paikan_kuvan_vaihto_sailyttaa_vanhan_muissa_kuvissa(self):
        self.lataa("takaa")
        vanha = Kuva.objects.get(paikka="takaa")
        self.lataa("takaa")
        vanha.refresh_from_db()
        self.assertEqual(vanha.paikka, "")
        self.assertEqual(Kuva.objects.filter(paikka="takaa").count(), 1)

    def test_vakiopaikalle_vain_yksi_kuva(self):
        self.lataa("edesta", tiedostot=[kuvatiedosto("a.jpg"), kuvatiedosto("b.jpg")])
        self.assertEqual(Kuva.objects.filter(kierto=self.d.kierto).exclude(pk=self.d.kuva.pk).count(), 1)

    def test_tietokanta_estaa_kaksi_kuvaa_samalla_paikalla(self):
        Kuva.objects.create(kierto=self.d.kierto, avain="a.jpg", paikka="takaa")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Kuva.objects.create(kierto=self.d.kierto, avain="b.jpg", paikka="takaa")

    def test_tuntematon_paikka_on_tavallinen_kuva(self):
        self.lataa("katto")
        kuva = Kuva.objects.exclude(pk=self.d.kuva.pk).get()
        self.assertEqual((kuva.paikka, kuva.tyyppi), ("", "ulko"))

    def test_valilehti_nayttaa_paikat_ja_ohjatun_kuvauksen(self):
        self.lataa("etu_vasen")
        vastaus = self.client.get(reverse("autot:valilehti", args=[self.d.kierto.pk, "kuvat"]), **HTMX)
        self.assertContains(vastaus, "Kuvaa vakiokuvat")
        self.assertContains(vastaus, 'data-paikka="taka_vasen"')
        self.assertContains(vastaus, 'capture="environment"')
        self.assertEqual(vastaus.context["vakiokuvia"], 1)
        self.assertEqual(len(vastaus.context["vakiopaikat"]), len(Kuva.VAKIOPAIKAT))

    def test_tyypin_vaihto_irrottaa_paikalta(self):
        self.lataa("etu_oikea")
        kuva = Kuva.objects.get(paikka="etu_oikea")
        self.client.post(reverse("autot:vaihda_kuvatyyppi", args=[kuva.pk]), {"tyyppi": "vaurio"})
        kuva.refresh_from_db()
        self.assertEqual((kuva.tyyppi, kuva.paikka), ("vaurio", ""))

    def test_useita_muita_kuvia_kerralla(self):
        vastaus = self.lataa(tiedostot=[kuvatiedosto("a.jpg"), kuvatiedosto("b.jpg"), kuvatiedosto("c.jpg")])
        self.assertContains(vastaus, "3 kuvaa lisätty.")
        self.assertEqual(Kuva.objects.filter(paikka="", tyyppi="ulko").exclude(pk=self.d.kuva.pk).count(), 3)


class UusiAutoKuvillaTestit(Pohja):
    def test_kuvat_tallentuvat_uudelle_autolle(self):
        self.client.post(
            reverse("autot:uusi"),
            {
                "merkki": "Kia",
                "malli": "Ceed",
                "kirjaus": "tarjous",
                "alv_kasittely": "marginaali",
                "kuvat": [kuvatiedosto("a.jpg"), kuvatiedosto("b.jpg")],
            },
        )
        k = Kierto.objects.get(ajoneuvo__merkki="Kia")
        self.assertEqual(k.kuvat.count(), 2)
        self.assertEqual(k.kuvat.filter(paakuva=True).count(), 1)

    def test_palvelu_palauttaa_virheelliset(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        lisatyt, virheelliset = palvelut.lisaa_kuvat(
            self.d.kierto, [SimpleUploadedFile("rikki.jpg", b"x"), kuvatiedosto()], self.d.admin
        )
        self.assertEqual((len(lisatyt), virheelliset), (1, ["rikki.jpg"]))
