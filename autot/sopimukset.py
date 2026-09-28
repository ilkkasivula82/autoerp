"""Osto- ja myyntisopimukset: sopimuksen luonti ja sen vaikutus kiertoihin.

Autot tulevat varastoon vain näillä tavoilla (ostohinta aina tiedossa):
  - ostosopimus (tee_ostosopimus)
  - myyntisopimuksen vaihtoajoneuvo (tee_myyntisopimus)
  - suora varastolisäys ostohinnalla (Uusi auto -lomake / tilasiirto)
Tietokannan rajoite varmistaa, ettei varastossa ole autoa ilman ostohintaa.

Kaikki funktiot olettavat, että liike on aktivoitu.
"""

from django.db import transaction
from django.db.models import Max

from liikkeet.models import Liike

from . import logiikka, palvelut
from .models import Ajoneuvo, Sopimus, SopimusRivi, Yritys

# Sopimuksen vastapuolen kenttä -> Yritys-mallin kenttä
VASTAPUOLEN_KENTAT = {
    "vp_nimi": "nimi",
    "vp_tunnus": "y_tunnus",
    "vp_lahiosoite": "lahiosoite",
    "vp_postinumero": "postinumero",
    "vp_postitoimipaikka": "postitoimipaikka",
    "vp_puhelin": "puhelin",
    "vp_sahkoposti": "sahkoposti",
    "vp_tilinumero": "tilinumero",
    "vp_alv_velvollinen": "alv_velvollinen",
}
SOPIMUKSEN_KENTAT = list(VASTAPUOLEN_KENTAT) + [
    "vp2_nimi",
    "vp2_tunnus",
    "vp2_osoite",
    "vp2_puhelin",
    "vp2_sahkoposti",
    "tunnistus",
    "pep",
    "pvm",
    "toimitusaika",
    "maksutapa",
    "lisatiedot",
    "toimistokulut",
    "etumaksu",
    "rahoitettava",
    "rahoitusyhtio",
    "erapaiva",
]
RIVIN_KENTAT = [
    "hinta",
    "jaannosvelka",
    "jaannosvelan_haltija",
    "alv_kasittely",
    "km",
    "katsastettu",
    "kolaroitu",
    "maahantuotu",
    "mittari_vastaa",
    "rakennemuutoksia",
]


def vastapuolen_tiedot(yritys):
    """Yrityksen tiedot sopimuksen vastapuolikenttinä (lomakkeen esitäyttö)."""
    return {vk: getattr(yritys, yk) for vk, yk in VASTAPUOLEN_KENTAT.items()}


def ratkaise_vastapuoli(yritys, tiedot, tyyppi="yksityinen"):
    """Valittu yritys päivitettynä sopimuksen tiedoilla, tai uusi yritys tiedoista."""
    if yritys is None:
        return Yritys.objects.create(
            tyyppi=tyyppi,
            **{
                yk: tiedot.get(vk) or ("" if yk != "alv_velvollinen" else False)
                for vk, yk in VASTAPUOLEN_KENTAT.items()
            },
        )
    muuttui = []
    for vk, yk in VASTAPUOLEN_KENTAT.items():
        arvo = tiedot.get(vk)
        if arvo not in (None, "") and getattr(yritys, yk) != arvo:
            setattr(yritys, yk, arvo)
            muuttui.append(yk)
    if muuttui:
        yritys.save(update_fields=muuttui)
    return yritys


def _uusi_numero(liike_id):
    # Lukitaan liikkeen rivi, jotta samanaikaiset sopimukset eivät saa samaa numeroa.
    Liike.objects.select_for_update().get(pk=liike_id)
    return (Sopimus.objects.aggregate(m=Max("numero"))["m"] or 0) + 1


def _luo_sopimus(tyyppi, kayttaja, vastapuoli, tiedot):
    kentat = {k: tiedot[k] for k in SOPIMUKSEN_KENTAT if tiedot.get(k) is not None}
    # Tallennetaan vastapuolen tiedot sopimushetken mukaisina
    for vk, yk in VASTAPUOLEN_KENTAT.items():
        kentat[vk] = getattr(vastapuoli, yk)
    return Sopimus.objects.create(
        tyyppi=tyyppi, numero=_uusi_numero(vastapuoli.liike_id), vastapuoli=vastapuoli, laatija=kayttaja, **kentat
    )


def _luo_rivi(sopimus, kierto, rooli, tiedot):
    a = kierto.ajoneuvo
    kentat = {k: tiedot[k] for k in RIVIN_KENTAT if tiedot.get(k) not in (None, "")}
    kentat.setdefault("km", kierto.km)
    return SopimusRivi.objects.create(
        sopimus=sopimus,
        kierto=kierto,
        rooli=rooli,
        rekisterinumero=a.rekisterinumero,
        vin=a.vin,
        merkki_malli=" ".join(x for x in [a.merkki, a.malli, a.mallitarkenne] if x),
        ensirekisterointi=a.ensirekisterointi,
        **kentat,
    )


def voi_tehda_ostosopimuksen(kierto):
    if kierto.tila not in ["tarjottu"] + logiikka.VARASTOTILAT:
        return False
    return not kierto.sopimusrivit.filter(sopimus__tyyppi="osto").exists()


def voi_tehda_myyntisopimuksen(kierto):
    return kierto.tila in logiikka.VARASTOTILAT


@transaction.atomic
def tee_ostosopimus(kierto, kayttaja, *, yritys, tiedot, kohde, alv_prosentti):
    """Ostosopimus kierrolle: auto varastoon ostohinnalla. Tarjottu auto siirtyy tilaan Ostettu.

    kohde: dict (hinta sis. mahdollisen alv:n, jaannosvelka, alv_kasittely, km, ilmoitetut tiedot).
    """
    if not voi_tehda_ostosopimuksen(kierto):
        raise palvelut.SiirtoVirhe("Autolle ei voi tehdä ostosopimusta (jo ostettu sopimuksella tai myyty).")
    vastapuoli = ratkaise_vastapuoli(yritys, tiedot)
    sopimus = _luo_sopimus("osto", kayttaja, vastapuoli, tiedot)
    alv_kasittely = kohde.get("alv_kasittely") or kierto.alv_kasittely
    ostohinta = logiikka.kierron_hinta(kohde["hinta"], alv_kasittely, alv_prosentti)

    kentat = ["toimittaja", "ostokanava", "km", "alv_kasittely", "ostohinta", "ostopvm"]
    vanhat = {k: getattr(kierto, k) for k in kentat}
    kierto.toimittaja = vastapuoli
    kierto.ostokanava = kierto.ostokanava or vastapuoli.tyyppi
    kierto.km = kohde.get("km") or kierto.km
    kierto.alv_kasittely = alv_kasittely
    if kierto.tila == "tarjottu":
        # Tilasiirto kirjaa itse hinta-, päivä- ja verokohtelumuutokset lokiin.
        palvelut.siirra_tila(
            kierto, "ostettu", kayttaja, ostohinta=ostohinta, ostopvm=sopimus.pvm, alv_kasittely=alv_kasittely
        )
        kentat = ["toimittaja", "ostokanava", "km"]
    else:
        kierto.ostohinta, kierto.ostopvm = ostohinta, sopimus.pvm
        kierto.save()
    palvelut.kirjaa_muutokset(kayttaja, kierto, vanhat, kentat)
    _luo_rivi(sopimus, kierto, "kohde", {**kohde, "alv_kasittely": alv_kasittely})
    palvelut.kirjaa(kayttaja, "kierto", kierto.pk, "ostosopimus", "", f"nro {sopimus.numero}")
    return sopimus


@transaction.atomic
def tee_myyntisopimus(kierto, kayttaja, *, yritys, tiedot, kohde, vaihdot=(), alv_prosentti):
    """Myyntisopimus: auto myydyksi, vaihtoajoneuvot varastoon ostohinnalla = vaihtohinta.

    vaihdot: dictit, joissa ajoneuvon tiedot (rekisterinumero, vin, merkki, malli, mallitarkenne,
    vuosimalli) ja rivin tiedot (hinta, jaannosvelka, alv_kasittely, km, ilmoitetut tiedot).
    Jos jokin vaihtoajoneuvo ei kelpaa, mitään ei tallenneta.
    """
    if not voi_tehda_myyntisopimuksen(kierto):
        raise palvelut.SiirtoVirhe("Vain varastossa olevan auton voi myydä.")
    vastapuoli = ratkaise_vastapuoli(yritys, tiedot)
    sopimus = _luo_sopimus("myynti", kayttaja, vastapuoli, tiedot)

    myyntihinta = logiikka.kierron_hinta(kohde["hinta"], kierto.alv_kasittely, alv_prosentti)
    if kohde.get("km"):
        kierto.km = kohde["km"]
    palvelut.siirra_tila(kierto, "myyty", kayttaja, asiakas=vastapuoli, myyntihinta=myyntihinta, myyntipvm=sopimus.pvm)
    _luo_rivi(sopimus, kierto, "kohde", {**kohde, "alv_kasittely": kierto.alv_kasittely})

    for v in vaihdot:
        ajoneuvo = palvelut.etsi_ajoneuvo(v.get("vin"), v.get("rekisterinumero"))
        if ajoneuvo is None:
            ajoneuvo = Ajoneuvo.objects.create(
                rekisterinumero=v.get("rekisterinumero") or "",
                vin=v.get("vin") or "",
                merkki=v["merkki"],
                malli=v["malli"],
                mallitarkenne=v.get("mallitarkenne") or "",
                vuosimalli=v.get("vuosimalli"),
                ensirekisterointi=v.get("ensirekisterointi"),
            )
        elif palvelut.avoin_kierto(ajoneuvo):
            raise palvelut.SiirtoVirhe(f"Vaihtoajoneuvo {ajoneuvo} on jo varastossa tai tarjolla (avoin kierros).")
        alv_kasittely = v.get("alv_kasittely") or "marginaali"
        vaihtoauto = palvelut.avaa_kierto(
            ajoneuvo,
            kayttaja,
            tila="ostettu",
            km=v.get("km"),
            toimittaja=vastapuoli,
            ostokanava="vaihto",
            alv_kasittely=alv_kasittely,
            ostohinta=logiikka.kierron_hinta(v["hinta"], alv_kasittely, alv_prosentti),
            ostopvm=sopimus.pvm,
            huomiot=f"Vaihtoauto, myyntisopimus nro {sopimus.numero}",
        )
        _luo_rivi(sopimus, vaihtoauto, "vaihto", {**v, "alv_kasittely": alv_kasittely})
        palvelut.kirjaa(kayttaja, "kierto", vaihtoauto.pk, "myyntisopimuksen vaihtoauto", "", f"nro {sopimus.numero}")

    palvelut.kirjaa(kayttaja, "kierto", kierto.pk, "myyntisopimus", "", f"nro {sopimus.numero}")
    return sopimus
