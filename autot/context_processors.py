from liikkeet.models import Rooli

from . import logiikka


def valinnat(request):
    """Valintalistat kaikkiin pohjiin (koodi -> näyttönimi -muunnoksia varten)."""
    return {
        "ROOLIT": Rooli.choices,
        "OSTOKANAVAT": logiikka.OSTOKANAVAT,
        "KULUTYYPIT": logiikka.KULUTYYPIT,
        "ALV_KASITTELYT": logiikka.ALV_KASITTELYT,
    }
