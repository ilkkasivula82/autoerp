"""Rahalukujen esitys käyttäjän valinnan mukaan: netto (ilman alv:tä) tai brutto (sis. alv).

Tallennetut hinnat ovat kuten ne kaupassa syntyvät (marginaalikaupassa myyntihinta
verollisena, ALV-kaupassa verottomana). Näkymät muuntavat ne tämän moduulin kautta.
"""

from dataclasses import dataclass

from . import logiikka


def nayta_brutto(request):
    kayttaja = getattr(request, "user", None)
    return bool(kayttaja and kayttaja.is_authenticated and kayttaja.nayta_brutto)


@dataclass(frozen=True)
class Hinnat:
    osto: int | None
    kulut: int
    myynti: int | None  # toteutunut myynti tai pyyntihinta (arvio)
    luvut: logiikka.Luvut | None  # katelaskelma, jos osto- ja myynti/pyyntihinta tiedossa
    arvio: bool


def hinnat(kierto, alv_prosentti, brutto):
    """Kierron osto, kulut, myynti ja kate valitussa esitystavassa."""
    kate = kierto.kate(alv_prosentti)
    kulut = kierto.kulusummat()
    kulut_n = kulut.verollinen if brutto else kulut.veroton
    if kate:
        luvut = kate.luvut(brutto)
        return Hinnat(luvut.osto, luvut.kulut, luvut.myynti, luvut, kate.arvio)

    osto = kierto.ostohinta
    myynti = kierto.myyntihinta if kierto.myyntihinta is not None else kierto.pyyntihinta
    arvio = kierto.myyntihinta is None
    if kierto.alv_kasittely == "alv":
        if brutto:
            osto = logiikka.verolliseksi(osto, alv_prosentti) if osto is not None else None
            myynti = logiikka.verolliseksi(myynti, alv_prosentti) if myynti is not None else None
    elif not brutto:
        # Marginaalikaupan veroton myynti riippuu ostohinnasta; ilman sitä ei voida laskea.
        myynti = None
    return Hinnat(osto, kulut_n, myynti, None, arvio)
