"""Myyntitarjoukset (tarjous -> myyntisopimus) ja sopimuksista syntyvät laskut."""

from django.urls import reverse
from django.utils import timezone

from autot import sopimukset
from autot.models import Kierto, Lasku, Myyntitarjous, Sopimus

from .test_sopimukset import Pohja, lomakedata


def tarjousdata(**muut):
    data = {"vp_nimi": "Liisa Asiakas", "vp_puhelin": "050 1", "pvm": "2026-09-01", "hinta": "15 000"}
    data.update(muut)
    return data


class TarjousPohja(Pohja):
    def setUp(self):
        super().setUp()
        # Apudatan tarjous ja lasku pois, jotta numerointi ja määrät näkyvät selvästi
        Lasku.objects.all().delete()
        Myyntitarjous.objects.all().delete()


class TarjousTestit(TarjousPohja):
    def test_tarjous_tallentuu_auton_taakse(self):
        golf = self.varastoauto(pyyntihinta=1_550_000)
        lomake = self.client.get(reverse("autot:uusi_tarjous", args=[golf.pk]))
        self.assertContains(lomake, 'value="15500"')  # pyyntihinta oletukseksi
        vastaus = self.client.post(
            reverse("autot:uusi_tarjous", args=[golf.pk]),
            tarjousdata(
                vaihto_rekisterinumero="fab456",
                vaihto_merkki="Skoda",
                vaihto_malli="Octavia",
                vaihto_hinta="10 000",
                vaihto_jaannosvelka="8 000",
            ),
        )
        t = Myyntitarjous.objects.get()
        self.assertRedirects(vastaus, reverse("autot:tarjous", args=[t.pk]))
        self.assertEqual((t.kierto, t.numero, t.tila, t.laatija), (golf, 1, "avoin", self.d.admin))
        self.assertEqual((t.vaihto_rekisterinumero, t.summat().maksettava), ("FAB-456", 1_300_000))

        tuloste = self.client.get(reverse("autot:tarjous", args=[t.pk]))
        self.assertContains(tuloste, "TARJOUS")
        self.assertContains(tuloste, "Skoda Octavia")
        self.assertContains(tuloste, "13\xa0000,00\xa0€")
        self.assertContains(tuloste, "Voittomarginaalijärjestely")
        self.assertContains(tuloste, f"{reverse('autot:myyntisopimus', args=[golf.pk])}?tarjous={t.pk}")

        valilehti = self.client.get(reverse("autot:valilehti", args=[golf.pk, "tarjoukset"]), HTTP_HX_REQUEST="true")
        self.assertContains(valilehti, "Liisa Asiakas")
        self.assertEqual(valilehti.context["laskurit"]["tarjoukset"], 1)

    def test_asiakas_rekisterista_ja_numerot_juoksevat(self):
        golf = self.varastoauto()
        for _ in range(2):
            self.client.post(
                reverse("autot:uusi_tarjous", args=[golf.pk]), tarjousdata(vp_nimi="", asiakas=self.d.asiakas.pk)
            )
        self.assertEqual(
            list(Myyntitarjous.objects.order_by("numero").values_list("numero", "vp_nimi")),
            [
                (1, "Testiliike Asiakas Oy"),
                (2, "Testiliike Asiakas Oy"),
            ],
        )

    def test_virheelliset_tiedot(self):
        golf = self.varastoauto()
        vastaus = self.client.post(
            reverse("autot:uusi_tarjous", args=[golf.pk]), tarjousdata(vp_nimi="", vaihto_merkki="Skoda")
        )
        self.assertEqual(vastaus.status_code, 422)
        self.assertIn("vp_nimi", vastaus.context["lomake"].errors)
        self.assertIn("vaihto_hinta", vastaus.context["lomake"].errors)
        self.assertFalse(Myyntitarjous.objects.exists())

    def test_tarjousta_ei_voi_tehda_tarjotusta_autosta(self):
        auto = self.tarjous()
        vastaus = self.client.post(reverse("autot:uusi_tarjous", args=[auto.pk]), tarjousdata())
        self.assertRedirects(vastaus, reverse("autot:kortti", args=[auto.pk]) + "?v=tarjoukset")
        self.assertFalse(Myyntitarjous.objects.exists())

    def test_hylkays(self):
        golf = self.varastoauto()
        t = sopimukset.tee_myyntitarjous(golf, self.d.admin, {"vp_nimi": "X", "hinta": 1})
        self.client.post(reverse("autot:hylkaa_tarjous", args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.tila, "hylatty")

    def test_tarjouksesta_myyntisopimus(self):
        golf = self.varastoauto(rek="GOL-123")
        t = sopimukset.tee_myyntitarjous(
            golf,
            self.d.admin,
            {
                "vp_nimi": "Liisa Asiakas",
                "vp_puhelin": "050 1",
                "hinta": 1_500_000,
                "toimistokulut": 19_000,
                "vaihto_rekisterinumero": "FAB-456",
                "vaihto_merkki": "Skoda",
                "vaihto_malli": "Octavia",
                "vaihto_hinta": 1_000_000,
                "vaihto_jaannosvelka": 800_000,
            },
        )
        toinen = sopimukset.tee_myyntitarjous(golf, self.d.admin, {"vp_nimi": "Toinen", "hinta": 1_400_000})
        url = reverse("autot:myyntisopimus", args=[golf.pk])

        # Lomake esitäytetään tarjoukselta
        lomake = self.client.get(f"{url}?tarjous={t.pk}")
        self.assertEqual(lomake.context["lomake"]["vp_nimi"].value(), "Liisa Asiakas")
        self.assertEqual(lomake.context["kohde"]["hinta"].value(), "15000")
        self.assertEqual(lomake.context["vaihdot"].forms[0]["merkki"].value(), "Skoda")
        self.assertContains(lomake, 'name="tarjous"')

        vastaus = self.client.post(
            url,
            lomakedata(
                **{
                    "tarjous": t.pk,
                    "s-vp_nimi": "Liisa Asiakas",
                    "s-toimistokulut": "190",
                    "kohde-hinta": "15 000",
                    "vaihto-TOTAL_FORMS": "1",
                    "vaihto-0-rekisterinumero": "FAB-456",
                    "vaihto-0-merkki": "Skoda",
                    "vaihto-0-malli": "Octavia",
                    "vaihto-0-hinta": "10 000",
                    "vaihto-0-jaannosvelka": "8 000",
                    "vaihto-0-jaannosvelan_haltija": "Rahoitus Oy",
                    "vaihto-0-alv_kasittely": "marginaali",
                }
            ),
        )
        s = Sopimus.objects.get(tyyppi="myynti")
        self.assertRedirects(vastaus, reverse("autot:sopimus", args=[s.pk]))
        t.refresh_from_db()
        toinen.refresh_from_db()
        self.assertEqual((t.tila, t.sopimus), ("hyvaksytty", s))
        self.assertEqual(toinen.tila, "hylatty")

        # Laskut: asiakas maksaa 15 190 - 10 000 + 8 000 = 13 190 €, vaihtoauto hyvitetty, velka rahoittajalle
        laskut = {(lk.suunta, lk.laji): lk for lk in s.laskut.all()}
        self.assertEqual(set(laskut), {("myynti", "toimitus"), ("myynti", "vaihtoauto"), ("osto", "jaannosvelka")})
        self.assertEqual(laskut["myynti", "toimitus"].summa, 1_319_000)
        self.assertEqual(laskut["myynti", "toimitus"].osapuoli_nimi, "Liisa Asiakas")
        self.assertTrue(laskut["myynti", "vaihtoauto"].maksettu)
        velka = laskut["osto", "jaannosvelka"]
        self.assertEqual((velka.summa, velka.osapuoli_nimi, velka.maksettu), (800_000, "Rahoitus Oy", False))

        yhteenveto = self.client.get(reverse("autot:sopimuksen_laskut", args=[s.pk]))
        self.assertContains(yhteenveto, "Asiakkaalle jää vaihtoautosta hyväksi 2\xa0000,00\xa0€")
        self.assertContains(yhteenveto, "voittomarginaalijärjestelmässä")

    def test_suljettua_tarjousta_ei_voi_kayttaa(self):
        golf = self.varastoauto()
        t = sopimukset.tee_myyntitarjous(golf, self.d.admin, {"vp_nimi": "X", "hinta": 1})
        t.tila = "hylatty"
        t.save()
        url = reverse("autot:myyntisopimus", args=[golf.pk])
        self.assertEqual(self.client.get(f"{url}?tarjous={t.pk}").status_code, 404)


class LaskuTestit(TarjousPohja):
    def myy(self, **tiedot):
        golf = self.varastoauto(rek="GOL-123")
        return sopimukset.tee_myyntisopimus(
            golf,
            self.d.admin,
            yritys=self.d.asiakas,
            tiedot={"maksutapa": "rahoitus", "rahoitusyhtio": "Rahoitus Oy", **tiedot},
            kohde={"hinta": 2_000_000},
            vaihdot=[{"rekisterinumero": "COR-321", "merkki": "Toyota", "malli": "Corolla", "hinta": 300_000}],
            alv_prosentti=self.d.liike.alv_prosentti,
        )

    def test_myyntisopimuksen_laskut(self):
        self.d.liike.tilinumero = "FI00 1234 5600 0007 85"
        self.d.liike.save()
        s = self.myy(etumaksu=100_000, rahoitettava=1_200_000, toimitusaika=timezone.localdate())
        laskut = list(s.laskut.order_by("suunta", "numero"))
        self.assertEqual(
            [(lk.laji, lk.summa) for lk in laskut],
            [("etumaksu", 100_000), ("rahoitus", 1_200_000), ("toimitus", 400_000), ("vaihtoauto", 300_000)],
        )
        self.assertEqual([lk.numero for lk in laskut], [1, 2, 3, 4])
        rahoitus = laskut[1]
        self.assertEqual((rahoitus.osapuoli_nimi, rahoitus.tilinumero), ("Rahoitus Oy", "FI00 1234 5600 0007 85"))
        self.assertEqual(laskut[0].erapaiva, s.pvm)
        self.assertEqual(laskut[2].erapaiva, s.toimitusaika)
        self.assertEqual(laskut[1].erapaiva, s.pvm + timezone.timedelta(days=self.d.liike.maksuaika_pv))
        self.assertTrue(all(lk.viitenumero for lk in laskut))

        tuloste = self.client.get(reverse("autot:lasku", args=[laskut[0].pk]))
        self.assertContains(tuloste, "LASKU")
        self.assertContains(tuloste, "Voittomarginaalijärjestely – käytetyt tavarat")
        self.assertContains(tuloste, laskut[0].viitenumero)
        self.assertContains(tuloste, "1\xa0000,00\xa0€")

    def test_luonti_ei_tuplaa(self):
        s = self.myy()
        maara = s.laskut.count()
        self.assertEqual(len(sopimukset.luo_laskut(s)), maara)
        self.client.post(reverse("autot:luo_laskut", args=[s.pk]))
        self.assertEqual(s.laskut.count(), maara)

    def test_vanhalle_sopimukselle_laskut_napista(self):
        # Ennen automaattista laskutusta tehty sopimus: laskut luodaan napista
        s = self.myy()
        s.laskut.all().delete()
        self.client.post(reverse("autot:luo_laskut", args=[s.pk]))
        self.assertEqual(s.laskut.count(), 2)

    def test_ostosopimuksen_laskut(self):
        auto = self.tarjous()
        s = sopimukset.tee_ostosopimus(
            auto,
            self.d.admin,
            yritys=None,
            tiedot={"vp_nimi": "Myyjä Mikko", "vp_tilinumero": "FI11"},
            kohde={"hinta": 2_000_000, "jaannosvelka": 1_747_460, "jaannosvelan_haltija": "Pankki Oy"},
            alv_prosentti=self.d.liike.alv_prosentti,
        )
        laskut = {lk.laji: lk for lk in s.laskut.all()}
        self.assertEqual(laskut["ostohinta"].summa, 252_540)
        self.assertEqual(laskut["ostohinta"].tilinumero, "FI11")
        self.assertEqual(laskut["jaannosvelka"].osapuoli_nimi, "Pankki Oy")
        self.assertEqual({lk.suunta for lk in laskut.values()}, {"osto"})

    def test_lista_ja_maksun_kirjaus(self):
        s = self.myy()
        toimitus = s.laskut.get(laji="toimitus")
        lista = self.client.get(reverse("autot:laskut"))
        self.assertContains(lista, "Maksu toimitettaessa")
        self.assertNotContains(lista, "Maksettu vaihtoajoneuvolla")  # oletuksena vain avoimet
        self.client.post(reverse("autot:lasku_maksettu", args=[toimitus.pk]), {"takaisin": reverse("autot:laskut")})
        toimitus.refresh_from_db()
        self.assertEqual(toimitus.maksettu_pvm, timezone.localdate())
        self.assertNotContains(self.client.get(reverse("autot:laskut")), "Maksu toimitettaessa")
        self.assertContains(self.client.get(reverse("autot:laskut") + "?tila=maksetut"), "Maksu toimitettaessa")
        self.client.post(reverse("autot:lasku_maksettu", args=[toimitus.pk]))
        toimitus.refresh_from_db()
        self.assertIsNone(toimitus.maksettu_pvm)

    def test_laskun_poisto_estetty_sopimuksen_kautta(self):
        s = self.myy()
        self.assertTrue(Lasku.objects.filter(sopimus=s).exists())
        self.assertEqual(Kierto.objects.get(ajoneuvo__rekisterinumero="GOL-123").tila, "myyty")
