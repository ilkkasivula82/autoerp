"""Laskut: sopimuksen laskujen yhteenveto, laskulista, tulostettava lasku ja maksun kirjaus.

Laskut syntyvät sopimuksesta automaattisesti (sopimukset.luo_laskut).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import logiikka
from .. import sopimukset as sopimuspalvelu
from ..models import Lasku, Sopimus
from .yhteiset import turvallinen_paluu

TILAT = [("avoimet", "Avoimet"), ("maksetut", "Maksetut"), ("kaikki", "Kaikki")]


def _verotus(rivit, summa, alv):
    """Kaupan kohteiden verotus: marginaali tai ALV (veroton, vero, verollinen) summasta."""
    if any(r.alv_kasittely == "alv" for r in rivit):
        vero = logiikka.alv_osuus(summa, "alv", alv)
        return {"alv": True, "veroton": summa - vero, "vero": vero, "verollinen": summa}
    return {"alv": False}


@require_GET
def sopimuksen_laskut(request, sid):
    """Myynti- tai ostosopimuksen yhteenveto: miten hinta jakautuu ja mitä laskuja siitä syntyy."""
    s = get_object_or_404(Sopimus.objects.select_related("vastapuoli"), pk=sid)
    alv = request.liike.alv_prosentti
    rivit = list(s.rivit.select_related("kierto"))
    kohteet = [r for r in rivit if r.rooli == "kohde"]
    vaihdot = [r for r in rivit if r.rooli == "vaihto"]
    summat = s.summat()
    for r in vaihdot:
        r.verotus = _verotus([r], r.hinta, alv)
        r.nettohyvitys = r.hinta - r.jaannosvelka
    return render(
        request,
        "autot/sopimuksen_laskut.html",
        {
            "s": s,
            "kohteet": kohteet,
            "vaihdot": vaihdot,
            "summat": summat,
            "palautettava": -summat.maksettava,
            "verotus": _verotus(kohteet, summat.kateishinta, alv),
            "alv_prosentti": alv,
            "laskut": list(s.laskut.all().order_by("suunta", "numero")),
        },
    )


@require_POST
def luo_laskut(request, sid):
    """Laskut sopimukselle, joka on tehty ennen automaattista laskutusta."""
    s = get_object_or_404(Sopimus, pk=sid)
    if s.laskut.exists():
        messages.info(request, "Sopimuksen laskut on jo luotu.")
    else:
        laskut = sopimuspalvelu.luo_laskut(s)
        messages.success(request, f"{len(laskut)} laskua luotu.")
    return redirect("autot:sopimuksen_laskut", sid=s.pk)


@require_GET
def lista(request):
    suunta = request.GET.get("suunta")
    tila = request.GET.get("tila", "avoimet")
    qs = Lasku.objects.select_related("sopimus")
    if suunta in dict(Lasku.SUUNNAT):
        qs = qs.filter(suunta=suunta)
    if tila == "avoimet":
        qs = qs.filter(maksettu_pvm__isnull=True)
    elif tila == "maksetut":
        qs = qs.filter(maksettu_pvm__isnull=False)
    rivit = list(qs.order_by("maksettu_pvm", "erapaiva", "-numero")[:500])
    tanaan = timezone.localdate()
    for r in rivit:
        r.myohassa = not r.maksettu and r.erapaiva is not None and r.erapaiva < tanaan
    return render(
        request,
        "autot/laskut.html",
        {
            "rivit": rivit,
            "suunta": suunta,
            "tila": tila,
            "SUUNNAT": Lasku.SUUNNAT,
            "TILAT": TILAT,
            "myynti_avoinna": sum(r.summa for r in rivit if r.suunta == "myynti" and not r.maksettu),
            "osto_avoinna": sum(r.summa for r in rivit if r.suunta == "osto" and not r.maksettu),
        },
    )


@require_GET
def lasku(request, lid):
    """Lasku tulostettavana asiakirjana."""
    lk = get_object_or_404(Lasku.objects.select_related("sopimus"), pk=lid)
    s = lk.sopimus
    alv = request.liike.alv_prosentti
    rivit = list(s.rivit.all())
    kohteet = [r for r in rivit if r.rooli == "kohde"]
    if lk.laji == "vaihtoauto":
        verotus = _verotus([r for r in rivit if r.rooli == "vaihto"], lk.summa, alv)
    else:
        verotus = _verotus(kohteet, s.summat().kateishinta, alv)
    return render(
        request,
        "autot/lasku.html",
        {
            "lk": lk,
            "s": s,
            "liike": request.liike,
            "kohteet": kohteet,
            "verotus": verotus,
            "alv_prosentti": alv,
            "sahkoposti": _sahkoposti(lk, request.liike),
        },
    )


def _sahkoposti(lk, liike):
    if lk.suunta != "myynti" or lk.maksettu:
        return None
    rivit = [
        f"Hei {lk.osapuoli_nimi},",
        "",
        lk.kuvaus,
        "",
        f"Summa: {logiikka.euro(lk.summa, True)}",
        f"Eräpäivä: {lk.erapaiva:%-d.%-m.%Y}" if lk.erapaiva else None,
        f"Tilinumero: {lk.tilinumero}" if lk.tilinumero else None,
        f"Viitenumero: {lk.viitenumero}" if lk.viitenumero else None,
        f"Saaja: {liike.nimi}",
        "",
        "Ystävällisin terveisin",
        liike.nimi,
    ]
    return {"otsikko": f"Lasku {lk.numero}: {liike.nimi}", "teksti": "\n".join(r for r in rivit if r is not None)}


@require_POST
def merkitse_maksetuksi(request, lid):
    lk = get_object_or_404(Lasku, pk=lid)
    lk.maksettu_pvm = None if lk.maksettu else timezone.localdate()
    lk.save(update_fields=["maksettu_pvm"])
    messages.success(request, f"Lasku {lk.numero} {'maksettu' if lk.maksettu else 'avoin'}.")
    return turvallinen_paluu(request, request.POST.get("takaisin"), reverse("autot:lasku", args=[lk.pk]))
