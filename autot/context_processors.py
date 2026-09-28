from liikkeet.models import Rooli

from . import logiikka
from .esitys import nayta_brutto


def valinnat(request):
    """Valintalistat kaikkiin pohjiin (koodi -> näyttönimi -muunnoksia varten) ja hintojen esitystapa."""
    brutto = nayta_brutto(request)
    return {
        "ROOLIT": Rooli.choices,
        "OSTOKANAVAT": logiikka.OSTOKANAVAT,
        "KULUTYYPIT": logiikka.KULUTYYPIT,
        "ALV_KASITTELYT": logiikka.ALV_KASITTELYT,
        "BRUTTO": brutto,
        "ALV_MERKINTA": "sis. alv" if brutto else "alv 0",
    }
