"""Etusivu (omat tehtävät ja tilannekuva) sekä tehtävälista."""

from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from liikkeet.models import Kayttaja

from .. import logiikka, palvelut
from ..models import Kierto, Tehtava
from .yhteiset import on_htmx, turvallinen_paluu


def etusivu(request):
    omat = (
        Tehtava.objects.filter(tehty=False)
        .filter(palvelut.omat_tehtavat_ehto(request.user))
        .select_related("kierto__ajoneuvo", "vastuu")
    )
    tilamaarat = dict(Kierto.objects.values_list("tila").annotate(n=Count("id")).values_list("tila", "n"))
    tanaan = timezone.localdate()
    varasto = list(Kierto.objects.varastossa().select_related("ajoneuvo").kulusummilla())
    for r in varasto:
        r.seisonut = logiikka.paivia_valissa(r.ostopvm, tanaan) or 0
    return render(
        request,
        "autot/etusivu.html",
        {
            "omat": omat,
            "tilamaarat": tilamaarat,
            "varastossa": len(varasto),
            "sidottu": sum((r.ostohinta or 0) + r.kulut_yht for r in varasto),
            "pisimmat": sorted(varasto, key=lambda r: -r.seisonut)[:5],
        },
    )


def lista(request):
    nayta = request.GET.get("nayta", "avoimet")
    kenelle = request.GET.get("kenelle", "kaikki")
    qs = Tehtava.objects.select_related("kierto__ajoneuvo", "vastuu", "tehnyt")
    if nayta == "avoimet":
        qs = qs.filter(tehty=False)
    elif nayta == "tehdyt":
        qs = qs.filter(tehty=True)
    if kenelle == "omat":
        qs = qs.filter(palvelut.omat_tehtavat_ehto(request.user))
    elif kenelle.isdigit():
        qs = qs.filter(vastuu_id=int(kenelle))
    return render(
        request,
        "autot/tehtavat.html",
        {
            "rivit": qs[:500],
            "nayta": nayta,
            "kenelle": kenelle,
            "kayttajat": Kayttaja.liikkeen.filter(is_active=True).order_by("nimi"),
        },
    )


@require_POST
def kuittaa(request, tid):
    t = get_object_or_404(Tehtava.objects.select_related("kierto__ajoneuvo", "vastuu", "tehnyt"), pk=tid)
    if t.tehty:
        t.tehty, t.tehty_aika, t.tehnyt = False, None, None
    else:
        t.tehty, t.tehty_aika, t.tehnyt = True, timezone.now(), request.user
    t.save(update_fields=["tehty", "tehty_aika", "tehnyt"])
    if on_htmx(request):
        return render(request, "autot/_tehtava.html", {"t": t, "nayta_auto": request.POST.get("nayta_auto") == "1"})
    return turvallinen_paluu(
        request, request.POST.get("takaisin"), reverse("autot:kortti", args=[t.kierto_id]) + "?v=tehtavat"
    )
