"""Lomakkeet.

Valintakenttien kyselyt (yritykset, käyttäjät, varusteet) asetetaan aina
__init__:ssä pyynnön aikana, jolloin ne rajautuvat käyttäjän liikkeeseen.
"""

from django import forms
from django.utils import timezone

from liikkeet.models import Kayttaja, Liike, Rooli

from . import logiikka
from . import sopimukset as sopimuspalvelu
from .models import (
    Ajoneuvo,
    Kierto,
    Koodi,
    Kulu,
    Kuntoraportti,
    Myyntitarjous,
    Rengassarja,
    Sopimus,
    SopimusRivi,
    Tehtava,
    Tehtavapohja,
    Varuste,
    Varustekategoria,
    Vaurio,
    Yritys,
)


def viivat_tyhjiksi(lomake):
    """Tyhjä valinta näytetään viivana '–' Djangon '---------' sijaan."""
    for kentta in lomake.fields.values():
        if isinstance(kentta, forms.ModelChoiceField):
            if kentta.empty_label is not None:
                kentta.empty_label = "–"
        elif isinstance(kentta, forms.ChoiceField):
            kentta.choices = [("", "–") if arvo == "" else (arvo, nimi) for arvo, nimi in kentta.choices]


class Suomeksi:
    """Mixin: viivat tyhjiksi valinnoiksi."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        viivat_tyhjiksi(self)


class EuroKentta(forms.CharField):
    """Euromäärä tekstinä ('12 500,50') -> sentit (int)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)
        self.widget.attrs.setdefault("inputmode", "decimal")

    def prepare_value(self, value):
        if isinstance(value, int):
            return logiikka.euro_input(value)
        return value

    def to_python(self, value):
        try:
            return logiikka.euro_senteiksi(value)
        except ValueError as e:
            raise forms.ValidationError("Anna summa euroina, esim. 12 500 tai 12500,50.") from e


class ProsenttiKentta(forms.DecimalField):
    """Hyväksyy myös pilkun: '25,5'."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace(",", ".").replace("%", "").strip()
        return super().to_python(value)


class PvmSyote(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


def _yritykset():
    return Yritys.objects.all()


def _kayttajat():
    return Kayttaja.liikkeen.filter(is_active=True).order_by("nimi")


def koodivalinnat(ryhma):
    return [("", "–")] + [(k.koodi, k.nimi) for k in Koodi.objects.filter(ryhma=ryhma)]


class KoodiKentat:
    """Käyttövoima, vaihteisto ja korimalli valitaan liikkeen koodistosta."""

    def _aseta_koodit(self):
        for ryhma in ("kayttovoima", "vaihteisto", "korimalli"):
            if ryhma in self.fields:
                vanha = self.fields[ryhma]
                self.fields[ryhma] = forms.ChoiceField(label=vanha.label, required=False, choices=koodivalinnat(ryhma))


AJONEUVO_KENTAT = [
    "rekisterinumero",
    "vin",
    "merkki",
    "malli",
    "mallitarkenne",
    "vuosimalli",
    "ensirekisterointi",
    "kayttovoima",
    "vaihteisto",
    "korimalli",
    "vetotapa",
    "vari",
    "teho_kw",
    "iskutilavuus",
    "ovet",
    "istuimet",
]


class AjoneuvoLomake(Suomeksi, KoodiKentat, forms.ModelForm):
    class Meta:
        model = Ajoneuvo
        fields = AJONEUVO_KENTAT
        widgets = {"ensirekisterointi": PvmSyote()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aseta_koodit()
        for nimi in ("rekisterinumero", "vin"):
            self.fields[nimi].widget.attrs["style"] = "text-transform:uppercase"


class UusiAutoLomake(KoodiKentat, forms.Form):
    """Uusi auto / tarjous. Ajoneuvo tunnistetaan VIN:llä ja rekisterillä."""

    rekisterinumero = forms.CharField(label="Rekisterinumero", max_length=20, required=False)
    vin = forms.CharField(label="VIN (valmistenumero)", max_length=17, required=False)
    merkki = forms.CharField(label="Merkki", max_length=100)
    malli = forms.CharField(label="Malli", max_length=100)
    mallitarkenne = forms.CharField(label="Mallitarkenne", max_length=200, required=False)
    vuosimalli = forms.IntegerField(label="Vuosimalli", required=False, min_value=1900, max_value=2100)
    km = forms.IntegerField(label="Kilometrit", required=False, min_value=0)
    kayttovoima = forms.ChoiceField(label="Käyttövoima", required=False)
    vaihteisto = forms.ChoiceField(label="Vaihteisto", required=False)
    korimalli = forms.ChoiceField(label="Korimalli", required=False)

    toimittaja = forms.ModelChoiceField(label="Tarjoaja / toimittaja", queryset=Yritys.kaikki.none(), required=False)
    ostokanava = forms.ChoiceField(label="Ostokanava", choices=[("", "–")] + logiikka.OSTOKANAVAT, required=False)
    tarjottu_hinta = EuroKentta(label="Pyydetty hinta (€)")
    alv_kasittely = forms.ChoiceField(label="Verokohtelu", choices=logiikka.ALV_KASITTELYT, initial="marginaali")
    huomiot = forms.CharField(label="Huomiot", widget=forms.Textarea, required=False)
    KIRJAUKSET = [
        ("tarjous", "Tarjous: autoa ei ole vielä ostettu"),
        ("ostosopimus", "Ostetaan: tehdään ostosopimus myyjän kanssa"),
        ("varasto", "Suoraan varastoon (ostohinta pakollinen)"),
    ]
    kirjaus = forms.ChoiceField(
        label="Mitä kirjataan?", choices=KIRJAUKSET, initial="tarjous", required=False, widget=forms.RadioSelect
    )
    ostohinta = EuroKentta(label="Ostohinta (€, ALV-autossa veroton)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["toimittaja"].queryset = _yritykset()
        self._aseta_koodit()

    def clean_rekisterinumero(self):
        return logiikka.normalisoi_rekisteri(self.cleaned_data.get("rekisterinumero"))

    def clean_vin(self):
        return (self.cleaned_data.get("vin") or "").strip().upper()

    def clean(self):
        data = super().clean()
        data["kirjaus"] = data.get("kirjaus") or "tarjous"
        if data["kirjaus"] == "varasto" and data.get("ostohinta") is None:
            self.add_error("ostohinta", "Anna ostohinta, kun auto lisätään suoraan varastoon.")
        return data


KAUPPA_KENTAT = [
    "km",
    "toimittaja",
    "ostokanava",
    "tarjottu_hinta",
    "tarjottu_pvm",
    "ostohinta",
    "ostopvm",
    "alv_kasittely",
    "arvioitu_saapuminen",
    "sijainti",
    "hylkayksen_syy",
    "pyyntihinta",
    "asiakas",
    "myyntihinta",
    "myyntipvm",
    "laskunumero",
    "maksettu_pvm",
    "toimitettu_pvm",
    "huomiot",
]


class KauppaLomake(Suomeksi, forms.ModelForm):
    """Kierron osto- ja myyntitiedot. Muutokset kirjataan muutoslokiin näkymässä."""

    tarjottu_hinta = EuroKentta(label="Pyydetty hinta (€)")
    ostohinta = EuroKentta(label="Ostohinta (€)")
    pyyntihinta = EuroKentta(label="Pyyntihinta (€)")
    myyntihinta = EuroKentta(label="Myyntihinta (€)")

    class Meta:
        model = Kierto
        fields = KAUPPA_KENTAT
        widgets = {
            f: PvmSyote()
            for f in ("tarjottu_pvm", "ostopvm", "arvioitu_saapuminen", "myyntipvm", "maksettu_pvm", "toimitettu_pvm")
        } | {"huomiot": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["toimittaja"].queryset = _yritykset()
        self.fields["asiakas"].queryset = _yritykset()
        self.fields["km"].label = "Kilometrit (tällä kierroksella)"
        self.fields["sijainti"].widget.attrs["placeholder"] = "esim. piha, halli, kunnostaja"

    def clean(self):
        data = super().clean()
        tila = self.instance.tila
        if tila in logiikka.OSTETUT and data.get("ostohinta") is None:
            self.add_error("ostohinta", "Varastossa olevalla autolla pitää olla ostohinta.")
        if tila in logiikka.MYYDYT and data.get("myyntihinta") is None:
            self.add_error("myyntihinta", "Myydyllä autolla pitää olla myyntihinta.")
        return data


class SiirtoLomake(Suomeksi, forms.Form):
    """Tilasiirron lisätiedot (vain siirtoon liittyvät kentät täytetään)."""

    tila = forms.ChoiceField(choices=[(k, n) for k, n, _ in logiikka.TILAT])
    ostohinta = EuroKentta()
    ostopvm = forms.DateField(required=False)
    alv_kasittely = forms.ChoiceField(choices=[("", "")] + logiikka.ALV_KASITTELYT, required=False)
    asiakas = forms.ModelChoiceField(queryset=Yritys.kaikki.none(), required=False)
    myyntihinta = EuroKentta()
    myyntipvm = forms.DateField(required=False)
    laskunumero = forms.CharField(max_length=50, required=False)
    toimitettu_pvm = forms.DateField(required=False)
    hylkayksen_syy = forms.CharField(max_length=500, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asiakas"].queryset = _yritykset()


class KuluLomake(Suomeksi, forms.ModelForm):
    summa = EuroKentta(label="Summa (€)", required=True)
    summa_on = forms.ChoiceField(
        label="Summa on", choices=[("veroton", "veroton (alv 0)"), ("verollinen", "verollinen")], initial="veroton"
    )
    alv_prosentti = ProsenttiKentta(label="ALV %", max_digits=5, decimal_places=2, min_value=0, max_value=100)

    class Meta:
        model = Kulu
        fields = ["tyyppi", "alv_prosentti", "pvm", "toimittaja", "kuvaus"]
        widgets = {"pvm": PvmSyote(), "alv_prosentti": forms.TextInput(attrs={"inputmode": "decimal"})}

    def __init__(self, *args, alv_oletus=None, **kwargs):
        super().__init__(*args, **kwargs)
        if alv_oletus is not None:
            self.fields["alv_prosentti"].initial = str(alv_oletus).rstrip("0").rstrip(".").replace(".", ",")
        self.fields["kuvaus"].widget.attrs["placeholder"] = "esim. määräaikaishuolto, jarrupalat edessä"
        self.order_fields(["tyyppi", "summa", "summa_on", "alv_prosentti", "pvm", "toimittaja", "kuvaus"])

    def save(self, commit=True):
        kulu = super().save(commit=False)
        summa, alv = self.cleaned_data["summa"], self.cleaned_data["alv_prosentti"]
        if self.cleaned_data["summa_on"] == "verollinen":
            kulu.summa_veroton = logiikka.verottomaksi(summa, alv)
            kulu.summa_verollinen = summa  # syötetty summa sellaisenaan
        else:
            kulu.summa_veroton = summa
            kulu.summa_verollinen = logiikka.verolliseksi(summa, alv)
        if commit:
            kulu.save()
        return kulu


class KuntoLomake(Suomeksi, forms.ModelForm):
    class Meta:
        model = Kuntoraportti
        fields = Kuntoraportti.VERRATTAVAT
        widgets = {
            "maalipinta": forms.RadioSelect,
            "yleiskunto": forms.RadioSelect,
            "sisatilat": forms.RadioSelect,
            "huomiot": forms.Textarea(attrs={"rows": 2}),
            "avaimet": forms.NumberInput(attrs={"style": "max-width:90px"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nimi in ("maalipinta", "yleiskunto", "sisatilat"):
            self.fields[nimi].choices = Kuntoraportti.ASTEIKKO


class RengasLomake(Suomeksi, forms.ModelForm):
    urasyvyys_mm = ProsenttiKentta(label="Urasyvyys (mm)", max_digits=4, decimal_places=1, required=False, min_value=0)

    class Meta:
        model = Rengassarja
        fields = ["tyyppi", "koko", "vanteet", "urasyvyys_mm", "kunto", "sijainti", "huomiot"]
        widgets = {"koko": forms.TextInput(attrs={"placeholder": "225/45R17"})}


class VaurioLomake(forms.ModelForm):
    arvioitu_korjaus = EuroKentta(label="Arvioitu korjaus (€)")
    kuvatiedosto = forms.ImageField(label="Kuva", required=False)

    class Meta:
        model = Vaurio
        fields = ["kohta", "kuvaus", "arvioitu_korjaus"]
        widgets = {
            "kohta": forms.TextInput(attrs={"list": "vauriokohdat", "placeholder": "esim. oikea etuovi"}),
            "kuvaus": forms.TextInput(attrs={"placeholder": "esim. naarmu 10 cm, lommo"}),
        }


class KuvaLatausLomake(forms.Form):
    tyyppi = forms.ChoiceField(
        label="Kuvatyyppi",
        choices=[
            ("ulko", "Ulkokuvat"),
            ("sisa", "Sisäkuvat"),
            ("vaurio", "Vauriot"),
            ("dokumentti", "Dokumentit (paperit, huoltokirja)"),
        ],
    )


class TehtavaLomake(Suomeksi, forms.ModelForm):
    class Meta:
        model = Tehtava
        fields = ["otsikko", "vastuu", "erapaiva", "kuvaus"]
        widgets = {
            "erapaiva": PvmSyote(),
            "otsikko": forms.TextInput(attrs={"placeholder": "esim. vie renkaat vaihtoon"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vastuu"].queryset = _kayttajat()


class TehtavapohjaLomake(forms.ModelForm):
    rooli = forms.ChoiceField(label="Rooli", choices=[("", "Rooli…")] + list(Rooli.choices), required=False)

    class Meta:
        model = Tehtavapohja
        fields = ["tila", "otsikko", "rooli", "vastuu", "erapaiva_pv"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vastuu"].queryset = _kayttajat()
        self.fields["vastuu"].empty_label = "tai henkilö…"


class YritysLomake(Suomeksi, forms.ModelForm):
    class Meta:
        model = Yritys
        fields = [
            "nimi",
            "y_tunnus",
            "tyyppi",
            "yhteyshenkilo",
            "puhelin",
            "sahkoposti",
            "lahiosoite",
            "postinumero",
            "postitoimipaikka",
            "tilinumero",
            "alv_velvollinen",
            "huomiot",
        ]
        widgets = {"huomiot": forms.Textarea(attrs={"rows": 3})}


class KayttajaLomake(forms.ModelForm):
    salasana = forms.CharField(
        label="Salasana",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        required=False,
        min_length=8,
    )

    class Meta:
        model = Kayttaja
        fields = ["nimi", "sahkoposti", "rooli", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:
            self.fields["salasana"].required = True
            self.fields.pop("is_active")
        else:
            self.fields["salasana"].widget.attrs["placeholder"] = "ei muutosta"
            self.fields["sahkoposti"].disabled = True

    def clean_sahkoposti(self):
        sahkoposti = self.cleaned_data["sahkoposti"].strip().lower()
        muut = Kayttaja.objects.filter(sahkoposti__iexact=sahkoposti).exclude(pk=self.instance.pk)
        if muut.exists():
            raise forms.ValidationError("Sähköposti on jo käytössä.")
        return sahkoposti

    def save(self, commit=True):
        kayttaja = super().save(commit=False)
        if self.cleaned_data.get("salasana"):
            kayttaja.set_password(self.cleaned_data["salasana"])
        if commit:
            kayttaja.save()
        return kayttaja


class LiikeLomake(forms.ModelForm):
    alv_prosentti = ProsenttiKentta(
        label="Yleinen ALV-kanta (%)", max_digits=5, decimal_places=2, min_value=0, max_value=100
    )

    class Meta:
        model = Liike
        fields = [
            "nimi",
            "y_tunnus",
            "alv_prosentti",
            "marginaalimenettely",
            "maksuaika_pv",
            "lahiosoite",
            "postinumero",
            "postitoimipaikka",
            "puhelin",
            "sahkoposti",
            "tilinumero",
            "ostoehdot",
            "myyntiehdot",
        ]
        widgets = {"ostoehdot": forms.Textarea(attrs={"rows": 6}), "myyntiehdot": forms.Textarea(attrs={"rows": 6})}
        help_texts = {
            "ostoehdot": "Tulostetaan ostosopimuksen liitteeksi.",
            "myyntiehdot": "Tulostetaan myyntisopimuksen liitteeksi.",
        }


class KoodiLomake(forms.ModelForm):
    class Meta:
        model = Koodi
        fields = ["ryhma", "koodi", "nimi"]

    def clean(self):
        data = super().clean()
        if Koodi.objects.filter(ryhma=data.get("ryhma"), koodi=data.get("koodi")).exists():
            raise forms.ValidationError("Koodi on jo olemassa.")
        return data


class VarustekategoriaLomake(forms.ModelForm):
    class Meta:
        model = Varustekategoria
        fields = ["nimi"]


class VarusteetLomake(forms.Form):
    """Useita varusteita kerralla: yksi per rivi."""

    kategoria = forms.ModelChoiceField(label="Kategoria", queryset=Varustekategoria.kaikki.none())
    nimet = forms.CharField(label="Varusteet (yksi per rivi)", widget=forms.Textarea(attrs={"rows": 6}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kategoria"].queryset = Varustekategoria.objects.all()


class VarusteMuokkausLomake(forms.ModelForm):
    class Meta:
        model = Varuste
        fields = ["nimi", "kategoria"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kategoria"].queryset = Varustekategoria.objects.all()


# ---------- Sopimukset ----------


class SopimusLomake(Suomeksi, forms.ModelForm):
    """Sopimuksen yleiset tiedot ja vastapuoli (valitaan rekisteristä tai kirjoitetaan uusi)."""

    valittu = forms.ModelChoiceField(
        label="Asiakas / yritys rekisteristä", queryset=Yritys.kaikki.none(), required=False
    )
    toimistokulut = EuroKentta(label="Toimistokulut (€)")
    etumaksu = EuroKentta(label="Etumaksu (€)")
    rahoitettava = EuroKentta(label="Rahoitettava osuus (€)")

    def clean_toimistokulut(self):
        return self.cleaned_data.get("toimistokulut") or 0

    def clean_etumaksu(self):
        return self.cleaned_data.get("etumaksu") or 0

    def clean_rahoitettava(self):
        return self.cleaned_data.get("rahoitettava") or 0

    class Meta:
        model = Sopimus
        fields = [
            "vp_nimi",
            "vp_tunnus",
            "vp_lahiosoite",
            "vp_postinumero",
            "vp_postitoimipaikka",
            "vp_puhelin",
            "vp_sahkoposti",
            "vp_tilinumero",
            "vp_alv_velvollinen",
            "vp2_nimi",
            "vp2_tunnus",
            "vp2_osoite",
            "vp2_puhelin",
            "vp2_sahkoposti",
            "tunnistus",
            "pep",
            "pvm",
            "toimitusaika",
            "maksutapa",
            "erapaiva",
            "rahoitusyhtio",
            "lisatiedot",
        ]
        widgets = {
            "pvm": PvmSyote(),
            "toimitusaika": PvmSyote(),
            "erapaiva": PvmSyote(),
            "lisatiedot": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["valittu"].queryset = _yritykset()
        self.fields["vp_nimi"].required = False
        self.fields["pvm"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        valittu = data.get("valittu")
        if not valittu and not data.get("vp_nimi"):
            self.add_error("vp_nimi", "Valitse vastapuoli rekisteristä tai anna nimi.")
        if valittu:
            # Tyhjät kentät täydennetään rekisterin tiedoista
            for kentta, arvo in sopimuspalvelu.vastapuolen_tiedot(valittu).items():
                if data.get(kentta) in (None, "") and kentta != "vp_alv_velvollinen":
                    data[kentta] = arvo
        return data


ILMOITETUT = ["kolaroitu", "maahantuotu", "mittari_vastaa", "rakennemuutoksia"]


class KohdeLomake(Suomeksi, forms.Form):
    """Kaupan kohteen hinta ja ehdot. Hinta on käteishinta sis. mahdollisen alv:n."""

    hinta = EuroKentta(label="Käteishinta (€, sis. alv)", required=True)
    jaannosvelka = EuroKentta(label="Jäännösvelka (€)")
    jaannosvelan_haltija = forms.CharField(label="Jäännösvelan haltija", max_length=200, required=False)
    alv_kasittely = forms.ChoiceField(
        label="Verotus",
        choices=logiikka.ALV_KASITTELYT,
        initial="marginaali",
        required=False,
        help_text="Normaali ALV vain, jos auto on ollut myyjällä 100 % vähennykseen oikeuttavassa käytössä.",
    )
    km = forms.IntegerField(label="Mittarilukema (km)", required=False, min_value=0)
    katsastettu = forms.DateField(label="Edellinen katsastus", required=False, widget=PvmSyote())
    kolaroitu = forms.ChoiceField(label="Kolaroitu", choices=[("", "")] + SopimusRivi.ILMOITUS, required=False)
    maahantuotu = forms.ChoiceField(
        label="Tuotu käytettynä maahan", choices=[("", "")] + SopimusRivi.ILMOITUS, required=False
    )
    mittari_vastaa = forms.ChoiceField(
        label="Mittarilukema vastaa ajomäärää", choices=[("", "")] + SopimusRivi.ILMOITUS, required=False
    )
    rakennemuutoksia = forms.ChoiceField(
        label="Rakenteellisia muutoksia", choices=[("", "")] + SopimusRivi.ILMOITUS, required=False
    )

    def clean_jaannosvelka(self):
        return self.cleaned_data.get("jaannosvelka") or 0


class VaihtoLomake(KohdeLomake):
    """Myyntisopimuksen vaihtoajoneuvo. Tyhjä lomake ohitetaan."""

    rekisterinumero = forms.CharField(label="Rekisterinumero", max_length=20, required=False)
    vin = forms.CharField(label="VIN", max_length=17, required=False)
    merkki = forms.CharField(label="Merkki", max_length=100, required=False)
    malli = forms.CharField(label="Malli", max_length=100, required=False)
    mallitarkenne = forms.CharField(label="Mallitarkenne", max_length=200, required=False)
    vuosimalli = forms.IntegerField(label="Vuosimalli", required=False, min_value=1900, max_value=2100)
    ensirekisterointi = forms.DateField(label="Ensirekisteröinti", required=False, widget=PvmSyote())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hinta"].required = False
        self.fields["hinta"].label = "Vaihtohinta (€)"
        self.order_fields(
            ["rekisterinumero", "vin", "merkki", "malli", "mallitarkenne", "vuosimalli", "ensirekisterointi", "km"]
        )

    def clean_rekisterinumero(self):
        return logiikka.normalisoi_rekisteri(self.cleaned_data.get("rekisterinumero"))

    def clean_vin(self):
        return (self.cleaned_data.get("vin") or "").strip().upper()

    TUNNISTAVAT = ("rekisterinumero", "vin", "merkki", "malli", "hinta")

    def has_changed(self):
        """Rivi on täytetty vain, jos siinä on ajoneuvo tai hinta (oletusvalinnat eivät riitä)."""
        return any(self[k].data not in (None, "") for k in self.TUNNISTAVAT)

    def clean(self):
        data = super().clean()
        if not self.has_changed():
            return data
        for kentta in ("merkki", "malli", "hinta"):
            if data.get(kentta) in (None, ""):
                self.add_error(kentta, "Pakollinen vaihtoajoneuvolle.")
        if not (data.get("rekisterinumero") or data.get("vin")):
            self.add_error("rekisterinumero", "Anna rekisterinumero tai VIN.")
        return data


VaihtoFormset = forms.formset_factory(VaihtoLomake, extra=2)


class MyyntitarjousLomake(Suomeksi, forms.ModelForm):
    """Myyntitarjous asiakkaalle: hinta, toimistokulut ja valinnainen vaihtoajoneuvo."""

    hinta = EuroKentta(label="Tarjoushinta (€, sis. alv)", required=True)
    toimistokulut = EuroKentta(label="Toimistokulut (€)")
    vaihto_hinta = EuroKentta(label="Vaihtohinta (€)")
    vaihto_jaannosvelka = EuroKentta(label="Vaihtoauton jäännösvelka (€)")

    class Meta:
        model = Myyntitarjous
        fields = [
            "asiakas",
            "vp_nimi",
            "vp_puhelin",
            "vp_sahkoposti",
            "pvm",
            "voimassa",
            "hinta",
            "toimistokulut",
            "vaihto_rekisterinumero",
            "vaihto_merkki",
            "vaihto_malli",
            "vaihto_km",
            "vaihto_hinta",
            "vaihto_jaannosvelka",
            "lisatiedot",
        ]
        widgets = {"pvm": PvmSyote(), "voimassa": PvmSyote(), "lisatiedot": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asiakas"].queryset = _yritykset()
        self.fields["vp_nimi"].required = False
        self.fields["pvm"].initial = timezone.localdate()

    def clean_toimistokulut(self):
        return self.cleaned_data.get("toimistokulut") or 0

    def clean_vaihto_jaannosvelka(self):
        return self.cleaned_data.get("vaihto_jaannosvelka") or 0

    def clean_vaihto_rekisterinumero(self):
        return logiikka.normalisoi_rekisteri(self.cleaned_data.get("vaihto_rekisterinumero"))

    def clean(self):
        data = super().clean()
        if not data.get("asiakas") and not data.get("vp_nimi"):
            self.add_error("vp_nimi", "Valitse asiakas rekisteristä tai anna nimi.")
        vaihto = any(data.get(k) for k in ("vaihto_rekisterinumero", "vaihto_merkki", "vaihto_malli"))
        if vaihto and data.get("vaihto_hinta") is None:
            self.add_error("vaihto_hinta", "Anna vaihtoajoneuvon hinta.")
        if data.get("vaihto_hinta") is not None and not data.get("vaihto_merkki"):
            self.add_error("vaihto_merkki", "Anna vaihtoajoneuvon merkki.")
        if data.get("vaihto_jaannosvelka") and data.get("vaihto_hinta") is None:
            self.add_error("vaihto_jaannosvelka", "Jäännösvelka vain vaihtoajoneuvolle.")
        return data
