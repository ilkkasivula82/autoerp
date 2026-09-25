"""Lomakkeet.

Valintakenttien kyselyt (yritykset, käyttäjät, varusteet) asetetaan aina
__init__:ssä pyynnön aikana, jolloin ne rajautuvat käyttäjän liikkeeseen.
"""

from django import forms

from liikkeet.models import Kayttaja, Rooli

from . import logiikka
from .models import (
    Ajoneuvo,
    Kierto,
    Koodi,
    Kulu,
    Kuntoraportti,
    Rengassarja,
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
    heti_ostettu = forms.BooleanField(label="Ostettu heti (ohitetaan tarjousvaihe)", required=False)
    ostohinta = EuroKentta(label="Ostohinta (€)")

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
        if data.get("heti_ostettu") and data.get("ostohinta") is None:
            self.add_error("ostohinta", "Anna ostohinta, kun auto on ostettu heti.")
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
        summa = self.cleaned_data["summa"]
        if self.cleaned_data["summa_on"] == "verollinen":
            summa = logiikka.verottomaksi(summa, self.cleaned_data["alv_prosentti"])
        kulu.summa_veroton = summa
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
        fields = ["nimi", "y_tunnus", "tyyppi", "yhteyshenkilo", "puhelin", "sahkoposti", "huomiot"]
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


class LiikeLomake(forms.Form):
    nimi = forms.CharField(label="Nimi", max_length=200)
    y_tunnus = forms.CharField(label="Y-tunnus", max_length=20, required=False)
    alv_prosentti = ProsenttiKentta(
        label="Yleinen ALV-kanta (%)", max_digits=5, decimal_places=2, min_value=0, max_value=100
    )


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
