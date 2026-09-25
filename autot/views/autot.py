"""Varastolista, uusi auto / tarjous ja palaavan auton tunnistus."""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .. import logiikka, palvelut
from ..forms import UusiAutoLomake
from ..models import Ajoneuvo, Kierto, Koodi, Kuva, Tehtava
from .yhteiset import kortille

NAKYMAT = {
    "varasto": ("Varasto", logiikka.VARASTOTILAT),
    "tarjotut": ("Tarjotut", ["tarjottu"]),
    "myydyt": ("Myydyt", ["myyty", "toimitettu"]),
    "hylatyt": ("Hylätyt", ["hylatty"]),
    "kaikki": ("Kaikki", None),
}


def koodinimet():
    """{ryhma: {koodi: nimi}} pohjia varten."""
    tulos = {ryhma: {} for ryhma, _ in Koodi.RYHMAT}
    for k in Koodi.objects.all():
        tulos[k.ryhma][k.koodi] = k.nimi
    return tulos


def lista(request):
    nakyma = request.GET.get("n", "varasto")
    if nakyma not in NAKYMAT:
        nakyma = "varasto"
    tila = request.GET.get("tila") or None
    if tila not in logiikka.TILA_NIMI:
        tila = None
    haku = (request.GET.get("q") or "").strip()

    qs = Kierto.objects.select_related("ajoneuvo", "toimittaja", "asiakas").kulusummilla()
    tilat = [tila] if tila else NAKYMAT[nakyma][1]
    if tilat:
        qs = qs.filter(tila__in=tilat)
    if haku:
        h = haku.upper()
        qs = qs.filter(
            Q(ajoneuvo__rekisterinumero__icontains=h)
            | Q(ajoneuvo__rekisterinumero__icontains=logiikka.normalisoi_rekisteri(h))
            | Q(ajoneuvo__vin__icontains=h)
            | Q(ajoneuvo__merkki__icontains=haku)
            | Q(ajoneuvo__malli__icontains=haku)
        )
    qs = qs.annotate(
        avoimet=Subquery(
            Tehtava.kaikki.filter(kierto=OuterRef("pk"), tehty=False)
            .values("kierto")
            .annotate(n=Count("id"))
            .values("n")[:1]
        ),
        kuva_id=Subquery(
            Kuva.kaikki.filter(kierto=OuterRef("pk"))
            .exclude(tyyppi="dokumentti")
            .order_by("-paakuva", "jarjestys", "id")
            .values("id")[:1]
        ),
        kierroksia=Subquery(
            Kierto.kaikki.filter(ajoneuvo=OuterRef("ajoneuvo"))
            .values("ajoneuvo")
            .annotate(n=Count("id"))
            .values("n")[:1]
        ),
    ).order_by("-tila_muutettu", "-id")

    alv = request.liike.alv_prosentti
    tanaan = timezone.localdate()
    rivit = list(qs)
    yht = {"osto": 0, "kulut": 0, "kate": 0}
    for r in rivit:
        r.kate_ = r.kate(alv)
        r.tilassa = logiikka.paivia_valissa(timezone.localtime(r.tila_muutettu).date(), tanaan)
        r.varastossa = logiikka.paivia_valissa(r.ostopvm, tanaan) if r.tila in logiikka.VARASTOTILAT else None
        yht["osto"] += r.ostohinta or 0
        yht["kulut"] += r.kulut_yht or 0
        if r.kate_:
            yht["kate"] += r.kate_.kate

    return render(
        request,
        "autot/lista.html",
        {
            "rivit": rivit,
            "nakyma": nakyma,
            "nakymat": [(k, n) for k, (n, _) in NAKYMAT.items()],
            "tila": tila,
            "haku": haku,
            "yht": yht,
            "koodinimet": koodinimet(),
        },
    )


@require_GET
def tarkista(request):
    """Uusi-lomake kysyy tätä, kun rekisteri tai VIN on syötetty: onko auto ollut meillä ennen?"""
    ajoneuvo = palvelut.etsi_ajoneuvo(request.GET.get("vin"), request.GET.get("rekisterinumero"))
    konteksti = {"ajoneuvo": ajoneuvo}
    if ajoneuvo:
        kierrot = list(ajoneuvo.kierrot.select_related("asiakas").order_by("-id"))
        konteksti.update(
            kierrot=kierrot,
            aktiivinen=next((k for k in kierrot if not k.paattynyt), None),
            taytto={
                k: getattr(ajoneuvo, k)
                for k in ("merkki", "malli", "mallitarkenne", "vuosimalli", "kayttovoima", "vaihteisto", "korimalli")
            },
        )
    return render(request, "autot/_aiempi_auto.html", konteksti)


AJONEUVON_TIEDOT = ["merkki", "malli", "mallitarkenne", "vuosimalli", "kayttovoima", "vaihteisto", "korimalli"]


def uusi(request):
    lomake = UusiAutoLomake(request.POST or None)
    if request.method == "POST" and lomake.is_valid():
        d = lomake.cleaned_data
        ajoneuvo = palvelut.etsi_ajoneuvo(d["vin"], d["rekisterinumero"])
        if ajoneuvo:
            avoin = palvelut.avoin_kierto(ajoneuvo)
            if avoin:
                messages.error(request, "Tämä auto on jo järjestelmässä avoimena. Avattiin olemassa oleva kortti.")
                return kortille(avoin.pk)
        try:
            with transaction.atomic():
                palaava = ajoneuvo is not None
                if palaava:
                    # Päivitä tunnisteet ja puuttuvat tiedot, jos ne on annettu
                    vanhat = {k: getattr(ajoneuvo, k) for k in ["rekisterinumero", "vin"] + AJONEUVON_TIEDOT}
                    for kentta in vanhat:
                        arvo = d.get(kentta)
                        if arvo not in (None, ""):
                            setattr(ajoneuvo, kentta, arvo)
                    ajoneuvo.save()
                    palvelut.kirjaa_muutokset(request.user, ajoneuvo, vanhat, vanhat.keys())
                else:
                    tekstit = {k: d.get(k) or "" for k in ["rekisterinumero", "vin"] + AJONEUVON_TIEDOT}
                    tekstit.pop("vuosimalli")
                    ajoneuvo = Ajoneuvo.objects.create(vuosimalli=d.get("vuosimalli"), **tekstit)
                tila = "ostettu" if d["heti_ostettu"] else "tarjottu"
                kierto = palvelut.avaa_kierto(
                    ajoneuvo,
                    request.user,
                    tila=tila,
                    km=d.get("km"),
                    toimittaja=d.get("toimittaja"),
                    ostokanava=d.get("ostokanava") or "",
                    tarjottu_hinta=d.get("tarjottu_hinta"),
                    alv_kasittely=d["alv_kasittely"],
                    ostohinta=d.get("ostohinta") if tila == "ostettu" else None,
                    huomiot=d.get("huomiot") or "",
                )
        except (palvelut.SiirtoVirhe, IntegrityError):
            messages.error(request, "Autolla on jo avoin kierros.")
            return redirect("autot:lista")
        if palaava:
            messages.success(
                request,
                "Auto on ollut meillä aiemmin. Sille avattiin uusi kierros, ja aiemmat "
                "kierrokset näkyvät Historia-välilehdellä.",
            )
        else:
            messages.success(request, "Auto lisätty.")
        return kortille(kierto.pk)
    return render(request, "autot/uusi.html", {"lomake": lomake})
