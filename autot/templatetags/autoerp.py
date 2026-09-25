"""Pohjien apusuodattimet. Ladataan kaikkiin pohjiin automaattisesti (TEMPLATES.builtins)."""

from django import template
from django.utils import timezone

from autot import logiikka

register = template.Library()


@register.filter
def euro(sentit, desimaalit=False):
    """{{ k.ostohinta|euro }} -> '12 500 €', {{ x|euro:True }} -> '12 500,50 €'"""
    return logiikka.euro(sentit, bool(desimaalit))


@register.filter
def euro_input(sentit):
    return logiikka.euro_input(sentit)


@register.filter
def pvm(arvo):
    """Päivämäärä muodossa 24.9.2026."""
    if not arvo:
        return "–"
    if hasattr(arvo, "hour"):
        arvo = timezone.localtime(arvo).date() if timezone.is_aware(arvo) else arvo.date()
    return f"{arvo.day}.{arvo.month}.{arvo.year}"


@register.filter
def km(arvo):
    if arvo in (None, ""):
        return "–"
    return f"{int(arvo):,}".replace(",", " ")


@register.filter
def pilkku(arvo):
    """Desimaaliluku suomalaisittain: 25.5 -> 25,5"""
    if arvo is None:
        return ""
    teksti = f"{arvo:f}" if hasattr(arvo, "as_tuple") else str(arvo)
    if "." in teksti:
        teksti = teksti.rstrip("0").rstrip(".")
    return teksti.replace(".", ",")


@register.filter
def tila_nimi(tila):
    return logiikka.TILA_NIMI.get(tila, tila)


@register.filter
def tila_luokka(tila):
    return logiikka.TILA_LUOKKA.get(tila, "")


@register.filter
def paivia(alku):
    """Päiviä annetusta päivästä tähän päivään."""
    if not alku:
        return None
    if hasattr(alku, "hour"):
        alku = timezone.localtime(alku).date()
    return logiikka.paivia_valissa(alku, timezone.localdate())


@register.filter
def hae(sanakirja, avain):
    """{{ sanakirja|hae:avain }}"""
    if not sanakirja:
        return None
    return sanakirja.get(avain)


@register.filter
def valinta(arvo, valinnat):
    """Koodi näyttönimeksi valintalistasta: {{ k.ostokanava|valinta:OSTOKANAVAT }}"""
    return dict(valinnat or []).get(arvo, arvo or "")


@register.inclusion_tag("autot/_tila.html")
def tila(tila, iso=False):
    return {
        "tila": tila,
        "nimi": logiikka.TILA_NIMI.get(tila, tila),
        "luokka": logiikka.TILA_LUOKKA.get(tila, ""),
        "iso": iso,
    }


@register.filter
def json_attr(arvo):
    """JSON HTML-attribuuttiin. Autoescape muuntaa lainausmerkit, selain palauttaa ne."""
    import json

    return json.dumps(arvo, default=str, ensure_ascii=False)
