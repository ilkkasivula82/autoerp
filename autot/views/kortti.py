"""Auton kortti (yksi kierto) ja sen välilehtien toiminnot.

Välilehdet ladataan HTMX:llä (hx-get). Välilehtien lomakkeet lähetetään
hx-postilla, ja näkymä palauttaa päivitetyn välilehden. Ilman JavaScriptiä
sama lomake toimii tavallisena POSTina, jonka jälkeen ohjataan kortille.
"""

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import kuvat as kuvatallennus
from .. import logiikka, palvelut
from ..forms import (
    AJONEUVO_KENTAT,
    KAUPPA_KENTAT,
    AjoneuvoLomake,
    KauppaLomake,
    KuluLomake,
    KuntoLomake,
    KuvaLatausLomake,
    RengasLomake,
    SiirtoLomake,
    TehtavaLomake,
    VaurioLomake,
)
from ..models import (
    AjoneuvonVaruste,
    Kierto,
    Kulu,
    Kuntoraportti,
    Kuva,
    Muutosloki,
    Rengassarja,
    Tehtava,
    Varuste,
    Varustekategoria,
    Vaurio,
    Yritys,
)
from .autot import koodinimet
from .yhteiset import kortille, on_htmx

VALILEHDET = [
    ("yhteenveto", "Yhteenveto"),
    ("kauppa", "Osto ja myynti"),
    ("ajoneuvo", "Ajoneuvo"),
    ("kulut", "Kulut"),
    ("kunto", "Kunto"),
    ("kuvat", "Kuvat"),
    ("varusteet", "Varusteet"),
    ("tehtavat", "Tehtävät"),
    ("historia", "Historia"),
]
VALILEHTI_AVAIMET = {v for v, _ in VALILEHDET}

VAURIOKOHDAT = [
    "Etupuskuri",
    "Takapuskuri",
    "Konepelti",
    "Katto",
    "Takaluukku",
    "Vasen etuovi",
    "Oikea etuovi",
    "Vasen takaovi",
    "Oikea takaovi",
    "Vasen etulokasuoja",
    "Oikea etulokasuoja",
    "Vasen takalokasuoja",
    "Oikea takalokasuoja",
    "Kynnys",
    "Vanne",
    "Sisätilat",
    "Istuin",
    "Ohjauspyörä",
    "Mittaristo",
]


def hae_kierto(kid):
    """Kierto vain käyttäjän omasta liikkeestä (oletusmanageri rajaa), muuten 404."""
    return get_object_or_404(Kierto.objects.select_related("ajoneuvo", "toimittaja", "asiakas"), pk=kid)


# ---------- välilehtien sisältö ----------


def _laskurit(kierto):
    return {
        "kulut": kierto.kulut.count(),
        "kunto": kierto.vauriot.filter(korjattu=False).count(),
        "kuvat": kierto.kuvat.count(),
        "varusteet": AjoneuvonVaruste.objects.filter(ajoneuvo_id=kierto.ajoneuvo_id).count(),
        "tehtavat": kierto.tehtavat.filter(tehty=False).count(),
    }


def _yhteenveto(request, k):
    jarjestys = logiikka.TILA_JARJESTYS
    siirrot = []
    for s in logiikka.SIIRROT.get(k.tila, []):
        siirrot.append({"tila": s, "nimi": logiikka.TILA_NIMI[s], "taakse": logiikka.on_taaksepain(k.tila, s)})
    polku = []
    ohi = True
    for avain, nimi, _ in logiikka.TILAT:
        if avain == "hylatty":
            continue
        if avain == k.tila:
            ohi = False
            polku.append((nimi, "nykyinen"))
        else:
            polku.append((nimi, "ohitettu" if ohi else ""))
    avoimet = list(k.tehtavat.filter(tehty=False).select_related("vastuu"))
    return {
        "kate": k.kate(request.liike.alv_prosentti),
        "polku": polku,
        "siirrot": siirrot,
        "jarjestys": jarjestys,
        "avoimet_tehtavat": avoimet[:6],
        "avoimia_yhteensa": len(avoimet),
        "yritykset": list(Yritys.objects.all()),
    }


def _kauppa(request, k, lomake=None):
    return {"lomake": lomake or KauppaLomake(instance=k)}


def _ajoneuvo(request, k, lomake=None):
    return {"lomake": lomake or AjoneuvoLomake(instance=k.ajoneuvo)}


def _kulut(request, k, lomake=None):
    kulut = list(k.kulut.all())
    for r in kulut:
        r.jalki = logiikka.on_jalkikulu(r.pvm, k.myyntipvm)
    yht, jalki = k.kulusummat()
    return {
        "kulut": kulut,
        "kulut_yht": yht,
        "jalki": jalki,
        "lomake": lomake or KuluLomake(alv_oletus=request.liike.alv_prosentti, initial={"pvm": timezone.localdate()}),
    }


def _kuntolomakkeet(k, data=None, vaihe=None):
    raportit = {r.vaihe: r for r in k.kuntoraportit.all()}
    lomakkeet = {}
    for v, _ in Kuntoraportti.VAIHEET:
        lomake = KuntoLomake(data if v == vaihe else None, instance=raportit.get(v), prefix=v)
        for kentta in lomake.fields.values():
            kentta.widget.attrs["form"] = f"kunto-{v}"
        lomakkeet[v] = lomake
    return raportit, lomakkeet


def _kunto(request, k, kuntolomakkeet=None, rengaslomake=None, vauriolomake=None):
    raportit, lomakkeet = kuntolomakkeet or _kuntolomakkeet(k)
    t, s = raportit.get("tarjous"), raportit.get("saapuminen")
    rivit = []
    for nimi in Kuntoraportti.VERRATTAVAT:
        ta, sa = (getattr(t, nimi) if t else None), (getattr(s, nimi) if s else None)
        ero = ta not in (None, "") and sa not in (None, "") and ta != sa
        rivit.append(
            {
                "nimi": Kuntoraportti._meta.get_field(nimi).verbose_name.capitalize(),
                "tarjous": lomakkeet["tarjous"][nimi],
                "saapuminen": lomakkeet["saapuminen"][nimi],
                "ero": ero,
            }
        )
    return {
        "raportit": raportit,
        "kuntorivit": rivit,
        "renkaat": k.rengassarjat.all(),
        "rengaslomake": rengaslomake or RengasLomake(),
        "vauriot": k.vauriot.all(),
        "vauriolomake": vauriolomake or VaurioLomake(),
        "vauriokohdat": VAURIOKOHDAT,
    }


def _kuvat(request, k):
    kaikki = list(k.kuvat.all())
    ryhmat = []
    for tyyppi, otsikko in Kuva.TYYPIT:
        ryhma = sorted((x for x in kaikki if x.tyyppi == tyyppi), key=lambda x: (x.jarjestys, x.id))
        if ryhma:
            ryhmat.append((otsikko, ryhma))
    return {"kuvaryhmat": ryhmat, "kuvia": len(kaikki), "kuvatyypit": Kuva.TYYPIT, "latauslomake": KuvaLatausLomake()}


def _varusteet(request, k):
    valitut = set(AjoneuvonVaruste.objects.filter(ajoneuvo_id=k.ajoneuvo_id).values_list("varuste_id", flat=True))
    kategoriat = []
    varusteet = list(Varuste.objects.all())
    for kat in Varustekategoria.objects.all():
        lista = [v for v in varusteet if v.kategoria_id == kat.id and (v.aktiivinen or v.id in valitut)]
        if lista:
            kategoriat.append((kat, lista))
    muut = (
        Kierto.objects.select_related("ajoneuvo")
        .exclude(ajoneuvo_id=k.ajoneuvo_id)
        .filter(ajoneuvo__merkki__iexact=k.ajoneuvo.merkki)
        .order_by("-id")[:30]
    )
    return {"varustekategoriat": kategoriat, "valitut": valitut, "muut_kierrot": muut}


def _tehtavat(request, k, lomake=None):
    return {
        "tehtavat": k.tehtavat.select_related("vastuu", "tehnyt"),
        "lomake": lomake or TehtavaLomake(),
    }


def _historia(request, k):
    historia = list(k.tilahistoria.select_related("kayttaja"))
    loki = Muutosloki.objects.select_related("kayttaja").filter(
        Q(kohde="kierto", kohde_id=k.pk) | Q(kohde="ajoneuvo", kohde_id=k.ajoneuvo_id)
    )[:200]
    aiemmat = (
        Kierto.objects.select_related("toimittaja", "asiakas")
        .filter(ajoneuvo_id=k.ajoneuvo_id)
        .exclude(pk=k.pk)
        .order_by("-id")
    )
    return {"vaiheet": palvelut.vaihekestot(historia), "loki": loki, "aiemmat": aiemmat}


RAKENTAJAT = {
    "yhteenveto": _yhteenveto,
    "kauppa": _kauppa,
    "ajoneuvo": _ajoneuvo,
    "kulut": _kulut,
    "kunto": _kunto,
    "kuvat": _kuvat,
    "varusteet": _varusteet,
    "tehtavat": _tehtavat,
    "historia": _historia,
}


def _konteksti(request, k, valilehti, **lisat):
    konteksti = {
        "k": k,
        "a": k.ajoneuvo,
        "valilehti": valilehti,
        "valilehdet": VALILEHDET,
        "laskurit": _laskurit(k),
        "koodinimet": koodinimet(),
        "tanaan": timezone.localdate(),
        "valilehti_pohja": f"autot/valilehdet/{valilehti}.html",
    }
    konteksti.update(RAKENTAJAT[valilehti](request, k, **lisat))
    return konteksti


def nayta_valilehti(request, k, valilehti, status=200, **lisat):
    """HTMX: välilehden sisältö (+ välilehtipalkki ja ilmoitukset OOB). Muuten koko kortti."""
    konteksti = _konteksti(request, k, valilehti, **lisat)
    if on_htmx(request):
        return render(request, "autot/_valilehti_vastaus.html", konteksti, status=status)
    return render(request, "autot/kortti.html", konteksti, status=status)


def _vastaa(request, k, valilehti):
    """Onnistuneen tallennuksen jälkeen: HTMX-pyyntöön päivitetty välilehti, muuten uudelleenohjaus."""
    if on_htmx(request):
        k.refresh_from_db()
        return nayta_valilehti(request, k, valilehti)
    return kortille(k.pk, valilehti)


# ---------- kortti ja välilehdet ----------


@require_GET
def kortti(request, kid):
    k = hae_kierto(kid)
    valilehti = request.GET.get("v", "yhteenveto")
    if valilehti not in VALILEHTI_AVAIMET:
        valilehti = "yhteenveto"
    konteksti = _konteksti(request, k, valilehti)
    konteksti["paakuva"] = k.kuvat.filter(paakuva=True).first()
    konteksti["kierroksia"] = k.kierroksia()
    return render(request, "autot/kortti.html", konteksti)


@require_GET
def valilehti(request, kid, valilehti):
    k = hae_kierto(kid)
    if valilehti not in VALILEHTI_AVAIMET:
        raise Http404
    if not on_htmx(request):
        return kortille(k.pk, valilehti)
    return nayta_valilehti(request, k, valilehti)


# ---------- tilasiirto ja uusi kierros ----------


@require_POST
def vaihda_tila(request, kid):
    k = hae_kierto(kid)
    lomake = SiirtoLomake(request.POST)
    if not lomake.is_valid():
        messages.error(
            request,
            "Tarkista tilasiirron tiedot: "
            + "; ".join(f"{kentta}: {' '.join(v)}" for kentta, v in lomake.errors.items()),
        )
        return kortille(k.pk)
    d = lomake.cleaned_data
    uusi = d.pop("tila")
    try:
        n = palvelut.siirra_tila(k, uusi, request.user, **{a: b for a, b in d.items() if b not in (None, "")})
    except palvelut.SiirtoVirhe as e:
        messages.error(request, str(e))
        return kortille(k.pk)
    viesti = f"Tila: {logiikka.TILA_NIMI[uusi]}."
    if n:
        viesti += f" Luotiin {n} tehtävää."
    messages.success(request, viesti)
    return kortille(k.pk)


@require_POST
def palaa(request, kid):
    """Sama ajoneuvo tulee takaisin: avataan uusi kierros samalle ajoneuvolle."""
    k = hae_kierto(kid)
    avoin = palvelut.avoin_kierto(k.ajoneuvo)
    if avoin:
        messages.error(request, "Autolla on jo avoin kierros.")
        return kortille(avoin.pk)
    try:
        uusi = palvelut.avaa_kierto(k.ajoneuvo, request.user, alv_kasittely=k.alv_kasittely)
    except (palvelut.SiirtoVirhe, IntegrityError):
        messages.error(request, "Autolla on jo avoin kierros.")
        return kortille(k.pk)
    messages.success(
        request, "Uusi kierros avattu. Päivitä kilometrit, toimittaja ja kunto. Varusteet siirtyivät automaattisesti."
    )
    return kortille(uusi.pk, "kauppa")


# ---------- perustiedot ----------


@require_POST
def tallenna_ajoneuvo(request, kid):
    k = hae_kierto(kid)
    a = k.ajoneuvo
    vanhat = {f: getattr(a, f) for f in AJONEUVO_KENTAT}
    lomake = AjoneuvoLomake(request.POST, instance=a)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "ajoneuvo", status=422, lomake=lomake)
    with transaction.atomic():
        lomake.save()
        palvelut.kirjaa_muutokset(request.user, a, vanhat, AJONEUVO_KENTAT)
    messages.success(request, "Ajoneuvon tiedot tallennettu.")
    return _vastaa(request, k, "ajoneuvo")


@require_POST
def tallenna_kauppa(request, kid):
    k = hae_kierto(kid)
    vanhat = {f: getattr(k, f) for f in KAUPPA_KENTAT}
    lomake = KauppaLomake(request.POST, instance=k)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "kauppa", status=422, lomake=lomake)
    with transaction.atomic():
        lomake.save()
        palvelut.kirjaa_muutokset(request.user, k, vanhat, KAUPPA_KENTAT)
    messages.success(request, "Tiedot tallennettu.")
    return _vastaa(request, k, "kauppa")


# ---------- kulut ----------


@require_POST
def lisaa_kulu(request, kid):
    k = hae_kierto(kid)
    lomake = KuluLomake(request.POST, alv_oletus=request.liike.alv_prosentti)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "kulut", status=422, lomake=lomake)
    with transaction.atomic():
        kulu = lomake.save(commit=False)
        kulu.kierto = k
        kulu.luonut = request.user
        kulu.save()
        palvelut.kirjaa(
            request.user,
            "kierto",
            k.pk,
            "kulu lisätty",
            "",
            f"{kulu.get_tyyppi_display()}: {logiikka.euro(kulu.summa_veroton, True)} alv 0 %",
        )
    if logiikka.on_jalkikulu(kulu.pvm, k.myyntipvm):
        messages.success(request, "Jälkikulu kirjattu. Se pienentää auton lopullista katetta.")
    else:
        messages.success(request, "Kulu lisätty.")
    return _vastaa(request, k, "kulut")


@require_POST
def poista_kulu(request, kid, kulu_id):
    k = hae_kierto(kid)
    kulu = get_object_or_404(Kulu, pk=kulu_id, kierto=k)
    with transaction.atomic():
        palvelut.kirjaa(
            request.user,
            "kierto",
            k.pk,
            "kulu poistettu",
            f"{kulu.get_tyyppi_display()}: {logiikka.euro(kulu.summa_veroton, True)}",
            "",
        )
        kulu.delete()
    messages.success(request, "Kulu poistettu.")
    return _vastaa(request, k, "kulut")


# ---------- kunto ----------


@require_POST
def tallenna_kunto(request, kid, vaihe):
    k = hae_kierto(kid)
    if vaihe not in dict(Kuntoraportti.VAIHEET):
        raise Http404
    raportit, lomakkeet = _kuntolomakkeet(k, request.POST, vaihe)
    lomake = lomakkeet[vaihe]
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "kunto", status=422, kuntolomakkeet=(raportit, lomakkeet))
    raportti = lomake.save(commit=False)
    raportti.kierto = k
    raportti.vaihe = vaihe
    raportti.tehnyt = request.user
    raportti.save()
    messages.success(request, "Kuntotiedot tallennettu.")
    return _vastaa(request, k, "kunto")


@require_POST
def lisaa_rengas(request, kid):
    k = hae_kierto(kid)
    lomake = RengasLomake(request.POST)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "kunto", status=422, rengaslomake=lomake)
    rengas = lomake.save(commit=False)
    rengas.kierto = k
    rengas.save()
    return _vastaa(request, k, "kunto")


@require_POST
def poista_rengas(request, kid, rid):
    k = hae_kierto(kid)
    get_object_or_404(Rengassarja, pk=rid, kierto=k).delete()
    return _vastaa(request, k, "kunto")


@require_POST
def lisaa_vaurio(request, kid):
    k = hae_kierto(kid)
    lomake = VaurioLomake(request.POST, request.FILES)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "kunto", status=422, vauriolomake=lomake)
    with transaction.atomic():
        vaurio = lomake.save(commit=False)
        vaurio.kierto = k
        tiedosto = lomake.cleaned_data.get("kuvatiedosto")
        if tiedosto:
            try:
                avain = kuvatallennus.tallenna_kuva(tiedosto, request.liike.pk, k.pk)
            except kuvatallennus.KuvaVirhe as e:
                lomake.add_error("kuvatiedosto", str(e))
                return nayta_valilehti(request, k, "kunto", status=422, vauriolomake=lomake)
            vaurio.kuva = Kuva.objects.create(kierto=k, avain=avain, tyyppi="vaurio", luonut=request.user)
        vaurio.save()
    return _vastaa(request, k, "kunto")


@require_POST
def vaurio_korjattu(request, kid, vid):
    k = hae_kierto(kid)
    vaurio = get_object_or_404(Vaurio, pk=vid, kierto=k)
    vaurio.korjattu = not vaurio.korjattu
    vaurio.save(update_fields=["korjattu"])
    return _vastaa(request, k, "kunto")


# ---------- kuvat ----------


@require_POST
def lataa_kuvat(request, kid):
    k = hae_kierto(kid)
    tyyppi = request.POST.get("tyyppi")
    if tyyppi not in dict(Kuva.TYYPIT):
        tyyppi = "ulko"
    on_paakuva = k.kuvat.filter(paakuva=True).exists()
    seuraava = (k.kuvat.aggregate(m=Max("jarjestys"))["m"] or 0) + 1
    n = 0
    for tiedosto in request.FILES.getlist("kuvat"):
        try:
            avain = kuvatallennus.tallenna_kuva(tiedosto, request.liike.pk, k.pk)
        except kuvatallennus.KuvaVirhe:
            messages.error(request, f"Kuvaa {tiedosto.name} ei voitu lukea.")
            continue
        paa = not on_paakuva and n == 0 and tyyppi == "ulko"
        Kuva.objects.create(
            kierto=k, avain=avain, tyyppi=tyyppi, jarjestys=seuraava + n, paakuva=paa, luonut=request.user
        )
        n += 1
    if n:
        messages.success(request, f"{n} kuvaa lisätty.")
    return _vastaa(request, k, "kuvat")


def _hae_kuva(kuva_id):
    return get_object_or_404(Kuva, pk=kuva_id)


@require_GET
def nayta_kuva(request, kuva_id, koko="iso"):
    """Kuva vain oman liikkeen käyttäjälle. R2:ssa ohjataan lyhytikäiseen allekirjoitettuun osoitteeseen."""
    kuva = _hae_kuva(kuva_id)
    avain = kuvatallennus.pikkukuva_avain(kuva.avain) if koko == "pieni" else kuva.avain
    if kuvatallennus.paikallinen():
        try:
            vastaus = FileResponse(kuvatallennus.avaa(avain), content_type="image/jpeg")
        except FileNotFoundError as e:
            raise Http404 from e
        vastaus["Cache-Control"] = "private, max-age=3600"
        return vastaus
    return redirect(kuvatallennus.osoite(avain))


@require_POST
def aseta_paakuva(request, kuva_id):
    kuva = _hae_kuva(kuva_id)
    with transaction.atomic():
        Kuva.objects.filter(kierto_id=kuva.kierto_id).update(paakuva=False)
        Kuva.objects.filter(pk=kuva.pk).update(paakuva=True)
    return _vastaa(request, hae_kierto(kuva.kierto_id), "kuvat")


@require_POST
def vaihda_kuvatyyppi(request, kuva_id):
    kuva = _hae_kuva(kuva_id)
    tyyppi = request.POST.get("tyyppi")
    if tyyppi in dict(Kuva.TYYPIT):
        kuva.tyyppi = tyyppi
        kuva.save(update_fields=["tyyppi"])
    return _vastaa(request, hae_kierto(kuva.kierto_id), "kuvat")


@require_POST
def siirra_kuva(request, kuva_id, suunta):
    kuva = _hae_kuva(kuva_id)
    ids = list(
        Kuva.objects.filter(kierto_id=kuva.kierto_id, tyyppi=kuva.tyyppi)
        .order_by("jarjestys", "id")
        .values_list("id", flat=True)
    )
    i = ids.index(kuva.pk)
    j = i - 1 if suunta == "ylos" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        with transaction.atomic():
            for n, x in enumerate(ids):
                Kuva.objects.filter(pk=x).update(jarjestys=n + 1)
    return _vastaa(request, hae_kierto(kuva.kierto_id), "kuvat")


@require_POST
def poista_kuva(request, kuva_id):
    kuva = _hae_kuva(kuva_id)
    kierto_id = kuva.kierto_id
    avain = kuva.avain
    kuva.delete()  # vaurion kuva-viittaus nollautuu (SET_NULL)
    transaction.on_commit(lambda: kuvatallennus.poista(avain))
    return _vastaa(request, hae_kierto(kierto_id), "kuvat")


# ---------- varusteet ----------


@require_POST
def tallenna_varusteet(request, kid):
    k = hae_kierto(kid)
    pyydetyt = {int(x) for x in request.POST.getlist("varuste") if x.isdigit()}
    # Vain oman liikkeen varusteet kelpaavat
    valitut = set(Varuste.objects.filter(pk__in=pyydetyt).values_list("id", flat=True))
    with transaction.atomic():
        AjoneuvonVaruste.objects.filter(ajoneuvo_id=k.ajoneuvo_id).exclude(varuste_id__in=valitut).delete()
        olemassa = set(AjoneuvonVaruste.objects.filter(ajoneuvo_id=k.ajoneuvo_id).values_list("varuste_id", flat=True))
        for v in valitut - olemassa:
            AjoneuvonVaruste.objects.create(ajoneuvo_id=k.ajoneuvo_id, varuste_id=v)
    messages.success(request, f"Varusteet tallennettu ({len(valitut)} kpl).")
    return _vastaa(request, k, "varusteet")


@require_POST
def kopioi_varusteet(request, kid):
    k = hae_kierto(kid)
    lahde_id = request.POST.get("lahde", "")
    lahde = hae_kierto(int(lahde_id) if lahde_id.isdigit() else 0)
    olemassa = set(AjoneuvonVaruste.objects.filter(ajoneuvo_id=k.ajoneuvo_id).values_list("varuste_id", flat=True))
    lahteen = AjoneuvonVaruste.objects.filter(ajoneuvo_id=lahde.ajoneuvo_id).values_list("varuste_id", flat=True)
    with transaction.atomic():
        for v in set(lahteen) - olemassa:
            AjoneuvonVaruste.objects.create(ajoneuvo_id=k.ajoneuvo_id, varuste_id=v)
    messages.success(request, f"Varusteet kopioitu autosta {lahde.ajoneuvo}. Tarkista ja tallenna.")
    return _vastaa(request, k, "varusteet")


# ---------- tehtävät kortilla ----------


@require_POST
def lisaa_tehtava(request, kid):
    k = hae_kierto(kid)
    lomake = TehtavaLomake(request.POST)
    if not lomake.is_valid():
        return nayta_valilehti(request, k, "tehtavat", status=422, lomake=lomake)
    tehtava = lomake.save(commit=False)
    tehtava.kierto = k
    tehtava.tila_vaihe = k.tila
    tehtava.luonut = request.user
    tehtava.save()
    return _vastaa(request, k, "tehtavat")


@require_POST
def poista_tehtava(request, kid, tid):
    k = hae_kierto(kid)
    get_object_or_404(Tehtava, pk=tid, kierto=k).delete()
    return _vastaa(request, k, "tehtavat")
