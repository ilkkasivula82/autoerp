from django import forms
from django.contrib.auth.forms import AuthenticationForm


class KirjautumisLomake(AuthenticationForm):
    """Sähköposti ei ole kirjainkokoriippuvainen."""

    username = forms.EmailField(
        label="Sähköposti", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"})
    )

    error_messages = {
        "invalid_login": "Väärä sähköposti tai salasana.",
        "inactive": "Käyttäjätunnus ei ole käytössä.",
    }

    def clean(self):
        if self.cleaned_data.get("username"):
            self.cleaned_data["username"] = self.cleaned_data["username"].strip().lower()
        return super().clean()
