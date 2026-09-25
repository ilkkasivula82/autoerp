"""Kuvien tallennus.

Tuotannossa tiedostot menevät Cloudflare R2:een (django-storages, S3-yhteensopiva),
kehityksessä ja testeissä paikalliselle levylle (MEDIA_ROOT). Valinta tehdään
asetuksissa (R2_BUCKET), joten tämä moduuli käyttää vain Djangon default_storagea.

Avaimet ovat muotoa  liike_<id>/kierto_<id>/<uuid>.jpg  ja pikkukuva  ..._t.jpg.
"""

import io
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_KOKO = 2000  # pidemmän sivun pikselit täysikokoisessa kuvassa
PIKKU_KOKO = 480  # listanäkymän pikkukuva


class KuvaVirhe(ValueError):
    pass


def pikkukuva_avain(avain):
    return avain[:-4] + "_t.jpg"


def _jpeg(img, laatu):
    puskuri = io.BytesIO()
    img.save(puskuri, "JPEG", quality=laatu, optimize=True)
    return ContentFile(puskuri.getvalue())


def tallenna_kuva(tiedosto, liike_id, kierto_id):
    """Kääntää EXIF:n mukaan, pienentää ja tallentaa JPEG:nä. Palauttaa avaimen."""
    try:
        img = Image.open(tiedosto)
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise KuvaVirhe("Tiedosto ei ole luettava kuva.") from e

    avain = f"liike_{liike_id}/kierto_{kierto_id}/{uuid.uuid4().hex}.jpg"
    iso = img.copy()
    iso.thumbnail((MAX_KOKO, MAX_KOKO))
    tallennettu = default_storage.save(avain, _jpeg(iso, 85))

    pieni = img.copy()
    pieni.thumbnail((PIKKU_KOKO, PIKKU_KOKO))
    default_storage.save(pikkukuva_avain(tallennettu), _jpeg(pieni, 80))
    return tallennettu


def poista(avain):
    for a in (avain, pikkukuva_avain(avain)):
        try:
            default_storage.delete(a)
        except Exception:  # tiedosto voi olla jo poistettu
            pass


def paikallinen():
    """Onko tallennus paikallinen levy (kehitys/testit)? Silloin näkymä palvelee tiedoston itse."""
    return isinstance(default_storage, FileSystemStorage)


def osoite(avain):
    """R2: lyhytikäinen allekirjoitettu osoite yksityiseen ämpäriin."""
    return default_storage.url(avain)


def avaa(avain):
    return default_storage.open(avain, "rb")
