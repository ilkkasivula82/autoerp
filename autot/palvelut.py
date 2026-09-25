"""Toiminnot, joita näkymät ja komennot käyttävät: tilasiirrot, tehtävät, muutosloki.

Kaikki funktiot olettavat, että liike on aktivoitu (näkymissä LiikeMiddleware).
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Replace, Upper
from django.utils import timezone

from . import logiikka
from .models import Ajoneuvo, Kierto, Muutosloki, Tehtava, Tehtavapohja, Tilahistoria


class SiirtoVirhe(ValueError):
    """Tilasiirto ei ole sallittu tai siitä puuttuu pakollisia tietoja."""


def _tekstiksi(arvo):
    if arvo is None or arvo == "":
        return ""
    return str(arvo)


def kirjaa(kayttaja, kohde, kohde_id, kentta, vanha, uusi):
    """Kirjaa muutoksen muutoslokiin, jos arvo oikeasti muuttui."""
    vanha, uusi = _tekstiksi(vanha), _tekstiksi(uusi)
    if vanha == uusi:
        return None
    return Muutosloki.objects.create(
        kayttaja=kayttaja, kohde=kohde, kohde_id=kohde_id, kentta=kentta, vanha=vanha, uusi=uusi
    )


RAHAKENTAT = {"tarjottu_hinta", "ostohinta", "pyyntihinta", "myyntihinta", "arvioitu_korjaus"}


def lokiarvo(kentta, arvo):
    """Muutoslokiin luettava arvo: rahat euroina, päivät suomalaisittain."""
    if arvo is None or arvo == "":
        return ""
    if kentta in RAHAKENTAT:
        return logiikka.euro(arvo, desimaalit=True)
    if hasattr(arvo, "isoformat") and not hasattr(arvo, "hour"):
        return f"{arvo.day}.{arvo.month}.{arvo.year}"
    if hasattr(arvo, "nimi"):
        return arvo.nimi
    return str(arvo)


def kirjaa_muutokset(kayttaja, olio, vanhat, kentat):
    """Vertaa tallennettua oliota vanhoihin arvoihin ja kirjaa muuttuneet kentät."""
    kohde = "kierto" if isinstance(olio, Kierto) else "ajoneuvo"
    for kentta in kentat:
        vanha, uusi = vanhat.get(kentta), getattr(olio, kentta)
        if vanha != uusi:
            nimi = olio._meta.get_field(kentta).verbose_name
            kirjaa(kayttaja, kohde, olio.pk, nimi, lokiarvo(kentta, vanha), lokiarvo(kentta, uusi))


def luo_tehtavat_tilalle(kierto, tila, kayttaja):
    """Luo tehtäväpohjien mukaiset tehtävät, kun kierto siirtyy tilaan. Palauttaa määrän."""
    pohjat = list(Tehtavapohja.objects.filter(tila=tila, aktiivinen=True))
    tanaan = timezone.localdate()
    for p in pohjat:
        Tehtava.objects.create(
            kierto=kierto,
            tila_vaihe=tila,
            otsikko=p.otsikko,
            vastuu_id=p.vastuu_id,
            rooli=p.rooli,
            erapaiva=tanaan + timedelta(days=p.erapaiva_pv) if p.erapaiva_pv is not None else None,
            luonut=kayttaja,
        )
    return len(pohjat)


def etsi_ajoneuvo(vin=None, rekisterinumero=None):
    """Etsii aiemmin kirjatun ajoneuvon. VIN ensin, koska rekisterinumero voi vaihtua."""
    vin = (vin or "").strip().upper()
    if vin:
        a = Ajoneuvo.objects.filter(vin__iexact=vin).order_by("-id").first()
        if a:
            return a
    avain = logiikka.rekisteri_hakuavain(rekisterinumero)
    if avain:
        return (
            Ajoneuvo.objects.annotate(_rek=Replace(Upper("rekisterinumero"), Value("-"), Value("")))
            .filter(_rek=avain)
            .order_by("-id")
            .first()
        )
    return None


def avoin_kierto(ajoneuvo):
    return Kierto.objects.filter(ajoneuvo=ajoneuvo).avoimet().first()


@transaction.atomic
def avaa_kierto(ajoneuvo, kayttaja, tila="tarjottu", **kentat):
    """Avaa ajoneuvolle uuden kierroksen, kirjaa tilahistorian ja luo vaiheen tehtävät."""
    if avoin_kierto(ajoneuvo):
        raise SiirtoVirhe("Autolla on jo avoin kierros.")
    tanaan = timezone.localdate()
    kentat.setdefault("tarjottu_pvm", tanaan)
    if tila == "ostettu":
        kentat.setdefault("ostopvm", tanaan)
    kierto = Kierto.objects.create(ajoneuvo=ajoneuvo, tila=tila, luonut=kayttaja, **kentat)
    Tilahistoria.objects.create(kierto=kierto, vanha_tila="", uusi_tila=tila, kayttaja=kayttaja)
    luo_tehtavat_tilalle(kierto, tila, kayttaja)
    return kierto


@transaction.atomic
def siirra_tila(kierto, uusi, kayttaja, **tiedot):
    """Siirtää kierron uuteen tilaan.

    tiedot: siirtoon liittyvät kentät (ostohinta, ostopvm, alv_kasittely,
    asiakas, myyntihinta, myyntipvm, laskunumero, toimitettu_pvm, hylkayksen_syy).
    Palauttaa luotujen tehtävien määrän.
    """
    vanha = kierto.tila
    if not logiikka.siirto_sallittu(vanha, uusi):
        raise SiirtoVirhe("Tilasiirto ei ole sallittu.")
    taakse = logiikka.on_taaksepain(vanha, uusi)
    tanaan = timezone.localdate()
    paivitys = {}

    if uusi == "ostettu" and not taakse:
        hinta = tiedot.get("ostohinta") if tiedot.get("ostohinta") is not None else kierto.ostohinta
        if hinta is None:
            raise SiirtoVirhe("Anna ostohinta, kun merkitset auton ostetuksi.")
        paivitys.update(
            ostohinta=hinta,
            ostopvm=tiedot.get("ostopvm") or kierto.ostopvm or tanaan,
            alv_kasittely=tiedot.get("alv_kasittely") or kierto.alv_kasittely,
        )
    elif uusi == "hylatty":
        paivitys["hylkayksen_syy"] = tiedot.get("hylkayksen_syy") or ""
    elif uusi in ("varattu", "myyty") and not taakse:
        asiakas = tiedot.get("asiakas") or kierto.asiakas
        paivitys["asiakas"] = asiakas
        if uusi == "myyty":
            hinta = tiedot.get("myyntihinta") if tiedot.get("myyntihinta") is not None else kierto.myyntihinta
            if hinta is None or asiakas is None:
                raise SiirtoVirhe("Anna ostaja ja myyntihinta, kun merkitset auton myydyksi.")
            paivitys.update(
                myyntihinta=hinta,
                myyntipvm=tiedot.get("myyntipvm") or kierto.myyntipvm or tanaan,
                laskunumero=tiedot.get("laskunumero") or kierto.laskunumero,
            )
    elif uusi == "toimitettu":
        paivitys["toimitettu_pvm"] = tiedot.get("toimitettu_pvm") or tanaan

    vanhat = {k: getattr(kierto, k) for k in paivitys}
    for kentta, arvo in paivitys.items():
        setattr(kierto, kentta, arvo)
    kierto.tila = uusi
    kierto.tila_muutettu = timezone.now()
    kierto.save()
    kirjaa_muutokset(kayttaja, kierto, vanhat, paivitys.keys())
    Tilahistoria.objects.create(kierto=kierto, vanha_tila=vanha, uusi_tila=uusi, kayttaja=kayttaja)
    kirjaa(kayttaja, "kierto", kierto.pk, "tila", logiikka.TILA_NIMI[vanha], logiikka.TILA_NIMI[uusi])
    return luo_tehtavat_tilalle(kierto, uusi, kayttaja)


def vaihekestot(historia):
    """Tilahistoriasta vaiheiden kestot päivinä: [(siirto, päiviä), ...]."""
    tulos = []
    for i, h in enumerate(historia):
        loppu = historia[i + 1].aika if i + 1 < len(historia) else timezone.now()
        tulos.append((h, (timezone.localtime(loppu).date() - timezone.localtime(h.aika).date()).days))
    return tulos


def omat_tehtavat_ehto(kayttaja):
    """Omat tehtävät: minulle nimetyt + nimeämättömät oman roolin tehtävät."""
    return Q(vastuu=kayttaja) | Q(vastuu__isnull=True, rooli=kayttaja.rooli)
