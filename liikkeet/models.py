from decimal import Decimal

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from .rajaus import LiikeManager, VaaraLiike, aktiivinen_liike_id


class Liike(models.Model):
    """Autoliike eli vuokraaja. Kaikki muu data kuuluu jollekin liikkeelle."""

    nimi = models.CharField(max_length=200)
    y_tunnus = models.CharField(max_length=20, blank=True)
    alv_prosentti = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("25.5"))
    marginaalimenettely = models.CharField(
        "voittomarginaaliverotuksen menettely",
        max_length=10,
        choices=[("kuukausi", "Kuukausikohtainen"), ("tavara", "Tavarakohtainen")],
        default="kuukausi",
        help_text="Kuukausikohtaisessa tappiollinen kauppa pienentää kuukauden veroa.",
    )
    maksuaika_pv = models.PositiveSmallIntegerField("laskujen maksuaika (pv)", default=14)
    # Sopimuksille tulostettavat tiedot
    lahiosoite = models.CharField("lähiosoite", max_length=200, blank=True)
    postinumero = models.CharField("postinumero", max_length=10, blank=True)
    postitoimipaikka = models.CharField("postitoimipaikka", max_length=100, blank=True)
    puhelin = models.CharField("puhelin", max_length=50, blank=True)
    sahkoposti = models.EmailField("sähköposti", blank=True)
    tilinumero = models.CharField("tilinumero (IBAN)", max_length=40, blank=True)
    ostoehdot = models.TextField("ostosopimuksen ehdot", blank=True)
    myyntiehdot = models.TextField("myyntisopimuksen ehdot", blank=True)
    luotu = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "liike"
        verbose_name_plural = "liikkeet"

    def __str__(self):
        return self.nimi


class Rooli(models.TextChoices):
    ADMIN = "admin", "Ylläpitäjä"
    OSTO = "osto", "Osto"
    MYYNTI = "myynti", "Myynti"
    KUNNOSTUS = "kunnostus", "Kunnostus / piha"
    TALOUS = "talous", "Talous"


class KayttajaManager(BaseUserManager):
    """Rajaamaton manageri kirjautumista varten (käyttäjä haetaan ennen kuin liike tiedetään)."""

    use_in_migrations = True

    def create_user(self, sahkoposti, salasana=None, **kentat):
        if not sahkoposti:
            raise ValueError("Sähköposti on pakollinen.")
        if "liike" not in kentat and "liike_id" not in kentat:
            raise ValueError("Käyttäjä kuuluu aina liikkeelle.")
        kayttaja = self.model(sahkoposti=self.normalize_email(sahkoposti).lower(), **kentat)
        kayttaja.set_password(salasana)
        kayttaja.save(using=self._db)
        return kayttaja


class Kayttaja(AbstractBaseUser):
    liike = models.ForeignKey(Liike, on_delete=models.CASCADE, related_name="kayttajat")
    sahkoposti = models.EmailField(unique=True)
    nimi = models.CharField(max_length=200)
    rooli = models.CharField(max_length=20, choices=Rooli.choices, default=Rooli.MYYNTI)
    is_active = models.BooleanField("aktiivinen", default=True)
    # Näytetäänkö rahaluvut bruttona (sis. alv) vai nettona (ilman alv:tä)
    nayta_brutto = models.BooleanField("luvut bruttona", default=False)
    luotu = models.DateTimeField(auto_now_add=True)

    objects = KayttajaManager()
    liikkeen = LiikeManager()  # näkymissä: vain oman liikkeen käyttäjät

    USERNAME_FIELD = "sahkoposti"
    EMAIL_FIELD = "sahkoposti"
    REQUIRED_FIELDS = ["nimi"]

    class Meta:
        verbose_name = "käyttäjä"
        verbose_name_plural = "käyttäjät"
        constraints = [models.UniqueConstraint(Lower("sahkoposti"), name="kayttaja_sahkoposti_uniikki_pienet")]

    def __str__(self):
        return self.nimi

    @property
    def etunimi(self):
        return self.nimi.split(" ")[0]

    @property
    def on_admin(self):
        return self.rooli == Rooli.ADMIN

    def save(self, *args, **kwargs):
        self.sahkoposti = (self.sahkoposti or "").strip().lower()
        aktiivinen = aktiivinen_liike_id()
        if aktiivinen is not None:
            if self.liike_id is None:
                self.liike_id = aktiivinen
            elif self.liike_id != aktiivinen:
                raise VaaraLiike("Käyttäjä kuuluu toiselle liikkeelle.")
        super().save(*args, **kwargs)
