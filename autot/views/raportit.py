"""Raportit: kate kuukausittain / ostokanavittain / toimittajittain / ostajittain,
varaston ikä ja myyntisaatavat."""

from datetime import date

from django.shortcuts import render
from django.utils import timezone

from .. import logiikka
from ..models import Kierto


def _pvm(teksti, oletus):
    try:
        return date.fromisoformat(teksti) if teksti else oletus
    except ValueError:
        return oletus


def _ryhmittele(rivit, avain):
    tulos = {}
    for r in rivit:
        nimi = avain(r) or "–"
        o = tulos.setdefault(nimi, {"nimi": nimi, "n": 0, "myynti": 0, "kate": 0, "jalki": 0, "paivat": []})
        o["n"] += 1
        o["myynti"] += r.kate_.nettomyynti
        o["kate"] += r.kate_.kate
        o["jalki"] += r.kate_.jalkikulut
        if r.kiertoaika is not None:
            o["paivat"].append(r.kiertoaika)
    for o in tulos.values():
        o["ka_kate"] = o["kate"] // o["n"] if o["n"] else 0
        o["ka_paivat"] = round(sum(o["paivat"]) / len(o["paivat"])) if o["paivat"] else None
        paivia = sum(o["paivat"])
        o["kate_per_pv"] = o["kate"] // paivia if paivia else None
    return sorted(tulos.values(), key=lambda o: str(o["nimi"]))


def index(request):
    tanaan = timezone.localdate()
    alku = _pvm(request.GET.get("alku"), date(tanaan.year, 1, 1))
    loppu = _pvm(request.GET.get("loppu"), tanaan)
    alv = request.liike.alv_prosentti

    rivit = list(
        Kierto.objects.filter(myyntihinta__isnull=False, myyntipvm__gte=alku, myyntipvm__lte=loppu)
        .select_related("ajoneuvo", "toimittaja", "asiakas")
        .kulusummilla()
        .order_by("myyntipvm", "id")
    )
    for r in rivit:
        r.kate_ = r.kate(alv)
        r.kiertoaika = (r.myyntipvm - r.ostopvm).days if r.ostopvm else None
    kanavat = dict(logiikka.OSTOKANAVAT)

    varasto = list(Kierto.objects.varastossa().kulusummilla())
    ika = []
    for nimi, a, b in [("0–30 pv", 0, 30), ("31–60 pv", 31, 60), ("61–90 pv", 61, 90), ("yli 90 pv", 91, 10**6)]:
        ryhma = [r for r in varasto if a <= (logiikka.paivia_valissa(r.ostopvm, tanaan) or 0) <= b]
        ika.append({"nimi": nimi, "n": len(ryhma), "sidottu": sum((r.ostohinta or 0) + r.kulut_yht for r in ryhma)})

    saatavat = list(
        Kierto.objects.filter(myyntihinta__isnull=False, maksettu_pvm__isnull=True)
        .select_related("ajoneuvo", "asiakas")
        .order_by("myyntipvm")
    )
    for s in saatavat:
        s.ika = logiikka.paivia_valissa(s.myyntipvm, tanaan)
        s.verollinen = logiikka.verolliseksi(s.myyntihinta, alv) if s.alv_kasittely == "alv" else s.myyntihinta

    yht = _ryhmittele(rivit, lambda r: "yht")
    return render(
        request,
        "autot/raportit.html",
        {
            "alku": alku,
            "loppu": loppu,
            "rivit": list(reversed(rivit)),
            "yht": yht[0] if yht else None,
            "taulut": [
                ("Kuukausittain", "Kuukausi", _ryhmittele(rivit, lambda r: r.myyntipvm.strftime("%Y-%m")), True),
                ("Ostokanavittain", "Kanava", _ryhmittele(rivit, lambda r: kanavat.get(r.ostokanava)), False),
                (
                    "Toimittajittain",
                    "Toimittaja",
                    _ryhmittele(rivit, lambda r: r.toimittaja and r.toimittaja.nimi),
                    False,
                ),
                ("Ostajittain", "Ostaja", _ryhmittele(rivit, lambda r: r.asiakas and r.asiakas.nimi), True),
            ],
            "ika": ika,
            "saatavat": saatavat,
        },
    )
