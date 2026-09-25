"""Uusi liike ja sen ensimmäinen ylläpitäjä (tuotannon käyttöönotto).

    python manage.py luo_liike --nimi "N247 Finland Oy" --sahkoposti admin@n247.fi --admin-nimi "Matti Meikäläinen"

Salasana kysytään, tai se luetaan ympäristömuuttujasta ADMIN_SALASANA.
Komento luo liikkeelle myös koodistot, varustekatalogin ja tehtäväpohjat.
"""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autot.perusdata import alusta_liike
from liikkeet.models import Kayttaja, Liike


class Command(BaseCommand):
    help = "Luo uuden liikkeen, sen perusdatan ja ylläpitäjän."

    def add_arguments(self, parser):
        parser.add_argument("--nimi", required=True)
        parser.add_argument("--y-tunnus", default="")
        parser.add_argument("--sahkoposti", required=True)
        parser.add_argument("--admin-nimi", default="Ylläpitäjä")

    def handle(self, *args, nimi, y_tunnus, sahkoposti, admin_nimi, **kwargs):
        sahkoposti = sahkoposti.strip().lower()
        if Kayttaja.objects.filter(sahkoposti__iexact=sahkoposti).exists():
            raise CommandError(f"Sähköposti {sahkoposti} on jo käytössä.")
        salasana = os.environ.get("ADMIN_SALASANA") or getpass.getpass("Ylläpitäjän salasana: ")
        try:
            validate_password(salasana)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages)) from e

        with transaction.atomic():
            liike = Liike.objects.create(nimi=nimi, y_tunnus=y_tunnus)
            alusta_liike(liike)
            Kayttaja.objects.create_user(sahkoposti, salasana, liike=liike, nimi=admin_nimi, rooli="admin")
        self.stdout.write(self.style.SUCCESS(f'Liike "{nimi}" luotu. Ylläpitäjä: {sahkoposti}'))
