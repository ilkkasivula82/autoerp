"""Myyntitarjoukset: tarjouksen teko, tulostettava tarjous ja hylkäys.

Hyväksytystä tarjouksesta tehdään myyntisopimus sopimuslomakkeella (?tarjous=<id>).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import logiikka, palvelut
from .. import sopimukset as sopimuspalvelu
from ..forms import MyyntitarjousLomake
from ..models import Myyntitarjous
from .kortti import hae_kierto
from .yhteiset import kortille

VOIMASSA_PV = 7


def uusi(request, kid):
    k = hae_kierto(kid)
    if not sopimuspalvelu.voi_tehda_myyntisopimuksen(k):
        messages.error(request, "Tarjouksen voi tehdä vain varastossa olevasta autosta.")
        return kortille(k.pk, "tarjoukset")
    alv = request.liike.alv_prosentti
    hinta = k.pyyntihinta
    if hinta is not None and k.alv_kasittely == "alv":
        hinta = logiikka.verolliseksi(hinta, alv)
    alku = {"hinta": hinta, "voimassa": timezone.localdate() + timezone.timedelta(days=VOIMASSA_PV)}
    if request.method == "POST":
        lomake = MyyntitarjousLomake(request.POST, initial=alku)
        if lomake.is_valid():
            try:
                tarjous = sopimuspalvelu.tee_myyntitarjous(k, request.user, dict(lomake.cleaned_data))
            except palvelut.SiirtoVirhe as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f"Myyntitarjous nro {tarjous.numero} tallennettu.")
                return redirect("autot:tarjous", tid=tarjous.pk)
        status = 422
    else:
        lomake = MyyntitarjousLomake(initial=alku)
        status = 200
    return render(request, "autot/tarjous_lomake.html", {"k": k, "a": k.ajoneuvo, "lomake": lomake}, status=status)


@require_GET
def tarjous(request, tid):
    """Tarjous tulostettavana asiakirjana."""
    t = get_object_or_404(Myyntitarjous.objects.select_related("kierto__ajoneuvo", "laatija", "sopimus"), pk=tid)
    summat = t.summat()
    return render(
        request,
        "autot/tarjous.html",
        {
            "t": t,
            "k": t.kierto,
            "a": t.kierto.ajoneuvo,
            "liike": request.liike,
            "summat": summat,
            "sahkoposti": _sahkoposti(t, summat, request.liike),
            "voi_myyda": t.tila == "avoin" and sopimuspalvelu.voi_tehda_myyntisopimuksen(t.kierto),
        },
    )


def _sahkoposti(t, summat, liike):
    """Tarjous sähköpostin otsikoksi ja tekstiksi (mailto-linkki)."""
    a = t.kierto.ajoneuvo
    auto = " ".join(x for x in [a.merkki, a.malli, a.rekisterinumero] if x)
    rivit = [f"Hei {t.vp_nimi},", "", f"kiitos kiinnostuksestasi. Tarjoamme sinulle ajoneuvon {auto}:"]
    rivit.append(f"Käteishinta {logiikka.euro(summat.kateishinta, True)}")
    if t.on_vaihtoauto:
        vaihto = " ".join(x for x in [t.vaihto_merkki, t.vaihto_malli, t.vaihto_rekisterinumero] if x)
        rivit.append(f"Vaihtoajoneuvo {vaihto}: hyvitys {logiikka.euro(summat.vaihtohyvitys, True)}")
        if summat.jaannosvelka:
            rivit.append(f"Jäännösvelka (maksamme rahoittajalle) {logiikka.euro(summat.jaannosvelka, True)}")
        rivit.append(f"Maksettavaa {logiikka.euro(summat.maksettava, True)}")
    if t.voimassa:
        rivit.append(f"Tarjous on voimassa {t.voimassa:%-d.%-m.%Y} asti.")
    if t.lisatiedot:
        rivit += ["", t.lisatiedot]
    rivit += ["", "Ystävällisin terveisin", t.laatija.nimi if t.laatija else "", liike.nimi, liike.puhelin]
    return {"otsikko": f"Tarjous {t.numero}: {auto}", "teksti": "\n".join(r for r in rivit if r is not None)}


@require_POST
def hylkaa(request, tid):
    t = get_object_or_404(Myyntitarjous, pk=tid)
    if t.tila == "avoin":
        t.tila = "hylatty"
        t.save(update_fields=["tila"])
        palvelut.kirjaa(request.user, "kierto", t.kierto_id, "myyntitarjous", f"nro {t.numero}", "hylätty")
        messages.success(request, f"Tarjous nro {t.numero} merkitty hylätyksi.")
    return kortille(t.kierto_id, "tarjoukset")
