# AutoERP – projektin säännöt

Autokaupan toiminnanohjausjärjestelmä: Django 5.2, PostgreSQL, HTMX, suomenkielinen käyttöliittymä.
Tuotanto Renderissä (`render.yaml`), kuvat Cloudflare R2:ssa.

## Säännöt

1. **Suomenkieliset nimet.** Mallit, kentät, funktiot, muuttujat, URL-nimet, pohjat ja käyttöliittymätekstit
   ovat suomeksi (esim. `Kierto`, `ostohinta`, `siirra_tila`). Ääkköset korvataan tunnisteissa (`hylatty`, `jalkikulu`),
   näkyvissä teksteissä ne kirjoitetaan oikein. Djangon omat rajapinnat (`save`, `get_queryset` ym.) pysyvät ennallaan.
2. **Testit jokaiselle muutokselle.** Uusi toiminto tai korjaus tuo mukanaan testin `autot/tests/`-kansioon.
   Bugikorjauksessa ensin testi, joka toistaa vian. Kaikki testit ajetaan ennen committia:
   `python manage.py test`. GitHub Actions ajaa ne jokaisesta pull requestista.
3. **Ei suoria SQL-muutoksia.** Tietokannan rakenne muuttuu vain Django-migraatioilla
   (`python manage.py makemigrations`). Ei käsin ajettua `ALTER TABLE`:a, ei raakaa SQL:ää sovelluskoodissa.
   Datamuutokset tehdään data-migraatioina (`RunPython`). Julkaistua migraatiota ei muokata jälkikäteen.
4. **Monivuokraajuus on ehdoton.** Jokainen liiketoimintarivi kuuluu liikkeelle:
   - Uusi malli perii `liikkeet.rajaus.LiikkeenMalli` -luokan (Meta: `class Meta(LiikkeenMalli.Meta)`).
   - Näkymissä käytetään vain oletusmanageria `Malli.objects` (rajattu kirjautuneen käyttäjän liikkeeseen).
     Rajaamatonta `Malli.kaikki`-manageria käytetään vain hallintakomennoissa ja testeissä.
   - Käyttäjät näkymissä: `Kayttaja.liikkeen`, ei `Kayttaja.objects`.
   - Lomakkeiden valintakenttien `queryset` asetetaan `__init__`:ssä (ks. `autot/forms.py`).
   - Rivin haku id:llä: `get_object_or_404(Malli, pk=...)` → toisen liikkeen rivi antaa 404.
   - Jokaiselle uudelle reitille lisätään testi `test_monivuokraajuus.py`:hin (toisen liikkeen id → 404, data ennallaan).
5. **Rahat sentteinä.** Rahasummat ovat kokonaislukuja (`BigIntegerField`, senttiä). Muunnokset vain
   `autot/logiikka.py`:n funktioilla (`euro_senteiksi`, `euro`, `euro_input`). Ei liukulukuja rahalle;
   pyöristys `Decimal` + `ROUND_HALF_UP`.
6. **Katelaskenta `autot/logiikka.py`:ssä**, ilman Django-riippuvuuksia, ja jokaiselle säännölle yksikkötesti
   (`test_logiikka.py`). Marginaaliverotus: vero = (myynti − osto) × r / (100 + r), jos voittomarginaali > 0.
7. **Kuvat vain `autot/kuvat.py`:n kautta** (Djangon `default_storage`: R2 tuotannossa, levy kehityksessä).
   Kuvia ei palvella suoraan ämpäristä, vaan näkymä tarkistaa liikkeen ja ohjaa allekirjoitettuun osoitteeseen.
8. **HTMX:** välilehdet ja pienet päivitykset palauttavat osapohjan (`_`-alkuiset pohjat). Jokaisen lomakkeen
   pitää toimia myös ilman JavaScriptiä (tavallinen POST + uudelleenohjaus).
9. **Tyyli:** `ruff check .` ja `ruff format .` (asetukset `pyproject.toml`:ssa, rivin pituus 120).

## Komennot

```bash
pip install -r requirements-dev.txt
export DEBUG=1                                 # kehitys: ei SECRET_KEY-vaatimusta, kuvat levylle
python manage.py migrate
python manage.py demodata                      # demoliike, kirjautuminen admin@demo.fi / demo1234
python manage.py runserver
python manage.py test                          # testit (vaatii PostgreSQL:n, DATABASE_URL)
python manage.py makemigrations --check        # onko mallimuutoksilta unohtunut migraatio
ruff check . && ruff format --check .
```

Oletustietokanta: `postgres://autoerp:autoerp@localhost:5432/autoerp` (vaihda `DATABASE_URL`:lla).

## Rakenne

```
config/            asetukset, reitit, wsgi, terveystarkistus /terveys/
liikkeet/          Liike, Kayttaja, monivuokraajuus (rajaus.py, middleware.py), kirjautuminen
autot/
  logiikka.py      tilat, siirrot, raha, katelaskenta (puhdas Python)
  models.py        tietomalli: Ajoneuvo, Kierto, Kulu, Tilahistoria, Tehtava, Kuntoraportti, ...
  palvelut.py      tilasiirrot, uusi kierros, tehtävien luonti, muutosloki
  forms.py         lomakkeet
  kuvat.py         kuvien pienennys ja tallennus
  perusdata.py     uuden liikkeen koodistot, varusteet, tehtäväpohjat
  views/           autot, kortti (välilehdet), tehtavat, hallinta, raportit
  templates/autot/ pohjat; valilehdet/ = kortin välilehdet
  management/commands/  demodata, luo_liike
  tests/           test_logiikka, test_monivuokraajuus, test_nakymat
```
