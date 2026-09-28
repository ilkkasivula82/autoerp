"""Uuden liikkeen perusdata: koodistot, varustekatalogi ja tehtäväpohjat.

Koodit on valittu vastaamaan Traficomin avoimen datan koodeja siltä osin kuin
mahdollista. Ne kannattaa tarkistaa Traficomin muuttujaluettelosta ennen
rekisterihaun kytkemistä (osa koodeista, esim. hybridit, on omia).
"""

from django.db import transaction

from liikkeet.rajaus import liike_kaytossa

from .models import Koodi, Tehtavapohja, Varuste, Varustekategoria

KOODIT = {
    "kayttovoima": [
        ("01", "Bensiini"),
        ("02", "Diesel"),
        ("04", "Sähkö"),
        ("HB", "Hybridi (bensiini)"),
        ("HD", "Hybridi (diesel)"),
        ("PHB", "Ladattava hybridi (bensiini)"),
        ("PHD", "Ladattava hybridi (diesel)"),
        ("06", "Kaasu (CNG/LPG)"),
        ("E85", "Etanoli / Flex"),
    ],
    "vaihteisto": [("1", "Manuaali"), ("2", "Automaatti"), ("3", "Portaaton (CVT)"), ("4", "Puoliautomaatti / DSG")],
    "korimalli": [
        ("AA", "Sedan"),
        ("AB", "Viistoperä"),
        ("AC", "Farmari"),
        ("AD", "Coupé"),
        ("AE", "Avoauto"),
        ("AF", "Tila-auto / monikäyttö"),
        ("SUV", "Maastoauto / SUV"),
        ("PA", "Pakettiauto"),
        ("LAVA", "Avolava"),
    ],
}

VARUSTEET = {
    "Turvallisuus": [
        "Mukautuva vakionopeudensäädin",
        "Kaistavahti",
        "Kuolleen kulman varoitin",
        "Hätäjarrutusavustin",
        "Liikennemerkkien tunnistus",
        "Väsymysvaroitin",
        "ISOFIX-kiinnikkeet",
    ],
    "Pysäköinti": [
        "Pysäköintitutka edessä",
        "Pysäköintitutka takana",
        "Peruutuskamera",
        "360° kamera",
        "Pysäköintiavustin",
    ],
    "Mukavuus": [
        "Ilmastointi",
        "Automaattinen ilmastointi",
        "2-alueinen ilmastointi",
        "Istuinlämmitys edessä",
        "Istuinlämmitys takana",
        "Ohjauspyörän lämmitys",
        "Tuulilasin lämmitys",
        "Sähkösäätöiset etuistuimet",
        "Muistipenkit",
        "Nahkaverhoilu",
        "Avaimeton käynnistys",
        "Avaimeton lukitus",
        "Sähkötoiminen takaluukku",
        "Panoraamakatto",
        "Kattoluukku",
    ],
    "Lämmitys": [
        "Webasto / polttoainekäyttöinen lisälämmitin",
        "Moottorinlämmitin",
        "Sisähaaran pistoke",
        "Etäkäynnistys sovelluksella",
    ],
    "Multimedia": [
        "Navigaattori",
        "Apple CarPlay",
        "Android Auto",
        "Bluetooth",
        "Premium-äänentoisto",
        "Digitaalinen mittaristo",
        "Tuulilasinäyttö (HUD)",
        "Langaton lataus",
    ],
    "Valot": ["LED-ajovalot", "Matriisi-LED-valot", "Xenon-ajovalot", "Lisävalot", "Kaarrevalot"],
    "Muut": [
        "Vetokoukku",
        "Sähköinen vetokoukku",
        "Kattokaiteet",
        "Neliveto",
        "Ilmajousitus",
        "Talvirenkaat vanteilla",
        "Huoltokirja",
        "Sähköinen huoltokirja",
        "Tummennetut takalasit",
    ],
}

TEHTAVAPOHJAT = [
    # (tila, otsikko, rooli, eräpäivä pv)
    ("tarjottu", "Arvioi hinta ja tee ostopäätös", "osto", 1),
    ("tarjottu", "Pyydä kuvat ja huoltohistoria myyjältä", "osto", 1),
    ("ostettu", "Maksa ostolasku", "talous", 3),
    ("ostettu", "Tilaa kuljetus", "osto", 2),
    ("tulossa", "Varmista paperit ja avaimet", "osto", None),
    ("tulossa", "Tee saapumistarkastus ja kuntoraportti", "kunnostus", None),
    ("kunnostuksessa", "Pesu ja preppaus", "kunnostus", 3),
    ("kunnostuksessa", "Tarkista huoltotarve", "kunnostus", 2),
    ("myynnissa", "Ota myyntikuvat", "myynti", 1),
    ("myynnissa", "Aseta pyyntihinta", "myynti", 1),
    ("myyty", "Laadi kauppakirja ja lasku", "talous", 1),
    ("myyty", "Tee omistajanvaihdos", "myynti", 2),
    ("toimitettu", "Varmista maksu saapunut", "talous", 7),
]


@transaction.atomic
def alusta_liike(liike):
    """Luo liikkeelle koodistot, varustekatalogin ja tehtäväpohjat, jos niitä ei vielä ole."""
    with liike_kaytossa(liike):
        if not Koodi.objects.exists():
            for ryhma, rivit in KOODIT.items():
                for i, (koodi, nimi) in enumerate(rivit):
                    Koodi.objects.create(ryhma=ryhma, koodi=koodi, nimi=nimi, jarjestys=i)
        if not Varustekategoria.objects.exists():
            for i, (kategoria, nimet) in enumerate(VARUSTEET.items()):
                kat = Varustekategoria.objects.create(nimi=kategoria, jarjestys=i)
                for j, nimi in enumerate(nimet):
                    Varuste.objects.create(kategoria=kat, nimi=nimi, jarjestys=j)
        if not Tehtavapohja.objects.exists():
            for i, (tila, otsikko, rooli, erapaiva_pv) in enumerate(TEHTAVAPOHJAT):
                Tehtavapohja.objects.create(
                    tila=tila, otsikko=otsikko, rooli=rooli, erapaiva_pv=erapaiva_pv, jarjestys=i
                )
