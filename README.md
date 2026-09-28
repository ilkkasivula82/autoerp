# AutoERP – autokaupan toiminnanohjaus

Django 5.2 + PostgreSQL + HTMX. Suomenkielinen käyttöliittymä, monivuokraajuus (useita autoliikkeitä samassa
järjestelmässä), kuvat Cloudflare R2:ssa. Pohjana aiempi Flask-versio 0.1.

Projektin säännöt: [CLAUDE.md](CLAUDE.md).

## Käynnistys paikallisesti

Tarvitaan Python 3.12 ja PostgreSQL.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
createdb autoerp                                   # tai aseta DATABASE_URL
export DEBUG=1
python manage.py migrate
python manage.py demodata                          # demoliike ja -autot
python manage.py runserver                         # http://127.0.0.1:8000
```

Kirjautuminen: `admin@demo.fi` / `demo1234` (myös `osto@`, `myynti@`, `piha@`, `talous@demo.fi`).

Testit: `python manage.py test`.

## Tietomallin ydinajatus

| Malli | Mitä | Miksi |
|---|---|---|
| `Ajoneuvo` | Fyysinen auto: VIN, rekisteri, tekniset tiedot, **varusteet** | Sama auto voi tulla meille monta kertaa. |
| `Kierto` | Yksi kierros: tarjous → osto → … → myynti → toimitus. Hinnat, tila, km, kunto, kuvat, kulut, tehtävät | Palaava auto saa **uuden kierroksen**; vanha kierros ja sen kate säilyvät. |

- **Palaava auto tunnistetaan** VIN:llä ja rekisterillä (`ABC123`, `abc-123`, `ABC 123` ovat sama).
  Tietokanta estää kaksi avointa kierrosta samalle autolle.
- **Kulut milloin tahansa**, myös myynnin jälkeen: *jälkikulut* näkyvät erikseen (kate myyntihetkellä / lopullinen kate).
- **Tilat** Tarjottu → Ostettu → Tulossa → Kunnostuksessa → Myynnissä → Varattu → Myyty → Toimitettu sekä Hylätty.
  Tilahistoria kertoo vaihekohtaiset kestot. **Tehtäväpohjat** luovat vaiheen tehtävät automaattisesti.
- **Kuntoraportti** kahdesti (tarjous / saapuminen) erot korostettuina, rengassarjat, vauriot kuvineen,
  kuvat (ulko / sisä / vaurio / dokumentti; 15 vakiopaikkaa, raahaa ja pudota, ohjattu kuvaus puhelimella), varustekatalogi, yritykset (toimittajat ja asiakkaat), muutosloki.
- **Rahat sentteinä**, pyöristys `Decimal`-aritmetiikalla.

### Miten auto tulee varastoon

Tarjottu auto (ei vielä ostettu) voidaan kirjata ilman ostohintaa. Varastoon auto tulee vain näin:

1. **Ostosopimuksella** (kortilla "Tee ostosopimus" tai Uusi auto → "Ostetaan"): sopimuksen hinta on ostohinta.
2. **Myyntisopimuksen vaihtoajoneuvona**: vaihtohinta on vaihtoauton ostohinta, ostokanavana "Vaihtoauto".
3. **Suoraan varastoon** (Uusi auto → "Suoraan varastoon" tai tilasiirto "Ostettu ilman sopimusta"): ostohinta pakollinen.

Tietokannan rajoite varmistaa, ettei varastossa tai myytynä ole autoa ilman ostohintaa eikä myytyä ilman myyntihintaa.

### Sopimukset

Osto- ja myyntisopimus tallennetaan omana tietueenaan (vastapuolen ja ajoneuvon tiedot sopimushetkeltä,
juokseva sopimusnumero liikkeittäin) ja tulostetaan selaimesta (Tulosta / tallenna PDF).

- Myyntisopimus: maksettava = kauppahinta + toimistokulut − vaihtohinnat + vaihtoautojen jäännösvelat;
  toimituksessa maksetaan = maksettava − etumaksu − rahoitettava osuus.
  Esim. Golf 10 000 €, Corolla vaihdossa 3 000 € → asiakas maksaa 7 000 €, Corolla varastoon 3 000 €:lla.
- Ostosopimus: myyjälle maksetaan = käteishinta − jäännösvelka.
- Hinnat sopimuksella ovat käteishintoja (ALV-kaupassa verollisia); kierrolle tallennetaan ALV-kaupassa veroton hinta.
- Liikkeen yhteystiedot sekä omat osto- ja myyntiehdot (sopimuksen liitteeksi) asetetaan Hallinta → Asetukset.

### Myyntitarjoukset

Varastossa olevasta autosta tehdään tarjous asiakkaalle (hinta, toimistokulut, vaihtoauto ja sen jäännösvelka).
Tarjoukset näkyvät auton Tarjoukset-välilehdellä ja tulostuvat / lähtevät sähköpostilla. "Tee sopimus" avaa
myyntisopimuksen tarjouksen tiedoilla; sopimuksen tallennus merkitsee tarjouksen hyväksytyksi ja muut auton
avoimet tarjoukset hylätyiksi.

### Laskut

Sopimuksen tallennus luo laskut automaattisesti (`sopimukset.luo_laskut`, säännöt `logiikka.sopimuksen_laskut`):

- Myyntisopimus: oma myyntilasku käsirahasta (eräpäivä heti), rahoitusyhtiön osuudesta (maksaja rahoitusyhtiö)
  ja toimituksessa maksettavasta (eräpäivä sopimuksen eräpäivä / toimitusaika / maksuaika) sekä kuitattu
  "lasku" vaihtoajoneuvosta. Jos vaihtoauto on kauppahintaa arvokkaampi, erotuksesta tulee ostolasku asiakkaalle.
- Jäännösvelka (vaihtoauton tai ostetun auton): ostolasku velan haltijalle. Esim. vaihtoauto 10 000 €, velkaa
  8 000 € → asiakkaalle jää hyväksi 2 000 €, ja liike maksaa 8 000 € rahoittajalle.
- Ostosopimus: ostolasku myyjälle (käteishinta − jäännösvelka).

Sopimuksen "Kaupan erittely ja laskut" -sivu näyttää hinnan jakautumisen ja ALV-käsittelyn; laskut tulostetaan
selaimesta. Myyntilaskuissa on viitenumero, marginaaliautoissa merkintä "Voittomarginaalijärjestely – käytetyt
tavarat". Laskut-sivulla kirjataan maksut. Maksuaika on liikkeen asetus.

### Monivuokraajuus

Jokainen rivi kuuluu liikkeelle (`liike_id`). `LiikeMiddleware` aktivoi kirjautuneen käyttäjän liikkeen,
ja mallien oletusmanageri rajaa jokaisen kyselyn siihen. Ilman aktiivista liikettä kysely ei palauta
mitään vaan nostaa virheen. Tallennus tarkistaa, ettei rivi tai sen viittaukset osoita toiseen liikkeeseen.
Testit: `autot/tests/test_monivuokraajuus.py`.

### Katelaskenta (`autot/logiikka.py`)

- **Marginaaliverotus:** auton voittomarginaalivero = (myyntihinta − ostohinta) × 25,5 / 125,5, jos marginaali > 0.
  Kulut eivät pienennä veron laskentaperustetta, mutta niiden ALV vähennetään, joten ne ovat katteessa verottomina.
  Kate (netto) = myyntihinta − vero − ostohinta − kulut (alv 0).
- **Normaali ALV:** kaikki verottomina, kate = myynti − osto − kulut.
- ALV-kanta on liikkeen asetus (Hallinta → Asetukset).

**Menettely** on liikkeen asetus (oletus kuukausikohtainen). Autokohtainen vero vastaa tavarakohtaista menettelyä. Kuukausikohtaisessa menettelyssä (autokaupan
yleisin) ilmoitettava vero lasketaan kuukauden kaikkien marginaaliostojen ja -myyntien erotuksesta. Auton oma
vero-osuus on silloinkin käyttökelpoinen yksittäisen auton katteen arvioon, mutta se ei ole ilmoitettava vero.
Kuukausikohtaisessa menettelyssä tappiollinen kauppa pienentää kuukauden veroa, joten auton vero-osuus voi olla
negatiivinen; tavarakohtaisessa se on vähintään 0.

**Netto vai brutto.** Yläpalkin valitsimella (Netto / Brutto) käyttäjä valitsee, näytetäänkö rahaluvut listoilla,
kortilla ja raporteilla ilman alv:tä vai alv:n kanssa. Valinta tallentuu käyttäjälle.

| | Netto (alv 0) | Brutto (sis. alv) |
|---|---|---|
| Myynti | marginaali: myyntihinta / (1 + alv); ALV: veroton | marginaali: myyntihinta; ALV: veroton × (1 + alv) |
| Osto | marginaali: laskennallinen (myynti netto − bruttokate); ALV: veroton | marginaali: ostohinta; ALV: verollinen |
| Kulut | verottomina | verollisina, kukin omalla ALV-kannallaan (syötetty summa säilyy sentilleen) |
| Kate | myynti − osto − kulut | myynti − osto − kulut |

Marginaaliauton nettoluvut ovat laskennallisia: myynti ja osto pienenevät veron verran niin, että erotus on
bruttokate (myynti − vero − osto). Myymättömän auton netto-ostohinta on ostohinta / (1 + alv). Myyntisaatavat
näytetään aina verollisina.

## Tuotanto (Render)

`render.yaml` on Render Blueprint: web-palvelu (gunicorn) ja PostgreSQL. Build ajaa `build.sh`:n
(riippuvuudet + `collectstatic`), migraatiot ajetaan jokaisen deployn yhteydessä (`preDeployCommand`),
terveystarkistus `/terveys/`.

Ensimmäisen liikkeen ja ylläpitäjän luonti (Renderin Shellissä):

```bash
python manage.py luo_liike --nimi "N247 Finland Oy" --sahkoposti admin@n247.fi --admin-nimi "Etunimi Sukunimi"
```

### Ympäristömuuttujat

| Muuttuja | Pakollinen | Kuvaus |
|---|---|---|
| `DATABASE_URL` | kyllä | Blueprint asettaa tietokannasta |
| `SECRET_KEY` | kyllä | Blueprint generoi |
| `R2_BUCKET` | kuvat | R2-ämpärin nimi. Ilman tätä kuvat tallennetaan levylle (häviävät Renderissä). |
| `R2_ACCOUNT_ID` | kuvat | Cloudflare-tilin tunnus (päätepiste `https://<id>.r2.cloudflarestorage.com`) |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | kuvat | R2 API -tunnus (Object Read & Write, vain tähän ämpäriin) |
| `R2_ENDPOINT_URL` | ei | Korvaa `R2_ACCOUNT_ID`:stä muodostetun päätepisteen (esim. EU-alue: `https://<id>.eu.r2.cloudflarestorage.com`) |
| `ALLOWED_HOSTS` | ei | Omat verkkotunnukset pilkulla erotettuina; Renderin osoite lisätään automaattisesti |
| `DEBUG` | ei | `1` vain kehityksessä |

R2-ämpäri pidetään yksityisenä: sovellus tarkistaa, että kuva kuuluu käyttäjän liikkeelle, ja ohjaa
tunnin voimassa olevaan allekirjoitettuun osoitteeseen.

## Seuraavat askeleet

1. Kokeilu N247:n kanssa ja palautteen perusteella korjaukset.
1. Sähköinen allekirjoitus sopimuksille; tarjous sähköpostilla, asiakkaan hyväksyntä linkistä ja sopimus
   automaattisesti allekirjoitettavaksi.
1. Laskujen lähetys (PDF / verkkolasku) suoraan järjestelmästä; nopea "lisää auto puhelimella" -lomake.
2. Procountor-integraatio: myyntilasku kaupasta, ostot ja kulut kirjanpitoon.
3. Rekisterihaku Traficomin sopimuskumppanin rajapinnan kautta (koodistot vastaavat Traficomin koodeja; tarkistettava).
4. Hinta-arvio omasta kauppadatasta.
