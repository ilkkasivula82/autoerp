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
    "ostettu": ["tulossa", "kunnostuksessa", "myynnissa", "myyty", "tarjottu"],
    "tulossa": ["kunnostuksessa", "myynnissa", "myyty", "ostettu"],
    "kunnostuksessa": ["myynnissa", "myyty", "tulossa"],
    "myynnissa": ["varattu", "myyty", "kunnostuksessa"],
    "varattu": ["myyty", "myynnissa"],
    "myyty": ["toimitettu", "varattu", "myynnissa"],
    "toimitettu": ["myyty"],
}

# Auto on omassa varastossa ja sitoo pääomaa
VARASTOTILAT = ["ostettu", "tulossa", "kunnostuksessa", "myynnissa", "varattu"]
# Kierros on päättynyt: autolle voi avata uuden kierroksen
PAATTYNEET = ["myyty", "toimitettu", "hylatty"]
# Tilat, joissa autolla on aina ostohinta (tietokannan rajoite) ja myyntihinta
OSTETUT = VARASTOTILAT + ["myyty", "toimitettu"]
MYYDYT = ["myyty", "toimitettu"]


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

# Kierron ostokanava: yrityksen tyypit + myynnin yhteydessä vaihdossa tullut auto
KIERRON_OSTOKANAVAT = OSTOKANAVAT + [("vaihto", "Vaihtoauto")]

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
      - osto: ALV-kaupassa verollinen ostohinta, marginaalikaupassa ostohinta sellaisenaan
      - kulut: jokainen kulu omalla ALV-kannallaan verollisena
      - kate = myynti - osto - kulut, eli kate sisältäen alv:n
    Netto:
      - ALV-kauppa: myynti, osto ja kulut verottomina
      - marginaalikauppa: myynti ja osto laskennallisesti ilman veroa (hinta * 100 / (100 + r)),
        jolloin myynti - osto = voittomarginaali ilman veroa; kulut verottomina
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
    nettoosto: int  # osto ilman veroa (marginaali: laskennallinen)
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
            return Luvut(False, self.nettomyynti, self.nettoosto, self.kulut, self.jalkikulut, self.kate)
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
    menettely="kuukausi",
):
    """Laskee yhden kierroksen katteen.

    Marginaaliverotus (käytetyn tavaran erityisjärjestely):
      - osto- ja myyntihinta sellaisenaan (myyntihinta sisältää veron)
      - auton vero-osuus = (myyntihinta - ostohinta) * r / (100 + r)
      - menettely="kuukausi" (kuukausikohtainen, oletus): kuukauden kaikki marginaaliostot ja
        -myynnit lasketaan yhteen, joten tappiollinen kauppa pienentää kuukauden veroa:
        auton vero-osuus voi olla negatiivinen
      - menettely="tavara" (tavarakohtainen): tappiollisesta kaupasta veroa ei makseta (vero 0)
      - kunnostuskulut eivät pienennä veron laskentaperustetta, mutta niiden
        ALV vähennetään, joten katteessa ne ovat verottomina
      - kate = myyntihinta - vero - ostohinta - kulut (alv 0)
      - nettoluvut: myynti ja osto * 100 / (100 + r), jolloin nettomyynti - nettoosto = myynti - vero - osto
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

    if menettely not in ("kuukausi", "tavara"):
        raise ValueError(f"Tuntematon marginaaliverotuksen menettely: {menettely}")

    if alv_kasittely == "alv":
        vero = 0
        nettomyynti, nettoosto = myyntihinta, ostohinta
        verollinen = verolliseksi(myyntihinta, r)
        verollinen_osto = verolliseksi(ostohinta, r)
    elif alv_kasittely == "marginaali":
        voittomarginaali = myyntihinta - ostohinta
        if voittomarginaali > 0 or menettely == "kuukausi":
            vero = pyorista_sentit(Decimal(voittomarginaali) * r / (100 + r))
            nettomyynti = verottomaksi(myyntihinta, r)
            # Johdetaan myynnistä, jotta nettomyynti - nettoosto = myynti - vero - osto sentilleen
            nettoosto = nettomyynti - (myyntihinta - vero - ostohinta)
        else:
            # Tavarakohtainen, tappiollinen kauppa: ei veroa, luvut sellaisenaan
            vero = 0
            nettomyynti, nettoosto = myyntihinta, ostohinta
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
        nettoosto=nettoosto,
        verollinen_osto=verollinen_osto,
        kulut=kulut,
        jalkikulut=jalkikulut,
        verolliset_kulut=int(kulut_verollinen),
        verolliset_jalkikulut=int(jalkikulut_verollinen),
        kate=myyntihinta - vero - ostohinta - kulut,
    )


def netto_osto(ostohinta, alv_kasittely, alv_prosentti, menettely="kuukausi"):
    """Myymättömän auton ostohinta nettona. Marginaaliauto kuukausikohtaisessa menettelyssä
    laskennallisesti ilman veroa, tavarakohtaisessa sellaisenaan (tappio ei vähennä veroa)."""
    if ostohinta is None:
        return None
    if alv_kasittely == "marginaali" and menettely == "kuukausi":
        return verottomaksi(ostohinta, alv_prosentti)
    return ostohinta


# ---------- Sopimukset ----------


@dataclass(frozen=True)
class SopimuksenSummat:
    """Osto- tai myyntisopimuksen rahavirrat senttiä.

    Ostosopimus (liike ostaa):
      käteishinta = kohteiden hinnat; jäännösvelka maksetaan rahoittajalle;
      myyjälle maksetaan käteishinta - jäännösvelka.
    Myyntisopimus (liike myy, voi ottaa vaihtoajoneuvoja):
      käteishinta = kohteiden kauppahinnat + toimistokulut
      vaihtoajoneuvon hinta hyvitetään, ja liike maksaa sen jäännösvelan, joten
      maksettava = käteishinta - vaihtoautojen hinnat + vaihtoautojen jäännösvelat
      toimituksen yhteydessä maksetaan = maksettava - etumaksu - rahoitettava osuus.
      Negatiivinen maksettava = liike maksaa asiakkaalle.
    """

    kauppahinta: int  # kohteiden hinnat
    toimistokulut: int
    kateishinta: int  # kauppahinta + toimistokulut
    jaannosvelka: int  # ostossa kohteen, myynnissä vaihtoautojen jäännösvelat
    vaihtohyvitys: int
    maksettava: int  # osto: liike maksaa myyjälle; myynti: asiakas maksaa liikkeelle
    etumaksu: int
    rahoitettava: int
    toimituksessa: int  # myynti: maksetaan toimituksen yhteydessä


def sopimuksen_summat(tyyppi, kohteet, vaihdot=(), *, toimistokulut=0, etumaksu=0, rahoitettava=0):
    """kohteet ja vaihdot: iteroitavia (hinta, jäännösvelka) -pareja senttiä."""
    kohteet, vaihdot = list(kohteet), list(vaihdot)
    kauppahinta = sum(h for h, _ in kohteet)
    toimistokulut, etumaksu, rahoitettava = toimistokulut or 0, etumaksu or 0, rahoitettava or 0
    if tyyppi == "osto":
        if vaihdot:
            raise ValueError("Ostosopimuksessa ei ole vaihtoajoneuvoja.")
        jaannosvelka = sum(j or 0 for _, j in kohteet)
        maksettava = kauppahinta - jaannosvelka
        return SopimuksenSummat(kauppahinta, 0, kauppahinta, jaannosvelka, 0, maksettava, 0, 0, maksettava)
    if tyyppi == "myynti":
        kateishinta = kauppahinta + toimistokulut
        hyvitys = sum(h for h, _ in vaihdot)
        jaannosvelka = sum(j or 0 for _, j in vaihdot)
        maksettava = kateishinta - hyvitys + jaannosvelka
        return SopimuksenSummat(
            kauppahinta,
            toimistokulut,
            kateishinta,
            jaannosvelka,
            hyvitys,
            maksettava,
            etumaksu,
            rahoitettava,
            maksettava - etumaksu - rahoitettava,
        )
    raise ValueError(f"Tuntematon sopimustyyppi: {tyyppi}")


@dataclass(frozen=True)
class Laskurivi:
    """Sopimuksesta syntyvä lasku ennen tallennusta.

    suunta: "myynti" (asiakas / rahoittaja maksaa liikkeelle) tai "osto" (liike maksaa).
    laji: ks. models.Lasku.LAJIT. maksettu: suoritettu jo sopimuksella (vaihtoajoneuvo).
    rivi: sopimusrivin indeksi (vaihtoajoneuvot ja jäännösvelat), muuten None.
    """

    suunta: str
    laji: str
    summa: int
    maksettu: bool = False
    rivi: int | None = None


def sopimuksen_laskut(tyyppi, summat, vaihdot=(), jaannosvelat=()):
    """Mitkä laskut osto- tai myyntisopimuksesta syntyy.

    Myyntisopimus: jokaisesta kaupan osasta oma lasku: käsiraha (etumaksu), rahoitusyhtiön osuus,
    maksu toimitettaessa ja vaihtoajoneuvon hyvitys (suoritettu, ei maksettava). Vaihtoajoneuvon
    jäännösvelasta liike maksaa rahoittajalle ostolaskun. Jos toimituksessa maksettava on
    negatiivinen, liike maksaa erotuksen asiakkaalle (hyvitys).
    Ostosopimus: ostohinta myyjälle (käteishinta - jäännösvelka) ja jäännösvelka rahoittajalle.

    vaihdot: vaihtoajoneuvojen hinnat; jaannosvelat: (rivin indeksi, jäännösvelka) -parit.
    """
    laskut = []
    if tyyppi == "myynti":
        if summat.etumaksu:
            laskut.append(Laskurivi("myynti", "etumaksu", summat.etumaksu))
        if summat.rahoitettava:
            laskut.append(Laskurivi("myynti", "rahoitus", summat.rahoitettava))
        if summat.toimituksessa > 0:
            laskut.append(Laskurivi("myynti", "toimitus", summat.toimituksessa))
        elif summat.toimituksessa < 0:
            laskut.append(Laskurivi("osto", "hyvitys", -summat.toimituksessa))
        for i, hinta in enumerate(vaihdot):
            laskut.append(Laskurivi("myynti", "vaihtoauto", hinta, maksettu=True, rivi=i))
    elif tyyppi == "osto":
        if summat.maksettava > 0:
            laskut.append(Laskurivi("osto", "ostohinta", summat.maksettava))
    else:
        raise ValueError(f"Tuntematon sopimustyyppi: {tyyppi}")
    for i, velka in jaannosvelat:
        if velka:
            laskut.append(Laskurivi("osto", "jaannosvelka", velka, rivi=i))
    return laskut


def viitenumero(perusosa):
    """Suomalainen viitenumero: perusosa + tarkiste (painot 7, 3, 1 oikealta), ryhmiteltynä viiden merkin osiin."""
    numerot = str(int(perusosa))
    if not 3 <= len(numerot) <= 19:
        raise ValueError("Viitenumeron perusosassa pitää olla 3–19 numeroa.")
    painot = (7, 3, 1)
    summa = sum(int(n) * painot[i % 3] for i, n in enumerate(reversed(numerot)))
    viite = numerot + str((10 - summa % 10) % 10)
    # Ryhmitellään oikealta viiden merkin ryhmiin
    ryhmat = []
    while viite:
        ryhmat.insert(0, viite[-5:])
        viite = viite[:-5]
    return " ".join(ryhmat)


def alv_osuus(verollinen_sentit, alv_kasittely, alv_prosentti):
    """Sopimushinnan ALV:n osuus. Marginaalikaupassa sopimukseen ei merkitä ALV:tä."""
    if alv_kasittely != "alv":
        return 0
    return verollinen_sentit - verottomaksi(verollinen_sentit, alv_prosentti)


def kierron_hinta(sopimushinta, alv_kasittely, alv_prosentti):
    """Sopimuksen käteishinta (sis. mahdollisen alv:n) kierron hinnaksi:
    marginaali sellaisenaan, ALV-kaupassa veroton."""
    if alv_kasittely == "alv":
        return verottomaksi(sopimushinta, alv_prosentti)
    return sopimushinta


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
