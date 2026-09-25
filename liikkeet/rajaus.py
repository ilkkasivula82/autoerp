"""Monivuokraajuus: jokainen liiketoimintarivi kuuluu yhdelle liikkeelle.

Periaate on "suljettu oletuksena" (fail closed):

* Pyynnön ajaksi aktivoidaan kirjautuneen käyttäjän liike (``LiikeMiddleware``).
* ``LiikkeenMalli``-mallien oletusmanageri ``objects`` rajaa jokaisen kyselyn
  aktiiviseen liikkeeseen. Jos liikettä ei ole aktivoitu, kysely on tyhjä ja
  sen suorittaminen nostaa ``LiikeEiAktiivinen``-poikkeuksen sen sijaan, että
  palauttaisi kaikkien liikkeiden rivit.
* Tallennus tarkistaa, että rivi ja kaikki sen viittaamat rivit kuuluvat
  aktiiviseen liikkeeseen.
* Rajaamaton manageri ``kaikki`` on olemassa vain hallintakomennoille ja
  testeille. Sitä ei käytetä näkymissä.

Koska lomakkeiden valintakentät (ModelChoiceField) käyttävät oletusmanageria,
toisen liikkeen rivin id:tä ei voi syöttää lomakkeen kautta.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import PermissionDenied
from django.db import models

_aktiivinen = ContextVar("aktiivinen_liike_id", default=None)


class LiikeEiAktiivinen(RuntimeError):
    """Liikekohtaista dataa yritettiin käsitellä ilman aktiivista liikettä."""


class VaaraLiike(PermissionDenied):
    """Rivi tai sen viittaama rivi kuuluu toiselle liikkeelle."""


def aktiivinen_liike_id():
    return _aktiivinen.get()


def aktivoi(liike_id):
    """Asettaa aktiivisen liikkeen. Palauttaa tunnisteen, jolla se palautetaan."""
    return _aktiivinen.set(liike_id)


def palauta(tunniste):
    _aktiivinen.reset(tunniste)


@contextmanager
def liike_kaytossa(liike):
    """Hallintakomennoissa ja testeissä: ``with liike_kaytossa(liike): ...``"""
    tunniste = aktivoi(liike.pk if hasattr(liike, "pk") else liike)
    try:
        yield
    finally:
        palauta(tunniste)


def _vaadi_liike():
    liike_id = _aktiivinen.get()
    if liike_id is None:
        raise LiikeEiAktiivinen(
            "Liikettä ei ole aktivoitu. Näkymissä LiikeMiddleware aktivoi sen; komennoissa käytä liike_kaytossa(liike)."
        )
    return liike_id


class LiikeQuerySet(models.QuerySet):
    """Kysely, joka tietää, luotiinko se ilman aktiivista liikettä.

    Ilman liikettä luotu kysely on tyhjä (``none()``), ja sen suorittaminen
    nostaa ``LiikeEiAktiivinen``-poikkeuksen. Tyhjä kysely on tarpeen, koska
    Django luo osan kyselyistä jo moduulia ladattaessa (esim. ModelFormin
    valintakentät); niiden kyselyt asetetaan uudelleen lomakkeen __init__:ssä.
    Alikyselynä (``filter(x__in=qs)``) tyhjä kysely ei palauta mitään.
    """

    _liike_puuttuu = False

    def _clone(self):
        klooni = super()._clone()
        klooni._liike_puuttuu = self._liike_puuttuu
        return klooni

    def _tarkista(self):
        if self._liike_puuttuu:
            _vaadi_liike()  # nostaa poikkeuksen, jos liike puuttuu edelleen
            raise LiikeEiAktiivinen("Kysely luotiin ennen kuin liike aktivoitiin. Luo kysely uudelleen pyynnön aikana.")

    def _fetch_all(self):
        self._tarkista()
        super()._fetch_all()

    def iterator(self, *args, **kwargs):
        self._tarkista()
        return super().iterator(*args, **kwargs)

    def count(self):
        self._tarkista()
        return super().count()

    def exists(self):
        self._tarkista()
        return super().exists()

    def aggregate(self, *args, **kwargs):
        self._tarkista()
        return super().aggregate(*args, **kwargs)

    def update(self, **kwargs):
        self._tarkista()
        return super().update(**kwargs)

    def delete(self):
        self._tarkista()
        return super().delete()


class LiikeManager(models.Manager.from_queryset(LiikeQuerySet)):
    """Oletusmanageri: näkyvät vain aktiivisen liikkeen rivit."""

    def get_queryset(self):
        qs = super().get_queryset()
        liike_id = _aktiivinen.get()
        if liike_id is None:
            qs = qs.none()
            qs._liike_puuttuu = True
            return qs
        return qs.filter(liike_id=liike_id)


class LiikkeenMalli(models.Model):
    """Abstrakti perusmalli kaikille liikekohtaisille tauluille."""

    liike = models.ForeignKey("liikkeet.Liike", on_delete=models.CASCADE, related_name="+", editable=False)

    objects = LiikeManager()
    kaikki = models.Manager()  # rajaamaton: vain komennot ja testit

    class Meta:
        abstract = True
        base_manager_name = "kaikki"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        liike_id = _aktiivinen.get()
        if liike_id is not None:
            if self.liike_id is None:
                self.liike_id = liike_id
            elif self.liike_id != liike_id:
                raise VaaraLiike("Rivi kuuluu toiselle liikkeelle.")
        elif self.liike_id is None:
            raise LiikeEiAktiivinen("Rivin liike puuttuu, eikä liikettä ole aktivoitu.")
        tarkista_viittaukset(self)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        liike_id = _aktiivinen.get()
        if liike_id is not None and self.liike_id != liike_id:
            raise VaaraLiike("Rivi kuuluu toiselle liikkeelle.")
        return super().delete(*args, **kwargs)


def tarkista_viittaukset(olio):
    """Varmistaa, että jokainen vierasavain osoittaa saman liikkeen riviin."""
    for kentta in olio._meta.concrete_fields:
        if not kentta.is_relation or kentta.name == "liike":
            continue
        kohde = kentta.related_model
        if not any(f.name == "liike" for f in kohde._meta.concrete_fields):
            continue
        arvo = getattr(olio, kentta.attname)
        if arvo is None:
            continue
        if kentta.is_cached(olio):
            kohteen_liike = getattr(olio, kentta.name).liike_id
        else:
            kohteen_liike = kohde._base_manager.filter(pk=arvo).values_list("liike_id", flat=True).first()
        if kohteen_liike != olio.liike_id:
            raise VaaraLiike(f"{kentta.name} viittaa toisen liikkeen riviin.")
