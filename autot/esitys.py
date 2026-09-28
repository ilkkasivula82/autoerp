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


def hinnat(kierto, liike, brutto):
    """Kierron osto, kulut, myynti ja kate valitussa esitystavassa (liike: ALV-kanta ja menettely)."""
    kate = kierto.kate(liike)
    kulut = kierto.kulusummat()
    kulut_n = kulut.verollinen if brutto else kulut.veroton
    if kate:
        luvut = kate.luvut(brutto)
        return Hinnat(luvut.osto, luvut.kulut, luvut.myynti, luvut, kate.arvio)

    alv, menettely = liike.alv_prosentti, liike.marginaalimenettely
    osto = kierto.ostohinta
    myynti = kierto.myyntihinta if kierto.myyntihinta is not None else kierto.pyyntihinta
    arvio = kierto.myyntihinta is None

    def muunna(sentit, funktio):
        return funktio(sentit, alv) if sentit is not None else None

    if kierto.alv_kasittely == "alv":
        if brutto:
            osto, myynti = muunna(osto, logiikka.verolliseksi), muunna(myynti, logiikka.verolliseksi)
    elif not brutto:
        osto = logiikka.netto_osto(osto, "marginaali", alv, menettely)
        # Kuukausikohtaisessa menettelyssä myynti on laskennallisesti ilman veroa. Tavarakohtaisessa
        # veroton myynti riippuu ostohinnasta, eikä sitä voi laskea ilman sitä.
        myynti = muunna(myynti, logiikka.verottomaksi) if menettely == "kuukausi" else None
    return Hinnat(osto, kulut_n, myynti, None, arvio)
