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
  kuvat (ulko / sisä / vaurio / dokumentti), varustekatalogi, yritykset (toimittajat ja asiakkaat), muutosloki.
- **Rahat sentteinä**, pyöristys `Decimal`-aritmetiikalla.

### Monivuokraajuus

Jokainen rivi kuuluu liikkeelle (`liike_id`). `LiikeMiddleware` aktivoi kirjautuneen käyttäjän liikkeen,
ja mallien oletusmanageri rajaa jokaisen kyselyn siihen. Ilman aktiivista liikettä kysely ei palauta
mitään vaan nostaa virheen. Tallennus tarkistaa, ettei rivi tai sen viittaukset osoita toiseen liikkeeseen.
Testit: `autot/tests/test_monivuokraajuus.py`.

### Katelaskenta (`autot/logiikka.py`)

- **Marginaaliverotus:** vero = (myyntihinta − ostohinta) × 25,5 / 125,5, jos voittomarginaali > 0.
  Kulut eivät pienennä veron laskentaperustetta, mutta niiden ALV vähennetään, joten ne ovat katteessa verottomina.
  Kate = myyntihinta − vero − ostohinta − kulut (alv 0).
- **Normaali ALV:** kaikki verottomina, kate = myynti − osto − kulut.
- ALV-kanta on liikkeen asetus (Hallinta → Asetukset). Laskentasäännöt kannattaa käydä läpi kirjanpitäjän kanssa;
  marginaalivero lasketaan autokohtaisesti.

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
2. Procountor-integraatio: myyntilasku kaupasta, ostot ja kulut kirjanpitoon.
3. Rekisterihaku Traficomin sopimuskumppanin rajapinnan kautta (koodistot vastaavat Traficomin koodeja; tarkistettava).
4. Hinta-arvio omasta kauppadatasta.
