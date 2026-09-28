"""Osto- ja myyntisopimukset: lomakkeet, sopimuslista ja tulostettava sopimus."""

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from .. import logiikka, palvelut
from .. import sopimukset as sopimuspalvelu
from ..forms import KohdeLomake, SopimusLomake, VaihtoFormset
from ..models import Myyntitarjous, Sopimus, Yritys
from .kortti import hae_kierto
from .yhteiset import kortille


def _verollisena(sentit, alv_kasittely, alv_prosentti):
    """Kierron hinta sopimuksen käteishinnaksi (ALV-kaupassa verollinen)."""
    if sentit is None:
        return None
    return logiikka.verolliseksi(sentit, alv_prosentti) if alv_kasittely == "alv" else sentit


def _alkuarvot(k, tyyppi, alv):
    if tyyppi == "osto":
        yritys = k.toimittaja
        hinta = k.ostohinta if k.ostohinta is not None else k.tarjottu_hinta
        # Tarjottu hinta on myyjän pyytämä käteishinta sellaisenaan
        hinta = _verollisena(hinta, k.alv_kasittely, alv) if k.ostohinta is not None else hinta
    else:
        yritys = k.asiakas
        hinta = k.myyntihinta if k.myyntihinta is not None else k.pyyntihinta
        hinta = _verollisena(hinta, k.alv_kasittely, alv)
    sopimus = {"valittu": yritys, "maksutapa": "tilisiirto"}
    if yritys:
        sopimus.update(sopimuspalvelu.vastapuolen_tiedot(yritys))
    kohde = {"hinta": hinta, "alv_kasittely": k.alv_kasittely, "km": k.km}
    return sopimus, kohde


def _tarjouksen_alkuarvot(tarjous, alku_sopimus, alku_kohde):
    """Myyntisopimus tarjouksesta: asiakas, hinta, toimistokulut ja vaihtoauto tarjoukselta."""
    if tarjous.asiakas:
        alku_sopimus.update({"valittu": tarjous.asiakas, **sopimuspalvelu.vastapuolen_tiedot(tarjous.asiakas)})
    else:
        alku_sopimus.update(
            {
                "valittu": None,
                "vp_nimi": tarjous.vp_nimi,
                "vp_puhelin": tarjous.vp_puhelin,
                "vp_sahkoposti": tarjous.vp_sahkoposti,
            }
        )
    alku_sopimus["toimistokulut"] = tarjous.toimistokulut
    alku_kohde["hinta"] = tarjous.hinta
    if not tarjous.on_vaihtoauto:
        return []
    return [
        {
            "rekisterinumero": tarjous.vaihto_rekisterinumero,
            "merkki": tarjous.vaihto_merkki,
            "malli": tarjous.vaihto_malli,
            "km": tarjous.vaihto_km,
            "hinta": tarjous.vaihto_hinta,
            "jaannosvelka": tarjous.vaihto_jaannosvelka or None,
        }
    ]


def _sopimuslomake(request, kid, tyyppi):
    k = hae_kierto(kid)
    alv = request.liike.alv_prosentti
    sallittu = (
        sopimuspalvelu.voi_tehda_ostosopimuksen(k) if tyyppi == "osto" else sopimuspalvelu.voi_tehda_myyntisopimuksen(k)
    )
    if not sallittu:
        messages.error(
            request,
            "Autolle ei voi tehdä ostosopimusta." if tyyppi == "osto" else "Vain varastossa olevan auton voi myydä.",
        )
        return kortille(k.pk)

    alku_sopimus, alku_kohde = _alkuarvot(k, tyyppi, alv)
    tarjous, alku_vaihdot = None, []
    tid = (request.POST if request.method == "POST" else request.GET).get("tarjous", "")
    if tyyppi == "myynti" and tid.isdigit():
        tarjous = get_object_or_404(Myyntitarjous, pk=int(tid), kierto=k, tila="avoin")
        alku_vaihdot = _tarjouksen_alkuarvot(tarjous, alku_sopimus, alku_kohde)
    data = request.POST if request.method == "POST" else None
    lomake = SopimusLomake(data, initial=alku_sopimus, prefix="s")
    kohde = KohdeLomake(data, initial=alku_kohde, prefix="kohde")
    vaihdot = VaihtoFormset(data, initial=alku_vaihdot, prefix="vaihto") if tyyppi == "myynti" else None

    if request.method == "POST":
        kelpaa = lomake.is_valid() & kohde.is_valid() & (vaihdot.is_valid() if vaihdot is not None else True)
        if kelpaa:
            tiedot = dict(lomake.cleaned_data)
            yritys = tiedot.pop("valittu")
            try:
                if tyyppi == "osto":
                    sopimus = sopimuspalvelu.tee_ostosopimus(
                        k, request.user, yritys=yritys, tiedot=tiedot, kohde=kohde.cleaned_data, alv_prosentti=alv
                    )
                else:
                    vaihtorivit = [f.cleaned_data for f in vaihdot if f.has_changed()]
                    sopimus = sopimuspalvelu.tee_myyntisopimus(
                        k,
                        request.user,
                        yritys=yritys,
                        tiedot=tiedot,
                        kohde=kohde.cleaned_data,
                        vaihdot=vaihtorivit,
                        alv_prosentti=alv,
                        tarjous=tarjous,
                    )
            except (palvelut.SiirtoVirhe, IntegrityError) as e:
                messages.error(request, str(e) if isinstance(e, palvelut.SiirtoVirhe) else "Tallennus epäonnistui.")
            else:
                messages.success(request, f"{sopimus.get_tyyppi_display()} nro {sopimus.numero} tallennettu.")
                return redirect("autot:sopimus", sid=sopimus.pk)
        status = 422
    else:
        status = 200
    return render(
        request,
        "autot/sopimus_lomake.html",
        {
            "k": k,
            "a": k.ajoneuvo,
            "tyyppi": tyyppi,
            "otsikko": "Ostosopimus" if tyyppi == "osto" else "Myyntisopimus",
            "lomake": lomake,
            "kohde": kohde,
            "vaihdot": vaihdot,
            "tarjous": tarjous,
        },
        status=status,
    )


def ostosopimus(request, kid):
    return _sopimuslomake(request, kid, "osto")


def myyntisopimus(request, kid):
    return _sopimuslomake(request, kid, "myynti")


@require_GET
def vastapuoli(request):
    """HTMX: valitun yrityksen tiedot sopimuslomakkeen vastapuolikenttiin."""
    valittu = request.GET.get("s-valittu", "")
    alku = {}
    if valittu.isdigit():
        yritys = get_object_or_404(Yritys, pk=int(valittu))
        alku = {"valittu": yritys, **sopimuspalvelu.vastapuolen_tiedot(yritys)}
    return render(request, "autot/_vastapuoli.html", {"lomake": SopimusLomake(initial=alku, prefix="s")})


@require_GET
def sopimus(request, sid):
    """Sopimus tulostettavana asiakirjana (selaimen tulostus / PDF)."""
    s = get_object_or_404(Sopimus.objects.select_related("vastapuoli", "laatija"), pk=sid)
    alv = request.liike.alv_prosentti
    rivit = list(s.rivit.select_related("kierto"))
    for r in rivit:
        r.alv_osuus = logiikka.alv_osuus(r.hinta, r.alv_kasittely, alv)
        # Myydyn auton rivillä näytetään ALV:n osuus, muilla jäännösvelka (ALV-kaupassa molemmat)
        r.nayta_alv = r.alv_kasittely == "alv" or (s.tyyppi == "myynti" and r.rooli == "kohde")
        r.maksetaan = r.hinta - r.jaannosvelka  # vaihtoauto: vaihtohinnan ja jäännösvelan erotus
    summat = s.summat()
    return render(
        request,
        "autot/sopimus.html",
        {
            "s": s,
            "liike": request.liike,
            "kohteet": [r for r in rivit if r.rooli == "kohde"],
            "vaihdot": [r for r in rivit if r.rooli == "vaihto"],
            "summat": summat,
            "palautettava": -summat.maksettava,
            "ilmoitetut_kohde": s.tyyppi == "osto",
            "ehdot": request.liike.ostoehdot if s.tyyppi == "osto" else request.liike.myyntiehdot,
        },
    )


@require_GET
def lista(request):
    tyyppi = request.GET.get("tyyppi")
    qs = Sopimus.objects.select_related("vastapuoli").prefetch_related("rivit")
    if tyyppi in dict(Sopimus.TYYPIT):
        qs = qs.filter(tyyppi=tyyppi)
    rivit = list(qs[:500])
    for s in rivit:
        s.summat_ = s.summat()
    return render(request, "autot/sopimukset.html", {"rivit": rivit, "tyyppi": tyyppi, "TYYPIT": Sopimus.TYYPIT})
