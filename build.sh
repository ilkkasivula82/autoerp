#!/usr/bin/env bash
# Renderin build-vaihe: riippuvuudet ja staattiset tiedostot.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
