"""Näkymien yhteiset apufunktiot."""

import functools

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def on_htmx(request):
    return request.headers.get("HX-Request") == "true"


def rooli_vaaditaan(*roolit):
    """@rooli_vaaditaan('talous'). Ylläpitäjä pääsee aina."""

    def koriste(nakyma):
        @functools.wraps(nakyma)
        def kaaritty(request, *args, **kwargs):
            if request.user.rooli != "admin" and request.user.rooli not in roolit:
                raise PermissionDenied
            return nakyma(request, *args, **kwargs)

        return kaaritty

    return koriste


def turvallinen_paluu(request, osoite, oletus):
    """Palaa vain oman palvelun osoitteisiin (ei avointa uudelleenohjausta)."""
    if osoite and url_has_allowed_host_and_scheme(
        osoite, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(osoite)
    return redirect(oletus)


def kortille(kierto_id, valilehti=None):
    osoite = reverse("autot:kortti", args=[kierto_id])
    if valilehti:
        osoite += f"?v={valilehti}"
    return redirect(osoite)
