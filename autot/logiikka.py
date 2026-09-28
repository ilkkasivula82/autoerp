"""Liiketoimintalogiikka: tilat, rahamuunnokset ja katelaskenta.

Tässä moduulissa ei ole Django-riippuvuuksia, joten se on helppo testata.
Kaikki rahasummat ovat SENTTEJÄ kokonaislukuina. Pyöristys tehdään
Decimal-aritmetiikalla puoli ylöspäin (ROUND_HALF_UP), ei liukuluvuilla.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# ---------- Tilat ----------

# (koodi, näyttönimi, CSS-luokka). Järjestys = auton tavallinen elinkaari.
TILAT = [
    ("tarjottu", "Tarjottu", "t-tarjottu"),
    ("ostettu", "Ostettu", "t-ostettu"),
    ("tulossa", "Tulossa", "t-tulossa"),
    ("kunnostuksessa", "Kunnostuksessa", "t-kunnostus"),
    ("myynnissa", "Myynnissä", "t-myynnissa"),
    ("varattu", "Varattu", "t-varattu"),
    ("myyty", "Myyty", "t-myyty"),
    ("toimitettu", "Toimitettu", "t-toimitettu"),
    ("hylatty", "Hylätty", "t-hylatty"),
]
TILA_NIMI = {k: n for k, n, _ in TILAT}
TILA_LUOKKA = {k: c for k, _, c in TILAT}
TILA_JARJESTYS = [k for k, _, _ in TILAT]

# Sallitut siirrot. Taaksepäin pääsee edelliseen vaiheeseen (virheiden korjaus).
SIIRROT = {
    "tarjottu": ["ostettu", "hylatty"],
    "hylatty": ["tarjottu"],
    "ostettu": ["tulossa", "kunnostuksessa", "myynnissa", "tarjottu"],
    "tulossa": ["kunnostuksessa", "myynnissa", "ostettu"],
    "kunnostuksessa": ["myynnissa", "tulossa"],
    "myynnissa": ["varattu", "myyty", "kunnostuksessa"],
    "varattu": ["myyty", "myynnissa"],
    "myyty": ["toimitettu", "varattu", "myynnissa"],
    "toimitettu": ["myyty"],
}

# Auto on omassa varastossa ja sitoo pääomaa
VARASTOTILAT = ["ostettu", "tulossa", "kunnostuksessa", "myynnissa", "varattu"]
# Kierros on päättynyt: autolle voi avata uuden kierroksen
PAATTYNEET = ["myyty", "toimitettu", "hylatty"]


def siirto_sallittu(vanha, uusi):
    return uusi in SIIRROT.get(vanha, [])


def on_taaksepain(vanha, uusi):
    """Onko siirto paluu aiempaan vaiheeseen (virheen korjaus)?"""
    if uusi == "hylatty" or vanha == "hylatty":
        return False
    return TILA_JARJESTYS.index(uusi) < TILA_JARJESTYS.index(vanha)


# ---------- Valintalistat ----------

OSTOKANAVAT = [
    ("rahoitusyhtio", "Rahoitusyhtiö"),
    ("huutokauppa", "Huutokauppa"),
    ("autoliike", "Autoliike"),
    ("yksityinen", "Yksityinen"),
    ("muu", "Muu"),
]

KULUTYYPIT = [
    ("huutokauppamaksu", "Huutokauppamaksu"),
    ("kuljetus", "Kuljetus"),
    ("huolto", "Huolto"),
    ("kunnostus", "Kunnostus / korjaus"),
    ("pesu", "Pesu / preppaus"),
    ("katsastus", "Katsastus"),
    ("renkaat", "Renkaat"),
    ("rekisterointi", "Rekisteröinti / verot"),
    ("reklamaatio", "Reklamaatio / jälkikorjaus"),
    ("hyvitys", "Hyvitys ostajalle"),
    ("muu", "Muu"),
]

ALV_KASITTELYT = [
    ("marginaali", "Marginaaliverotus"),
    ("alv", "Normaali ALV"),
]

# ---------- Raha ----------


def euro_senteiksi(teksti):
    """Käyttäjän syöttämä euromäärä sentteinä.

    '12 500,50' -> 1250050, '12500.5' -> 1250050, '1.250,50' -> 125050,
    '' / None -> None. Virheellinen syöte nostaa ValueErrorin.
    """
    if teksti is None:
        return None
    t = str(teksti).strip().replace(" ", "").replace(" ", "").replace(" ", "").replace("€", "")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "")  # tuhaterotin
    t = t.replace(",", ".")
    try:
        arvo = Decimal(t)
    except InvalidOperation as e:
        raise ValueError(f"Virheellinen summa: {teksti}") from e
    if not arvo.is_finite():
        raise ValueError(f"Virheellinen summa: {teksti}")
    return int((arvo * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ryhmittele(kokonaisluku):
    return f"{kokonaisluku:,}".replace(",", " ")


def euro(sentit, desimaalit=False):
    """1250050 -> '12 500 €' tai desimaaleilla '12 500,50 €'."""
    if sentit is None:
        return "–"
    etumerkki = "-" if sentit < 0 else ""
    sentit = abs(int(sentit))
    if desimaalit:
        return f"{etumerkki}{_ryhmittele(sentit // 100)},{sentit % 100:02d} €"
    eurot = int((Decimal(sentit) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{etumerkki}{_ryhmittele(eurot)} €"


def euro_input(sentit):
    """Lomakkeen kenttään: 12500 tai 12500,50."""
    if sentit is None:
        return ""
    etumerkki = "-" if sentit < 0 else ""
    sentit = abs(int(sentit))
    if sentit % 100 == 0:
        return f"{etumerkki}{sentit // 100}"
    return f"{etumerkki}{sentit // 100},{sentit % 100:02d}"


def pyorista_sentit(arvo):
    return int(Decimal(arvo).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def verottomaksi(verollinen_sentit, alv_prosentti):
    """Verollinen summa -> veroton (senttiä)."""
    r = Decimal(str(alv_prosentti))
    return pyorista_sentit(Decimal(verollinen_sentit) * 100 / (100 + r))


def verolliseksi(veroton_sentit, alv_prosentti):
    r = Decimal(str(alv_prosentti))
    return pyorista_sentit(Decimal(veroton_sentit) * (100 + r) / 100)


# ---------- Katelaskenta ----------


@dataclass(frozen=True)
class Luvut:
    """Katelaskelman luvut yhdessä esitystavassa: netto (ilman alv:tä) tai brutto (sis. alv).

    Brutto:
      - myynti: verollinen myyntihinta (marginaalikaupassa myyntihinta sellaisenaan)
      - osto: ALV-kaupassa verollinen ostohinta, marginaalikaupassa ostohinta (siinä ei ole vähennettävää veroa)
      - kulut: jokainen kulu omalla ALV-kannallaan verollisena
      - kate = myynti - osto - kulut, eli kate sisältäen alv:n
    Netto:
      - myynti ilman veroa (marginaalikaupassa myyntihinta - marginaalivero), osto ja kulut verottomina
    """

    brutto: bool
    myynti: int
    osto: int
    kulut: int  # kaikki kulut, myös jälkikulut
    jalkikulut: int
    kate: int  # lopullinen kate

    @property
    def kulut_ennen_myyntia(self):
        return self.kulut - self.jalkikulut

    @property
    def kate_myyntihetki(self):
        return self.kate + self.jalkikulut

    @property
    def kate_prosentti(self):
        if not self.myynti:
            return None
        return Decimal(self.kate * 100) / Decimal(self.myynti)


@dataclass(frozen=True)
class Kate:
    arvio: bool  # laskettu pyyntihinnalla, ei toteutuneella myynnillä
    alv_kasittely: str
    myynti: int  # marginaali: verollinen, alv: veroton
    verollinen_myynti: int
    marginaalivero: int
    nettomyynti: int  # myynti ilman veroa
    osto: int  # marginaali: sellaisenaan, alv: veroton
    verollinen_osto: int
    kulut: int  # kaikki kulut verottomina, myös jälkikulut
    jalkikulut: int  # näistä myyntipäivän jälkeen kirjatut
    verolliset_kulut: int
    verolliset_jalkikulut: int
    kate: int  # lopullinen kate (netto)

    @property
    def hankintameno(self):
        return self.osto + self.kulut

    @property
    def kulut_ennen_myyntia(self):
        return self.kulut - self.jalkikulut

    @property
    def kate_myyntihetki(self):
        """Kate ennen jälkikuluja (reklamaatiot ym.)."""
        return self.kate + self.jalkikulut

    @property
    def kate_prosentti(self):
        if not self.nettomyynti:
            return None
        return Decimal(self.kate * 100) / Decimal(self.nettomyynti)

    def luvut(self, brutto=False):
        """Luvut valitussa esitystavassa (ks. Luvut)."""
        if not brutto:
            return Luvut(False, self.nettomyynti, self.osto, self.kulut, self.jalkikulut, self.kate)
        myynti, osto, kulut = self.verollinen_myynti, self.verollinen_osto, self.verolliset_kulut
        return Luvut(True, myynti, osto, kulut, self.verolliset_jalkikulut, myynti - osto - kulut)

    @property
    def netto(self):
        return self.luvut(False)

    @property
    def brutto(self):
        return self.luvut(True)


def laske_kate(
    *,
    ostohinta,
    myyntihinta,
    alv_kasittely,
    kulut_veroton,
    alv_prosentti,
    jalkikulut=0,
    kulut_verollinen=None,
    jalkikulut_verollinen=None,
    arvio=False,
):
    """Laskee yhden kierroksen katteen.

    Marginaaliverotus (käytetyn tavaran erityisjärjestely):
      - osto- ja myyntihinta sellaisenaan (myyntihinta sisältää veron)
      - vero = (myyntihinta - ostohinta) * r / (100 + r), jos voittomarginaali > 0;
        tappiollisesta kaupasta veroa ei makseta
      - kunnostuskulut eivät pienennä veron laskentaperustetta, mutta niiden
        ALV vähennetään, joten katteessa ne ovat verottomina
      - kate = myyntihinta - vero - ostohinta - kulut (alv 0)
      Vero on auton oma osuus. Kuukausikohtaisessa menettelyssä ilmoitettava vero
      lasketaan kuukauden kaikista marginaaliostoista ja -myynneistä yhteensä.
    Normaali ALV:
      - osto- ja myyntihinta sekä kulut verottomina
      - kate = myynti - osto - kulut

    kulut_verollinen / jalkikulut_verollinen: kulut verollisina (kukin omalla
    ALV-kannallaan) brutto-esitystä varten. Jos puuttuu, lasketaan kannalla alv_prosentti.

    Rahat sentteinä, alv_prosentti esim. Decimal('25.5').
    Palauttaa Kate-olion tai None, jos osto- tai myyntihinta puuttuu.
    """
    if ostohinta is None or myyntihinta is None:
        return None
    r = Decimal(str(alv_prosentti or 0))
    kulut = int(kulut_veroton or 0)
    jalkikulut = int(jalkikulut or 0)
    if kulut_verollinen is None:
        kulut_verollinen = verolliseksi(kulut, r)
    if jalkikulut_verollinen is None:
        jalkikulut_verollinen = verolliseksi(jalkikulut, r)

    if alv_kasittely == "alv":
        vero = 0
        nettomyynti = myyntihinta
        verollinen = verolliseksi(myyntihinta, r)
        verollinen_osto = verolliseksi(ostohinta, r)
    elif alv_kasittely == "marginaali":
        voittomarginaali = myyntihinta - ostohinta
        vero = pyorista_sentit(Decimal(voittomarginaali) * r / (100 + r)) if voittomarginaali > 0 else 0
        nettomyynti = myyntihinta - vero
        verollinen = myyntihinta
        verollinen_osto = ostohinta
    else:
        raise ValueError(f"Tuntematon ALV-käsittely: {alv_kasittely}")

    return Kate(
        arvio=arvio,
        alv_kasittely=alv_kasittely,
        myynti=myyntihinta,
        verollinen_myynti=verollinen,
        marginaalivero=vero,
        nettomyynti=nettomyynti,
        osto=ostohinta,
        verollinen_osto=verollinen_osto,
        kulut=kulut,
        jalkikulut=jalkikulut,
        verolliset_kulut=int(kulut_verollinen),
        verolliset_jalkikulut=int(jalkikulut_verollinen),
        kate=nettomyynti - ostohinta - kulut,
    )


def on_jalkikulu(kulun_pvm, myyntipvm):
    """Kulu on jälkikulu, jos se on kirjattu myyntipäivän jälkeen."""
    return bool(myyntipvm and kulun_pvm and kulun_pvm > myyntipvm)


# ---------- Rekisterinumero ----------


def normalisoi_rekisteri(teksti):
    """'abc123' / 'ABC 123' / 'abc-123' -> 'ABC-123'. Muut muodot isoilla kirjaimilla sellaisenaan."""
    import re

    v = (teksti or "").strip().upper().replace(" ", "")
    m = re.fullmatch(r"([A-ZÅÄÖ]{1,3})-?(\d{1,3})", v)
    if m:
        v = f"{m.group(1)}-{m.group(2)}"
    return v


def rekisteri_hakuavain(teksti):
    """Vertailuavain: 'ABC-123' ja 'abc123' ovat sama."""
    return normalisoi_rekisteri(teksti).replace("-", "")


# ---------- Päivämäärät ----------


def paivia_valissa(alku, loppu=None):
    """Päiviä alkupäivästä loppupäivään (oletus tänään). None, jos alkua ei ole."""
    if alku is None:
        return None
    if hasattr(alku, "date") and callable(alku.date):
        alku = alku.date()
    loppu = loppu or date.today()
    if hasattr(loppu, "date") and callable(loppu.date):
        loppu = loppu.date()
    return (loppu - alku).days
