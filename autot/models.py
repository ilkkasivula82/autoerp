"""AutoERP:n tietomalli.

Ydinajatus:
  Ajoneuvo = fyysinen auto (VIN, rekisteri, tekniset tiedot, varusteet).
  Kierto   = yksi kierros liikkeen kautta: tarjous -> osto -> ... -> myynti -> toimitus.
             Hinnat, tila, km, kunto, kuvat, kulut ja tehtävät kuuluvat kierrolle.
Kun sama auto palaa, sille avataan uusi kierto; vanhat kierrot ja niiden kate säilyvät.

Kaikki taulut perivät LiikkeenMalli-luokan: jokainen rivi kuuluu yhdelle liikkeelle.
Rahasummat ovat senttejä (BigIntegerField).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from liikkeet.rajaus import LiikeManager, LiikeQuerySet, LiikkeenMalli

from . import logiikka

KAYTTAJA = settings.AUTH_USER_MODEL


def raha(verbose_name, **kwargs):
    """Rahakenttä sentteinä."""
    kwargs.setdefault("null", True)
    kwargs.setdefault("blank", True)
    return models.BigIntegerField(verbose_name, help_text="senttiä", **kwargs)


def alv_kentta(verbose_name="ALV %", **kwargs):
    return models.DecimalField(verbose_name, max_digits=5, decimal_places=2, **kwargs)


class Tila(models.TextChoices):
    TARJOTTU = "tarjottu", "Tarjottu"
    OSTETTU = "ostettu", "Ostettu"
    TULOSSA = "tulossa", "Tulossa"
    KUNNOSTUKSESSA = "kunnostuksessa", "Kunnostuksessa"
    MYYNNISSA = "myynnissa", "Myynnissä"
    VARATTU = "varattu", "Varattu"
    MYYTY = "myyty", "Myyty"
    TOIMITETTU = "toimitettu", "Toimitettu"
    HYLATTY = "hylatty", "Hylätty"


assert [t.value for t in Tila] == logiikka.TILA_JARJESTYS


# ---------- Perusrekisterit ----------


class Yritys(LiikkeenMalli):
    """Toimittajat ja asiakkaat samassa taulussa: sama liike voi olla kumpaakin."""

    nimi = models.CharField("nimi", max_length=200)
    y_tunnus = models.CharField("Y-tunnus / henkilötunnus", max_length=20, blank=True)
    tyyppi = models.CharField("tyyppi", max_length=20, choices=logiikka.OSTOKANAVAT, default="autoliike")
    yhteyshenkilo = models.CharField("yhteyshenkilö", max_length=200, blank=True)
    puhelin = models.CharField("puhelin", max_length=50, blank=True)
    sahkoposti = models.EmailField("sähköposti", blank=True)
    lahiosoite = models.CharField("lähiosoite", max_length=200, blank=True)
    postinumero = models.CharField("postinumero", max_length=10, blank=True)
    postitoimipaikka = models.CharField("postitoimipaikka", max_length=100, blank=True)
    tilinumero = models.CharField("tilinumero (IBAN)", max_length=40, blank=True)
    alv_velvollinen = models.BooleanField("alv-velvollinen", default=False)
    huomiot = models.TextField("huomiot", blank=True)
    luotu = models.DateTimeField(auto_now_add=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "yritys"
        verbose_name_plural = "yritykset"
        ordering = ["nimi"]

    def __str__(self):
        return self.nimi


class Koodi(LiikkeenMalli):
    """Koodistot (käyttövoima, vaihteisto, korimalli). Koodit vastaavat Traficomin koodeja."""

    RYHMAT = [("kayttovoima", "Käyttövoima"), ("vaihteisto", "Vaihteisto"), ("korimalli", "Korimalli")]

    ryhma = models.CharField(max_length=20, choices=RYHMAT)
    koodi = models.CharField(max_length=10)
    nimi = models.CharField(max_length=100)
    jarjestys = models.IntegerField(default=0)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "koodi"
        verbose_name_plural = "koodit"
        ordering = ["ryhma", "jarjestys", "nimi"]
        constraints = [models.UniqueConstraint(fields=["liike", "ryhma", "koodi"], name="koodi_uniikki")]

    def __str__(self):
        return self.nimi


class Varustekategoria(LiikkeenMalli):
    nimi = models.CharField(max_length=100)
    jarjestys = models.IntegerField(default=0)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "varustekategoria"
        verbose_name_plural = "varustekategoriat"
        ordering = ["jarjestys", "nimi"]

    def __str__(self):
        return self.nimi


class Varuste(LiikkeenMalli):
    """Varustekatalogi. Käytössä olevaa varustetta ei poisteta, vaan piilotetaan (aktiivinen=False)."""

    kategoria = models.ForeignKey(Varustekategoria, on_delete=models.PROTECT, related_name="varusteet")
    nimi = models.CharField(max_length=200)
    aktiivinen = models.BooleanField(default=True)
    jarjestys = models.IntegerField(default=0)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "varuste"
        verbose_name_plural = "varusteet"
        ordering = ["jarjestys", "nimi"]

    def __str__(self):
        return self.nimi


# ---------- Ajoneuvo ja kierto ----------


class Ajoneuvo(LiikkeenMalli):
    """Fyysinen auto. Sama ajoneuvo voi kulkea liikkeen läpi monta kertaa.

    Tunnistus ensisijaisesti VIN:llä (rekisterinumero voi vaihtua, esim. erikoiskilpi).
    Varusteet kuuluvat ajoneuvolle, joten ne säilyvät uudelle kierrokselle.
    """

    rekisterinumero = models.CharField("rekisterinumero", max_length=20, blank=True)
    vin = models.CharField("VIN", max_length=17, blank=True)
    merkki = models.CharField("merkki", max_length=100)
    malli = models.CharField("malli", max_length=100)
    mallitarkenne = models.CharField("mallitarkenne", max_length=200, blank=True)
    vuosimalli = models.PositiveSmallIntegerField("vuosimalli", null=True, blank=True)
    ensirekisterointi = models.DateField("ensirekisteröinti", null=True, blank=True)
    kayttovoima = models.CharField("käyttövoima", max_length=10, blank=True)  # Koodi(ryhma=kayttovoima)
    vaihteisto = models.CharField("vaihteisto", max_length=10, blank=True)  # Koodi(ryhma=vaihteisto)
    korimalli = models.CharField("korimalli", max_length=10, blank=True)  # Koodi(ryhma=korimalli)
    vari = models.CharField("väri", max_length=50, blank=True)
    teho_kw = models.PositiveIntegerField("teho (kW)", null=True, blank=True)
    iskutilavuus = models.PositiveIntegerField("iskutilavuus (cm³)", null=True, blank=True)
    vetotapa = models.CharField(
        "vetotapa",
        max_length=20,
        blank=True,
        choices=[("etuveto", "Etuveto"), ("takaveto", "Takaveto"), ("neliveto", "Neliveto")],
    )
    ovet = models.PositiveSmallIntegerField("ovet", null=True, blank=True)
    istuimet = models.PositiveSmallIntegerField("istuimet", null=True, blank=True)
    varusteet = models.ManyToManyField(Varuste, through="AjoneuvonVaruste", related_name="ajoneuvot", blank=True)
    luotu = models.DateTimeField(auto_now_add=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "ajoneuvo"
        verbose_name_plural = "ajoneuvot"
        indexes = [
            models.Index(fields=["liike", "rekisterinumero"], name="ajoneuvo_rek_idx"),
            models.Index(fields=["liike", "vin"], name="ajoneuvo_vin_idx"),
        ]

    def __str__(self):
        return f"{self.merkki} {self.malli} {self.rekisterinumero}".strip()

    def save(self, *args, **kwargs):
        self.rekisterinumero = logiikka.normalisoi_rekisteri(self.rekisterinumero)
        self.vin = (self.vin or "").strip().upper()
        super().save(*args, **kwargs)


class AjoneuvonVaruste(LiikkeenMalli):
    ajoneuvo = models.ForeignKey(Ajoneuvo, on_delete=models.CASCADE)
    varuste = models.ForeignKey(Varuste, on_delete=models.CASCADE)

    class Meta(LiikkeenMalli.Meta):
        constraints = [models.UniqueConstraint(fields=["ajoneuvo", "varuste"], name="ajoneuvon_varuste_uniikki")]


def _kulusumma(kentta, ehto=None):
    kulut = Kulu.kaikki.filter(kierto=OuterRef("pk"))
    if ehto is not None:
        kulut = kulut.filter(ehto)
    return Coalesce(
        Subquery(kulut.values("kierto").annotate(s=Sum(kentta)).values("s")[:1]),
        Value(0),
        output_field=models.BigIntegerField(),
    )


@dataclass(frozen=True)
class Kulusummat:
    veroton: int
    jalki_veroton: int
    verollinen: int
    jalki_verollinen: int


class KiertoQuerySet(LiikeQuerySet):
    def kulusummilla(self):
        """Lisää kulusummat (senttiä, verottomina ja verollisina) ilman N+1-kyselyjä."""
        jalki = Q(pvm__gt=OuterRef("myyntipvm"))
        return self.annotate(
            kulut_yht=_kulusumma("summa_veroton"),
            jalkikulut_yht=_kulusumma("summa_veroton", jalki),
            kulut_verolliset_yht=_kulusumma("summa_verollinen"),
            jalkikulut_verolliset_yht=_kulusumma("summa_verollinen", jalki),
        )

    def varastossa(self):
        return self.filter(tila__in=logiikka.VARASTOTILAT)

    def avoimet(self):
        return self.exclude(tila__in=logiikka.PAATTYNEET)


class KiertoManager(LiikeManager.from_queryset(KiertoQuerySet)):
    pass


class Kierto(LiikkeenMalli):
    ajoneuvo = models.ForeignKey(Ajoneuvo, on_delete=models.PROTECT, related_name="kierrot")
    km = models.PositiveIntegerField("kilometrit", null=True, blank=True)
    tila = models.CharField("tila", max_length=20, choices=Tila.choices, default=Tila.TARJOTTU)
    tila_muutettu = models.DateTimeField(default=timezone.now)
    sijainti = models.CharField("sijainti", max_length=200, blank=True)

    # Tarjous ja osto
    toimittaja = models.ForeignKey(
        Yritys, verbose_name="toimittaja", on_delete=models.PROTECT, null=True, blank=True, related_name="ostot"
    )
    ostokanava = models.CharField("ostokanava", max_length=20, choices=logiikka.KIERRON_OSTOKANAVAT, blank=True)
    tarjottu_hinta = raha("pyydetty hinta")
    tarjottu_pvm = models.DateField("tarjottu", null=True, blank=True)
    hylkayksen_syy = models.CharField("hylkäyksen syy", max_length=500, blank=True)
    ostohinta = raha("ostohinta")  # marginaali: sellaisenaan, alv: veroton
    ostopvm = models.DateField("ostopäivä", null=True, blank=True)
    alv_kasittely = models.CharField(
        "verokohtelu", max_length=20, choices=logiikka.ALV_KASITTELYT, default="marginaali"
    )
    arvioitu_saapuminen = models.DateField("arvioitu saapuminen", null=True, blank=True)

    # Myynti
    pyyntihinta = raha("pyyntihinta")  # arvioitua katetta varten
    asiakas = models.ForeignKey(
        Yritys, verbose_name="ostaja", on_delete=models.PROTECT, null=True, blank=True, related_name="myynnit"
    )
    myyntihinta = raha("myyntihinta")  # marginaali: verollinen, alv: veroton
    myyntipvm = models.DateField("myyntipäivä", null=True, blank=True)
    laskunumero = models.CharField("laskunumero", max_length=50, blank=True)
    maksettu_pvm = models.DateField("maksettu", null=True, blank=True)
    toimitettu_pvm = models.DateField("toimitettu", null=True, blank=True)

    huomiot = models.TextField("huomiot", blank=True)
    luotu = models.DateTimeField(auto_now_add=True)
    luonut = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    objects = KiertoManager()

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "kierto"
        verbose_name_plural = "kierrot"
        indexes = [models.Index(fields=["liike", "tila"], name="kierto_liike_tila_idx")]
        constraints = [
            # Samalla ajoneuvolla voi olla vain yksi avoin kierros kerrallaan.
            models.UniqueConstraint(
                fields=["ajoneuvo"],
                condition=~Q(tila__in=logiikka.PAATTYNEET),
                name="yksi_avoin_kierto_per_ajoneuvo",
            ),
            # Varastossa tai myytynä olevalla autolla on aina ostohinta.
            models.CheckConstraint(
                condition=~Q(tila__in=logiikka.OSTETUT) | Q(ostohinta__isnull=False),
                name="ostetulla_autolla_ostohinta",
                violation_error_message="Varastossa olevalla autolla pitää olla ostohinta.",
            ),
            # Myydyllä autolla on aina myyntihinta.
            models.CheckConstraint(
                condition=~Q(tila__in=logiikka.MYYDYT) | Q(myyntihinta__isnull=False),
                name="myydylla_autolla_myyntihinta",
                violation_error_message="Myydyllä autolla pitää olla myyntihinta.",
            ),
        ]

    def __str__(self):
        return f"{self.ajoneuvo} (kierto {self.pk})"

    @property
    def paattynyt(self):
        return self.tila in logiikka.PAATTYNEET

    @property
    def tila_luokka(self):
        return logiikka.TILA_LUOKKA[self.tila]

    def kulusummat(self):
        """Kierron kulut senttiä. Käyttää annotaatioita, jos ne on haettu (kulusummilla)."""
        if hasattr(self, "kulut_yht"):
            return Kulusummat(
                self.kulut_yht, self.jalkikulut_yht, self.kulut_verolliset_yht, self.jalkikulut_verolliset_yht
            )
        kulut = list(self.kulut.values_list("summa_veroton", "summa_verollinen", "pvm"))
        jalki = [k for k in kulut if logiikka.on_jalkikulu(k[2], self.myyntipvm)]
        return Kulusummat(
            veroton=sum(k[0] for k in kulut),
            jalki_veroton=sum(k[0] for k in jalki),
            verollinen=sum(k[1] for k in kulut),
            jalki_verollinen=sum(k[1] for k in jalki),
        )

    def kate(self, alv_prosentti=None):
        """Toteutunut kate, tai arvio pyyntihinnalla, jos autoa ei ole myyty."""
        myynti, arvio = self.myyntihinta, False
        if myynti is None:
            myynti, arvio = self.pyyntihinta, True
        kulut = self.kulusummat()
        if alv_prosentti is None:
            alv_prosentti = self.liike.alv_prosentti
        return logiikka.laske_kate(
            ostohinta=self.ostohinta,
            myyntihinta=myynti,
            alv_kasittely=self.alv_kasittely,
            kulut_veroton=kulut.veroton,
            alv_prosentti=alv_prosentti,
            jalkikulut=kulut.jalki_veroton,
            kulut_verollinen=kulut.verollinen,
            jalkikulut_verollinen=kulut.jalki_verollinen,
            arvio=arvio,
        )

    def sidottu(self, alv_prosentti, brutto=False):
        """Autoon sidottu raha: ostohinta + kulut (brutto: ALV-kaupan osto ja kulut verollisina)."""
        kulut = self.kulusummat()
        osto = self.ostohinta or 0
        if not brutto:
            return osto + kulut.veroton
        if self.alv_kasittely == "alv":
            osto = logiikka.verolliseksi(osto, alv_prosentti)
        return osto + kulut.verollinen

    def kierroksia(self):
        return Kierto.objects.filter(ajoneuvo_id=self.ajoneuvo_id).count()


class Tilahistoria(LiikkeenMalli):
    """Jokainen tilasiirto. Tästä lasketaan vaihekohtaiset seisonta-ajat."""

    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="tilahistoria")
    vanha_tila = models.CharField(max_length=20, choices=Tila.choices, blank=True)
    uusi_tila = models.CharField(max_length=20, choices=Tila.choices)
    kayttaja = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    aika = models.DateTimeField(default=timezone.now)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "tilasiirto"
        verbose_name_plural = "tilahistoria"
        ordering = ["aika", "id"]


class Kulu(LiikkeenMalli):
    """Kierron kulu. Voidaan kirjata milloin tahansa, myös myynnin jälkeen (jälkikulu)."""

    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="kulut")
    tyyppi = models.CharField("tyyppi", max_length=30, choices=logiikka.KULUTYYPIT, default="muu")
    kuvaus = models.CharField("kuvaus", max_length=500, blank=True)
    summa_veroton = models.BigIntegerField("summa (alv 0)", help_text="senttiä")
    # Tallennetaan erikseen, jotta käyttäjän syöttämä verollinen summa säilyy sentilleen.
    summa_verollinen = models.BigIntegerField("summa (sis. alv)", help_text="senttiä")
    alv_prosentti = alv_kentta(default=Decimal("25.5"))
    pvm = models.DateField("päivämäärä", default=timezone.localdate)
    toimittaja = models.CharField("toimittaja / korjaamo", max_length=200, blank=True)
    luotu = models.DateTimeField(auto_now_add=True)
    luonut = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "kulu"
        verbose_name_plural = "kulut"
        ordering = ["pvm", "id"]

    @property
    def on_jalkikulu(self):
        return logiikka.on_jalkikulu(self.pvm, self.kierto.myyntipvm)

    def save(self, *args, **kwargs):
        if self.summa_verollinen is None:
            self.summa_verollinen = logiikka.verolliseksi(self.summa_veroton, self.alv_prosentti)
        super().save(*args, **kwargs)


class Kuntoraportti(LiikkeenMalli):
    """Tehdään kahdesti: myyjän ilmoittama (tarjous) ja oma tarkastus (saapuminen)."""

    VAIHEET = [("tarjous", "Tarjousvaihe"), ("saapuminen", "Saapumistarkastus")]
    TUULILASI = [("ehja", "Ehjä"), ("kiveniskuja", "Kiveniskuja"), ("vaihdettava", "Vaihdettava")]
    HUOLTOKIRJA = [("taysi", "Täysi"), ("osittainen", "Osittainen"), ("puuttuu", "Puuttuu")]
    ASTEIKKO = [(i, str(i)) for i in range(1, 6)]

    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="kuntoraportit")
    vaihe = models.CharField(max_length=20, choices=VAIHEET)
    tuulilasi = models.CharField("tuulilasi", max_length=20, choices=TUULILASI, blank=True)
    avaimet = models.PositiveSmallIntegerField("avaimet (kpl)", null=True, blank=True)
    maalipinta = models.PositiveSmallIntegerField("maalipinta (1–5)", choices=ASTEIKKO, null=True, blank=True)
    yleiskunto = models.PositiveSmallIntegerField("yleiskunto (1–5)", choices=ASTEIKKO, null=True, blank=True)
    sisatilat = models.PositiveSmallIntegerField("sisätilat (1–5)", choices=ASTEIKKO, null=True, blank=True)
    huoltokirja = models.CharField("huoltohistoria", max_length=20, choices=HUOLTOKIRJA, blank=True)
    huomiot = models.TextField("huomiot", blank=True)
    tehnyt = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    paivitetty = models.DateTimeField(auto_now=True)

    VERRATTAVAT = ["tuulilasi", "avaimet", "maalipinta", "yleiskunto", "sisatilat", "huoltokirja", "huomiot"]

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "kuntoraportti"
        verbose_name_plural = "kuntoraportit"
        constraints = [models.UniqueConstraint(fields=["kierto", "vaihe"], name="kuntoraportti_vaihe_uniikki")]


class Rengassarja(LiikkeenMalli):
    TYYPIT = [("kesa", "Kesä"), ("kitka", "Kitka"), ("nasta", "Nasta"), ("ymparivuotinen", "Ympärivuotinen")]
    VANTEET = [("pelti", "Pelti"), ("alumiini", "Alumiini")]
    SIJAINNIT = [("alla", "Autossa alla"), ("mukana", "Mukana"), ("varastossa", "Varastossa")]

    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="rengassarjat")
    tyyppi = models.CharField("tyyppi", max_length=20, choices=TYYPIT)
    koko = models.CharField("koko", max_length=30, blank=True)
    vanteet = models.CharField("vanteet", max_length=20, choices=VANTEET, blank=True)
    urasyvyys_mm = models.DecimalField("urasyvyys (mm)", max_digits=4, decimal_places=1, null=True, blank=True)
    kunto = models.PositiveSmallIntegerField("kunto (1–5)", choices=Kuntoraportti.ASTEIKKO, null=True, blank=True)
    sijainti = models.CharField("sijainti", max_length=20, choices=SIJAINNIT, default="alla")
    huomiot = models.CharField("huomiot", max_length=500, blank=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "rengassarja"
        verbose_name_plural = "rengassarjat"
        ordering = ["id"]


class Kuva(LiikkeenMalli):
    TYYPIT = [("ulko", "Ulkokuvat"), ("sisa", "Sisäkuvat"), ("vaurio", "Vauriot"), ("dokumentti", "Dokumentit")]

    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="kuvat")
    avain = models.CharField(max_length=300)  # tallennusavain (R2 / levy); pikkukuva: avain + _t
    tyyppi = models.CharField(max_length=20, choices=TYYPIT, default="ulko")
    jarjestys = models.IntegerField(default=0)
    paakuva = models.BooleanField(default=False)
    luotu = models.DateTimeField(auto_now_add=True)
    luonut = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "kuva"
        verbose_name_plural = "kuvat"
        ordering = ["-paakuva", "tyyppi", "jarjestys", "id"]


class Vaurio(LiikkeenMalli):
    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="vauriot")
    kohta = models.CharField("kohta", max_length=100)
    kuvaus = models.CharField("kuvaus", max_length=500, blank=True)
    arvioitu_korjaus = raha("arvioitu korjaus")
    kuva = models.ForeignKey(Kuva, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    korjattu = models.BooleanField(default=False)
    luotu = models.DateTimeField(auto_now_add=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "vaurio"
        verbose_name_plural = "vauriot"
        ordering = ["korjattu", "id"]


# ---------- Tehtävät ----------


class Tehtavapohja(LiikkeenMalli):
    """Kun auto siirtyy tilaan, pohjat luovat sille tehtävät automaattisesti."""

    tila = models.CharField(max_length=20, choices=Tila.choices)
    otsikko = models.CharField(max_length=200)
    rooli = models.CharField(max_length=20, blank=True)  # liikkeet.Rooli
    vastuu = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    erapaiva_pv = models.PositiveSmallIntegerField(null=True, blank=True)  # eräpäivä N päivää siirrosta
    jarjestys = models.IntegerField(default=0)
    aktiivinen = models.BooleanField(default=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "tehtäväpohja"
        verbose_name_plural = "tehtäväpohjat"
        ordering = ["jarjestys", "id"]


class Tehtava(LiikkeenMalli):
    kierto = models.ForeignKey(Kierto, on_delete=models.CASCADE, related_name="tehtavat")
    tila_vaihe = models.CharField(max_length=20, choices=Tila.choices, blank=True)  # vaihe, jossa syntyi
    otsikko = models.CharField("tehtävä", max_length=200)
    kuvaus = models.CharField("lisätiedot", max_length=1000, blank=True)
    vastuu = models.ForeignKey(
        KAYTTAJA, verbose_name="vastuuhenkilö", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    rooli = models.CharField(max_length=20, blank=True)
    erapaiva = models.DateField("eräpäivä", null=True, blank=True)
    tehty = models.BooleanField(default=False)
    tehty_aika = models.DateTimeField(null=True, blank=True)
    tehnyt = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    luotu = models.DateTimeField(auto_now_add=True)
    luonut = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "tehtävä"
        verbose_name_plural = "tehtävät"
        ordering = ["tehty", F("erapaiva").asc(nulls_last=True), "id"]
        indexes = [models.Index(fields=["liike", "vastuu", "tehty"], name="tehtava_vastuu_idx")]

    @property
    def myohassa(self):
        return not self.tehty and self.erapaiva is not None and self.erapaiva < timezone.localdate()


# ---------- Muutosloki ----------


class Muutosloki(LiikkeenMalli):
    """Kuka muutti mitä ja milloin (hinnat, tilat, kulut, ajoneuvotiedot)."""

    kayttaja = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kohde = models.CharField(max_length=20)  # 'kierto' tai 'ajoneuvo'
    kohde_id = models.BigIntegerField()
    kentta = models.CharField(max_length=100)
    vanha = models.TextField(blank=True)
    uusi = models.TextField(blank=True)
    aika = models.DateTimeField(default=timezone.now)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "muutos"
        verbose_name_plural = "muutosloki"
        ordering = ["-aika", "-id"]
        indexes = [models.Index(fields=["kohde", "kohde_id"], name="muutosloki_kohde_idx")]


# ---------- Sopimukset ----------


class Sopimus(LiikkeenMalli):
    """Osto- tai myyntisopimus. Vastapuolen tiedot tallennetaan sopimushetken mukaisina.

    Ostosopimus vie auton varastoon (ostohinta = sopimushinta). Myyntisopimus merkitsee
    auton myydyksi; sen vaihtoajoneuvot tulevat varastoon ostohinnalla = vaihtohinta.
    """

    TYYPIT = [("osto", "Ostosopimus"), ("myynti", "Myyntisopimus")]
    TUNNISTUSTAVAT = [
        ("ajokortti", "Ajokortti"),
        ("passi", "Passi"),
        ("henkilokortti", "Henkilökortti"),
        ("muu", "Muu"),
        ("ei", "Ei tarkastettu (yritys)"),
    ]
    MAKSUTAVAT = [
        ("tilisiirto", "Tilisiirto"),
        ("lasku", "Lasku"),
        ("kateinen", "Käteinen"),
        ("rahoitus", "Osamaksu / rahoitus"),
        ("muu", "Muu"),
    ]

    tyyppi = models.CharField(max_length=10, choices=TYYPIT)
    numero = models.PositiveIntegerField("sopimusnumero")
    pvm = models.DateField("päiväys", default=timezone.localdate)
    vastapuoli = models.ForeignKey(Yritys, on_delete=models.PROTECT, related_name="sopimukset")
    # Vastapuolen tiedot sopimushetkellä
    vp_nimi = models.CharField("nimi", max_length=200)
    vp_tunnus = models.CharField("Y-tunnus / henkilötunnus", max_length=20, blank=True)
    vp_lahiosoite = models.CharField("lähiosoite", max_length=200, blank=True)
    vp_postinumero = models.CharField("postinumero", max_length=10, blank=True)
    vp_postitoimipaikka = models.CharField("postitoimipaikka", max_length=100, blank=True)
    vp_puhelin = models.CharField("puhelin", max_length=50, blank=True)
    vp_sahkoposti = models.EmailField("sähköposti", blank=True)
    vp_tilinumero = models.CharField("tilinumero (IBAN)", max_length=40, blank=True)
    vp_alv_velvollinen = models.BooleanField("alv-velvollinen", default=False)
    # Toinen osapuoli (esim. Ostaja 2 / Myyjä 2 / muu haltija), valinnainen
    vp2_nimi = models.CharField("toisen osapuolen nimi", max_length=200, blank=True)
    vp2_tunnus = models.CharField("toisen osapuolen Y-tunnus / henkilötunnus", max_length=20, blank=True)
    vp2_osoite = models.CharField("toisen osapuolen osoite", max_length=300, blank=True)
    vp2_puhelin = models.CharField("toisen osapuolen puhelin", max_length=50, blank=True)
    vp2_sahkoposti = models.EmailField("toisen osapuolen sähköposti", blank=True)
    # Asiakkaan tunnistaminen (rahanpesulaki)
    tunnistus = models.CharField("henkilötiedot tarkastettu", max_length=20, choices=TUNNISTUSTAVAT, default="ei")
    pep = models.BooleanField("poliittisesti vaikutusvaltainen henkilö (PEP)", default=False)
    # Toimitus ja maksu
    toimitusaika = models.DateField("toimitusaika", null=True, blank=True)
    maksutapa = models.CharField("maksutapa", max_length=20, choices=MAKSUTAVAT, default="tilisiirto")
    # Myyntisopimuksen hinnan lisäerät ja maksun jakautuminen (senttiä)
    toimistokulut = models.BigIntegerField("toimistokulut", default=0, help_text="senttiä")
    etumaksu = models.BigIntegerField("etumaksu", default=0, help_text="senttiä")
    rahoitettava = models.BigIntegerField("rahoitettava osuus", default=0, help_text="senttiä")
    rahoitusyhtio = models.CharField("rahoitusyhtiö", max_length=200, blank=True)
    erapaiva = models.DateField("laskun eräpäivä", null=True, blank=True)
    lisatiedot = models.TextField("lisätiedot ja muut ehdot", blank=True)
    laatija = models.ForeignKey(KAYTTAJA, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    luotu = models.DateTimeField(auto_now_add=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "sopimus"
        verbose_name_plural = "sopimukset"
        ordering = ["-pvm", "-numero"]
        constraints = [models.UniqueConstraint(fields=["liike", "numero"], name="sopimusnumero_uniikki")]

    def __str__(self):
        return f"{self.get_tyyppi_display()} {self.numero}"

    def kohderivit(self):
        return [r for r in self.rivit.all() if r.rooli == "kohde"]

    def vaihtorivit(self):
        return [r for r in self.rivit.all() if r.rooli == "vaihto"]

    def summat(self):
        return logiikka.sopimuksen_summat(
            self.tyyppi,
            [(r.hinta, r.jaannosvelka) for r in self.kohderivit()],
            [(r.hinta, r.jaannosvelka) for r in self.vaihtorivit()],
            toimistokulut=self.toimistokulut,
            etumaksu=self.etumaksu,
            rahoitettava=self.rahoitettava,
        )


class SopimusRivi(LiikkeenMalli):
    """Sopimuksen ajoneuvo: kaupan kohde tai (myyntisopimuksessa) vaihtoajoneuvo."""

    ROOLIT = [("kohde", "Kaupan kohde"), ("vaihto", "Vaihtoajoneuvo")]
    ILMOITUS = [("ei", "Ei"), ("kylla", "Kyllä"), ("ei_tietoa", "Ei tietoa")]

    sopimus = models.ForeignKey(Sopimus, on_delete=models.CASCADE, related_name="rivit")
    kierto = models.ForeignKey(Kierto, on_delete=models.PROTECT, related_name="sopimusrivit")
    rooli = models.CharField(max_length=10, choices=ROOLIT, default="kohde")
    hinta = models.BigIntegerField("käteishinta", help_text="senttiä, sis. mahdollisen alv:n")
    jaannosvelka = models.BigIntegerField("jäännösvelka", default=0, help_text="senttiä")
    jaannosvelan_haltija = models.CharField("jäännösvelan haltija", max_length=200, blank=True)
    alv_kasittely = models.CharField("verotus", max_length=20, choices=logiikka.ALV_KASITTELYT, default="marginaali")
    # Ajoneuvon tiedot sopimushetkellä
    rekisterinumero = models.CharField(max_length=20, blank=True)
    vin = models.CharField(max_length=17, blank=True)
    merkki_malli = models.CharField(max_length=300)
    km = models.PositiveIntegerField("mittarilukema", null=True, blank=True)
    ensirekisterointi = models.DateField("ensirekisteröinti", null=True, blank=True)
    katsastettu = models.DateField("edellinen katsastus", null=True, blank=True)
    # Myyjän ilmoittamat tiedot (ostettavat ja vaihtoajoneuvot)
    kolaroitu = models.CharField("kolaroitu", max_length=10, choices=ILMOITUS, blank=True)
    maahantuotu = models.CharField("tuotu käytettynä maahan", max_length=10, choices=ILMOITUS, blank=True)
    mittari_vastaa = models.CharField("mittarilukema vastaa ajomäärää", max_length=10, choices=ILMOITUS, blank=True)
    rakennemuutoksia = models.CharField("rakenteellisia muutoksia", max_length=10, choices=ILMOITUS, blank=True)

    class Meta(LiikkeenMalli.Meta):
        verbose_name = "sopimusrivi"
        verbose_name_plural = "sopimusrivit"
        ordering = ["id"]
