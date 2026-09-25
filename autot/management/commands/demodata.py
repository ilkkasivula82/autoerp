"""Demoaineisto kokeilua varten.

    python manage.py demodata                 # luo liikkeen "Demo Autot Oy"
    python manage.py demodata --korvaa        # poistaa ensin saman nimisen liikkeen kaikkine tietoineen
    python manage.py demodata --nimi "Toinen Oy" --sahkopostipaate toinen.fi

Käyttäjät (salasana --salasana, oletus "demo1234"):
    admin@<pääte>, osto@<pääte>, myynti@<pääte>, piha@<pääte>
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autot.models import (
    Ajoneuvo,
    AjoneuvonVaruste,
    Kierto,
    Kulu,
    Kuntoraportti,
    Rengassarja,
    Tehtava,
    Tehtavapohja,
    Tilahistoria,
    Varuste,
    Vaurio,
    Yritys,
)
from autot.perusdata import alusta_liike
from liikkeet.models import Kayttaja, Liike
from liikkeet.rajaus import liike_kaytossa


class Command(BaseCommand):
    help = "Luo demoliikkeen käyttäjineen, yrityksineen ja autoineen."

    def add_arguments(self, parser):
        parser.add_argument("--nimi", default="Demo Autot Oy", help="Liikkeen nimi")
        parser.add_argument("--sahkopostipaate", default="demo.fi", help="Käyttäjien sähköpostien verkkotunnus")
        parser.add_argument("--salasana", default="demo1234", help="Demokäyttäjien salasana")
        parser.add_argument("--korvaa", action="store_true", help="Poista ensin saman niminen liike tietoineen")

    @transaction.atomic
    def handle(self, *args, nimi, sahkopostipaate, salasana, korvaa, **kwargs):
        olemassa = Liike.objects.filter(nimi=nimi)
        if olemassa.exists():
            if not korvaa:
                raise CommandError(f'Liike "{nimi}" on jo olemassa. Käytä --korvaa, jos haluat luoda sen uudelleen.')
            for liike in olemassa:
                self._poista_liike(liike)

        liike = Liike.objects.create(nimi=nimi)
        alusta_liike(liike)
        with liike_kaytossa(liike):
            kayttajat = self._kayttajat(liike, sahkopostipaate, salasana)
            self._autot(kayttajat)
        self.stdout.write(
            self.style.SUCCESS(f'Demoliike "{nimi}" luotu. Kirjaudu: admin@{sahkopostipaate} / {salasana}')
        )

    def _poista_liike(self, liike):
        # Suojatut viittaukset (PROTECT) poistetaan oikeassa järjestyksessä.
        with liike_kaytossa(liike):
            Kierto.objects.all().delete()
            Ajoneuvo.objects.all().delete()
            Yritys.objects.all().delete()
            AjoneuvonVaruste.objects.all().delete()
            Varuste.objects.all().delete()
        liike.delete()

    def _kayttajat(self, liike, paate, salasana):
        tiedot = [
            ("admin", "Aino Ylläpitäjä", "admin"),
            ("osto", "Olli Ostaja", "osto"),
            ("myynti", "Maija Myyjä", "myynti"),
            ("piha", "Pekka Piha", "kunnostus"),
            ("talous", "Tiina Talous", "talous"),
        ]
        tulos = {}
        for tunnus, nimi, rooli in tiedot:
            sahkoposti = f"{tunnus}@{paate}"
            if Kayttaja.objects.filter(sahkoposti__iexact=sahkoposti).exists():
                raise CommandError(f"Sähköposti {sahkoposti} on jo käytössä. Valitse toinen --sahkopostipaate.")
            tulos[rooli] = Kayttaja.objects.create_user(sahkoposti, salasana, liike=liike, nimi=nimi, rooli=rooli)
        return tulos

    def _autot(self, kayttajat):
        admin, ostaja = kayttajat["admin"], kayttajat["osto"]
        tanaan = timezone.localdate()
        nyt = timezone.now()

        def d(n):
            return tanaan - timedelta(days=n)

        y = {}
        for nimi, tyyppi in [
            ("Esimerkki Rahoitus Oy", "rahoitusyhtio"),
            ("Huutokauppa Esimerkki", "huutokauppa"),
            ("Autotalo Mallinen Oy", "autoliike"),
            ("Vaihtoauto Testilä Oy", "autoliike"),
            ("Autokeskus Demo Oy", "autoliike"),
        ]:
            y[nimi] = Yritys.objects.create(nimi=nimi, tyyppi=tyyppi)

        def ajoneuvo(rek, vin, merkki, malli, tarkenne, vm, kv, vt, kori):
            return Ajoneuvo.objects.create(
                rekisterinumero=rek,
                vin=vin,
                merkki=merkki,
                malli=malli,
                mallitarkenne=tarkenne,
                vuosimalli=vm,
                kayttovoima=kv,
                vaihteisto=vt,
                korimalli=kori,
            )

        def kierros(
            a,
            km,
            tila,
            toimittaja,
            kanava,
            osto,
            ostopv,
            pyynti=None,
            asiakas=None,
            myynti=None,
            myyntipv=None,
            maksettu=False,
            alv="marginaali",
            tarjottu=None,
        ):
            tarjottu_pv = (ostopv or 0) + 2
            muutos_pv = myyntipv if myyntipv is not None else (ostopv if ostopv is not None else 1)
            k = Kierto.objects.create(
                ajoneuvo=a,
                km=km,
                tila=tila,
                toimittaja=y[toimittaja],
                ostokanava=kanava,
                tarjottu_hinta=tarjottu,
                tarjottu_pvm=d(tarjottu_pv),
                ostohinta=osto,
                ostopvm=d(ostopv) if ostopv is not None else None,
                alv_kasittely=alv,
                pyyntihinta=pyynti,
                asiakas=y[asiakas] if asiakas else None,
                myyntihinta=myynti,
                myyntipvm=d(myyntipv) if myyntipv is not None else None,
                maksettu_pvm=d(max((myyntipv or 0) - 5, 0)) if maksettu else None,
                tila_muutettu=nyt - timedelta(days=muutos_pv),
                luonut=admin,
            )
            Tilahistoria.objects.create(
                kierto=k, vanha_tila="", uusi_tila="tarjottu", kayttaja=ostaja, aika=nyt - timedelta(days=tarjottu_pv)
            )
            if tila != "tarjottu":
                Tilahistoria.objects.create(
                    kierto=k,
                    vanha_tila="tarjottu",
                    uusi_tila=tila,
                    kayttaja=ostaja,
                    aika=nyt - timedelta(days=muutos_pv),
                )
            return k

        def kulu(k, tyyppi, summa, pv, kuvaus=""):
            Kulu.objects.create(kierto=k, tyyppi=tyyppi, summa_veroton=summa, pvm=d(pv), kuvaus=kuvaus, luonut=admin)

        a1 = ajoneuvo("ABC-123", "WVWZZZAUZKW000001", "Volkswagen", "Golf", "1.5 TSI Style", 2019, "01", "4", "AB")
        k1 = kierros(a1, 98000, "myynnissa", "Esimerkki Rahoitus Oy", "rahoitusyhtio", 1290000, 24, pyynti=1490000)
        kulu(k1, "kuljetus", 18000, 22)
        kulu(k1, "pesu", 9000, 20)
        kulu(k1, "huolto", 42000, 19, "Määräaikaishuolto")
        Rengassarja.objects.create(
            kierto=k1, tyyppi="kesa", koko="205/55R16", vanteet="alumiini", urasyvyys_mm="5.5", kunto=4, sijainti="alla"
        )
        Rengassarja.objects.create(
            kierto=k1, tyyppi="nasta", koko="205/55R16", vanteet="pelti", urasyvyys_mm="3.5", kunto=3, sijainti="mukana"
        )
        Kuntoraportti.objects.create(
            kierto=k1,
            vaihe="tarjous",
            tuulilasi="ehja",
            avaimet=2,
            maalipinta=4,
            yleiskunto=4,
            sisatilat=4,
            huoltokirja="taysi",
            tehnyt=ostaja,
        )
        Kuntoraportti.objects.create(
            kierto=k1,
            vaihe="saapuminen",
            tuulilasi="kiveniskuja",
            avaimet=2,
            maalipinta=3,
            yleiskunto=4,
            sisatilat=4,
            huoltokirja="taysi",
            tehnyt=kayttajat["kunnostus"],
        )
        Vaurio.objects.create(kierto=k1, kohta="Takapuskuri", kuvaus="Naarmu 10 cm", arvioitu_korjaus=25000)

        a2 = ajoneuvo("XYZ-987", "YV1ZWA8UDL1000002", "Volvo", "XC60", "T8 Inscription", 2020, "PHB", "2", "SUV")
        k2 = kierros(a2, 124000, "kunnostuksessa", "Huutokauppa Esimerkki", "huutokauppa", 2750000, 9, pyynti=3190000)
        kulu(k2, "huutokauppamaksu", 35000, 9)
        kulu(k2, "kuljetus", 22000, 7)

        a3 = ajoneuvo("KLM-456", "WBA8E1100JA000003", "BMW", "320d", "xDrive Touring", 2018, "02", "2", "AC")
        kierros(a3, 156000, "tulossa", "Autotalo Mallinen Oy", "autoliike", 1680000, 2, pyynti=1950000)

        a4 = ajoneuvo("TRE-321", "JTDKBRFU0K3000004", "Toyota", "RAV4", "2.5 Hybrid AWD", 2019, "HB", "3", "SUV")
        kierros(a4, 87000, "tarjottu", "Esimerkki Rahoitus Oy", "rahoitusyhtio", None, None, tarjottu=2450000)
        a5 = ajoneuvo("SKO-555", "TMBJJ7NE5L0000005", "Skoda", "Octavia", "2.0 TDI Combi", 2020, "02", "4", "AC")
        kierros(a5, 143000, "tarjottu", "Huutokauppa Esimerkki", "huutokauppa", None, None, tarjottu=1390000)

        a6 = ajoneuvo("MER-777", "WDD2130041A000006", "Mercedes-Benz", "E 220 d", "4Matic", 2019, "02", "2", "AA")
        k6 = kierros(
            a6,
            112000,
            "myyty",
            "Esimerkki Rahoitus Oy",
            "rahoitusyhtio",
            2390000,
            48,
            pyynti=2790000,
            asiakas="Vaihtoauto Testilä Oy",
            myynti=2690000,
            myyntipv=12,
        )
        kulu(k6, "kuljetus", 20000, 46)
        kulu(k6, "kunnostus", 65000, 40, "Jarrulevyt ja palat edessä")
        kulu(k6, "reklamaatio", 38000, 3, "Ilmastoinnin kompressori vikaantui, puolet kuluista meille")

        # Palaava auto: myyty yli vuosi sitten, nyt uudelleen meillä
        a7 = ajoneuvo("AUD-202", "WAUZZZF40LA000007", "Audi", "A4", "40 TDI quattro Avant", 2020, "02", "4", "AC")
        vanha = kierros(
            a7,
            61000,
            "toimitettu",
            "Autotalo Mallinen Oy",
            "autoliike",
            2980000,
            420,
            asiakas="Autokeskus Demo Oy",
            myynti=3250000,
            myyntipv=395,
            maksettu=True,
        )
        kulu(vanha, "kuljetus", 20000, 418)
        kierros(a7, 118000, "myynnissa", "Esimerkki Rahoitus Oy", "rahoitusyhtio", 2090000, 15, pyynti=2390000)
        for nimi in [
            "Neliveto",
            "Vetokoukku",
            "LED-ajovalot",
            "Navigaattori",
            "Istuinlämmitys edessä",
            "Peruutuskamera",
        ]:
            AjoneuvonVaruste.objects.create(ajoneuvo=a7, varuste=Varuste.objects.get(nimi=nimi))

        a8 = ajoneuvo("PEU-808", "VF3MCYHZRKS000008", "Peugeot", "3008", "1.2 PureTech Allure", 2019, "01", "2", "SUV")
        k8 = kierros(
            a8,
            76000,
            "toimitettu",
            "Huutokauppa Esimerkki",
            "huutokauppa",
            1450000,
            70,
            asiakas="Autotalo Mallinen Oy",
            myynti=1690000,
            myyntipv=41,
            maksettu=True,
        )
        kulu(k8, "huutokauppamaksu", 25000, 70)

        a9 = ajoneuvo("TES-100", "5YJ3E7EB0LF000009", "Tesla", "Model 3", "Long Range AWD", 2020, "04", "2", "AA")
        k9 = kierros(
            a9,
            89000,
            "myyty",
            "Esimerkki Rahoitus Oy",
            "rahoitusyhtio",
            2150000,
            30,
            asiakas="Autokeskus Demo Oy",
            myynti=2450000,
            myyntipv=6,
            alv="alv",
        )
        kulu(k9, "pesu", 12000, 25)

        # Vaiheiden tehtävät avoimille autoille (normaalisti syntyvät tilasiirrossa)
        for k in Kierto.objects.exclude(tila__in=["toimitettu", "hylatty"]):
            for p in Tehtavapohja.objects.filter(tila=k.tila):
                ep = tanaan + timedelta(days=p.erapaiva_pv - 2) if p.erapaiva_pv is not None else None
                Tehtava.objects.create(
                    kierto=k, tila_vaihe=k.tila, otsikko=p.otsikko, rooli=p.rooli, erapaiva=ep, luonut=admin
                )
