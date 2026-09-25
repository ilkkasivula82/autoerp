from . import rajaus


class LiikeMiddleware:
    """Aktivoi kirjautuneen käyttäjän liikkeen pyynnön ajaksi.

    Kirjautumaton pyyntö ei aktivoi mitään liikettä, joten liikekohtaisen datan
    kysely nostaa silloin poikkeuksen (suljettu oletuksena).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.liike = None
        kayttaja = getattr(request, "user", None)
        if kayttaja is None or not kayttaja.is_authenticated:
            return self.get_response(request)
        request.liike = kayttaja.liike
        tunniste = rajaus.aktivoi(kayttaja.liike_id)
        try:
            return self.get_response(request)
        finally:
            rajaus.palauta(tunniste)
