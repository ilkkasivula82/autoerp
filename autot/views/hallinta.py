"""Hallinta: yritykset, käyttäjät, varustekatalogi, tehtäväpohjat, asetukset ja koodistot."""

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render

from liikkeet.models import Kayttaja

from .. import logiikka
from ..forms import (
    KayttajaLomake,
    KoodiLomake,
    LiikeLomake,
    TehtavapohjaLomake,
    VarusteetLomake,
    VarustekategoriaLomake,
    VarusteMuokkausLomake,
    YritysLomake,
)
from ..models import AjoneuvonVaruste, Kierto, Koodi, Tehtavapohja, Varuste, Varustekategoria, Yritys
from .yhteiset import rooli_vaaditaan

# ---------- yritykset ----------


def yritykset(request):
    muokattava = None
    if request.GET.get("muokkaa", "").isdigit():
        muokattava = get_object_or_404(Yritys, pk=int(request.GET["muokkaa"]))
    if request.method == "POST":
        yid = request.POST.get("id", "")
        if yid.isdigit():
            muokattava = get_object_or_404(Yritys, pk=int(yid))
        lomake = YritysLomake(request.POST, instance=muokattava)
        if lomake.is_valid():
            lomake.save()
            messages.success(request, "Yritys tallennettu.")
            return redirect("autot:yritykset")
    else:
        lomake = YritysLomake(instance=muokattava)
    rivit = Yritys.objects.annotate(
        ostettu_n=Count("ostot", filter=Q(ostot__ostohinta__isnull=False), distinct=True),
        myyty_n=Count("myynnit", filter=Q(myynnit__myyntihinta__isnull=False), distinct=True),
        maksamatta_n=Count(
            "myynnit", filter=Q(myynnit__myyntihinta__isnull=False, myynnit__maksettu_pvm__isnull=True), distinct=True
        ),
    )
    return render(request, "autot/yritykset.html", {"rivit": rivit, "lomake": lomake, "m": muokattava})


def yritys(request, yid):
    y = get_object_or_404(Yritys, pk=yid)
    kaupat = list(
        Kierto.objects.filter(Q(toimittaja=y) | Q(asiakas=y)).select_related("ajoneuvo").kulusummilla().order_by("-id")
    )
    alv = request.liike.alv_prosentti
    kate_ostetuista = 0
    ostettu = myyty = 0
    for r in kaupat:
        r.suunta = "osto" if r.toimittaja_id == y.pk else "myynti"
        r.kate_ = r.kate(alv)
        if r.suunta == "osto" and r.ostohinta is not None:
            ostettu += 1
            if r.kate_ and not r.kate_.arvio:
                kate_ostetuista += r.kate_.kate
        if r.asiakas_id == y.pk and r.myyntihinta is not None:
            myyty += 1
    return render(
        request,
        "autot/yritys.html",
        {
            "y": y,
            "kaupat": kaupat,
            "kate_ostetuista": kate_ostetuista,
            "ostettu": ostettu,
            "myyty": myyty,
        },
    )


# ---------- käyttäjät ----------


@rooli_vaaditaan("admin")
def kayttajat(request):
    if request.method == "POST":
        kid = request.POST.get("id", "")
        instance = get_object_or_404(Kayttaja.liikkeen, pk=int(kid)) if kid.isdigit() else None
        lomake = KayttajaLomake(request.POST, instance=instance, prefix=f"k{kid}" if instance else "uusi")
        if lomake.is_valid():
            if instance == request.user and (
                not lomake.cleaned_data.get("is_active", True) or lomake.cleaned_data["rooli"] != "admin"
            ):
                messages.error(request, "Et voi poistaa omaa ylläpito-oikeuttasi.")
            else:
                lomake.save()
                messages.success(request, "Käyttäjä tallennettu.")
            return redirect("autot:kayttajat")
        messages.error(request, "Tarkista tiedot: " + "; ".join(" ".join(v) for v in lomake.errors.values()))
        return redirect("autot:kayttajat")
    rivit = []
    for u in Kayttaja.liikkeen.order_by("-is_active", "nimi"):
        lomake = KayttajaLomake(instance=u, prefix=f"k{u.pk}")
        for kentta in lomake.fields.values():
            kentta.widget.attrs["form"] = f"u{u.pk}"  # rivin kentät kuuluvat rivin lomakkeeseen
        rivit.append((u, lomake))
    return render(request, "autot/kayttajat.html", {"rivit": rivit, "uusi": KayttajaLomake(prefix="uusi")})


# ---------- varustekatalogi ----------


def varusteet(request):
    if request.method == "POST":
        toiminto = request.POST.get("toiminto")
        if toiminto == "kategoria":
            lomake = VarustekategoriaLomake(request.POST)
            if lomake.is_valid():
                kat = lomake.save(commit=False)
                kat.jarjestys = (Varustekategoria.objects.aggregate(m=Max("jarjestys"))["m"] or 0) + 1
                kat.save()
        elif toiminto == "varuste":
            lomake = VarusteetLomake(request.POST)
            if lomake.is_valid():
                kat = lomake.cleaned_data["kategoria"]
                for nimi in lomake.cleaned_data["nimet"].splitlines():
                    if nimi.strip():
                        Varuste.objects.create(kategoria=kat, nimi=nimi.strip()[:200])
        elif toiminto in ("nakyvyys", "nimea"):
            varuste = get_object_or_404(Varuste, pk=request.POST.get("id") or 0)
            if toiminto == "nakyvyys":
                varuste.aktiivinen = not varuste.aktiivinen
                varuste.save(update_fields=["aktiivinen"])
            else:
                lomake = VarusteMuokkausLomake(request.POST, instance=varuste)
                if lomake.is_valid():
                    lomake.save()
        return redirect("autot:varusteet")
    kaytossa = dict(AjoneuvonVaruste.objects.values_list("varuste").annotate(n=Count("id")).values_list("varuste", "n"))
    kategoriat = []
    kaikki = list(Varuste.objects.all())
    for v in kaikki:
        v.kaytossa = kaytossa.get(v.id, 0)
    for kat in Varustekategoria.objects.all():
        kategoriat.append((kat, [v for v in kaikki if v.kategoria_id == kat.id]))
    return render(
        request,
        "autot/varusteet.html",
        {
            "kategoriat": kategoriat,
            "kaikki_kategoriat": [k for k, _ in kategoriat],
            "lisayslomake": VarusteetLomake(),
            "kategorialomake": VarustekategoriaLomake(),
        },
    )


# ---------- tehtäväpohjat ----------


def tehtavapohjat(request):
    if request.method == "POST":
        if request.POST.get("toiminto") == "poista":
            get_object_or_404(Tehtavapohja, pk=request.POST.get("id") or 0).delete()
        else:
            lomake = TehtavapohjaLomake(request.POST)
            if lomake.is_valid():
                lomake.save()
            else:
                messages.error(request, "Tarkista tehtäväpohjan tiedot.")
        return redirect("autot:tehtavapohjat")
    pohjat = list(Tehtavapohja.objects.select_related("vastuu"))
    ryhmat = [
        (tila, nimi, luokka, [p for p in pohjat if p.tila == tila], TehtavapohjaLomake(initial={"tila": tila}))
        for tila, nimi, luokka in logiikka.TILAT
    ]
    return render(request, "autot/tehtavapohjat.html", {"ryhmat": ryhmat})


# ---------- asetukset ja koodistot ----------


@rooli_vaaditaan("admin")
def asetukset(request):
    liike = request.liike
    if request.method == "POST":
        if request.POST.get("toiminto") == "liike":
            lomake = LiikeLomake(request.POST)
            if lomake.is_valid():
                liike.nimi = lomake.cleaned_data["nimi"]
                liike.y_tunnus = lomake.cleaned_data["y_tunnus"]
                liike.alv_prosentti = lomake.cleaned_data["alv_prosentti"]
                liike.save()
                messages.success(request, "Asetukset tallennettu.")
            else:
                messages.error(request, "Tarkista asetukset.")
        elif request.POST.get("toiminto") == "koodi":
            lomake = KoodiLomake(request.POST)
            if lomake.is_valid():
                koodi = lomake.save(commit=False)
                koodi.jarjestys = 99
                koodi.save()
            else:
                messages.error(request, "Koodi on jo olemassa tai tiedot puuttuvat.")
        return redirect("autot:asetukset")
    koodit = list(Koodi.objects.all())
    ryhmat = [(ryhma, nimi, [k for k in koodit if k.ryhma == ryhma]) for ryhma, nimi in Koodi.RYHMAT]
    return render(
        request,
        "autot/asetukset.html",
        {
            "liikelomake": LiikeLomake(
                initial={"nimi": liike.nimi, "y_tunnus": liike.y_tunnus, "alv_prosentti": liike.alv_prosentti}
            ),
            "koodiryhmat": ryhmat,
        },
    )
