"""AutoERP-asetukset.

Kaikki ympäristökohtainen luetaan ympäristömuuttujista (ks. README ja render.yaml).
"""

import os
import sys
import tempfile
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(nimi, oletus=False):
    arvo = os.environ.get(nimi)
    if arvo is None:
        return oletus
    return arvo.strip().lower() in ("1", "true", "yes", "on", "kylla")


DEBUG = _bool("DEBUG", False)
# `manage.py test`: ei HTTPS-uudelleenohjausta, ei R2:ta eikä collectstaticia.
TESTI = len(sys.argv) > 1 and sys.argv[1] == "test"

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not (DEBUG or TESTI):
        raise RuntimeError("SECRET_KEY puuttuu. Aseta se ympäristömuuttujaan (tai DEBUG=1 kehityksessä).")
    SECRET_KEY = "kehitysavain-ei-tuotantoon"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
# Render asettaa palvelun osoitteen automaattisesti.
RENDER_HOST = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1")]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "liikkeet",
    "autot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "liikkeet.middleware.LiikeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "autot.context_processors.valinnat",
            ],
            "builtins": ["autot.templatetags.autoerp"],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgres://autoerp:autoerp@localhost:5432/autoerp",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "liikkeet.Kayttaja"
LOGIN_URL = "kirjaudu"
LOGIN_REDIRECT_URL = "autot:etusivu"
LOGOUT_REDIRECT_URL = "kirjaudu"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "fi"
TIME_ZONE = "Europe/Helsinki"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- Staattiset tiedostot (WhiteNoise) ja kuvat (Cloudflare R2) ----------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

R2_BUCKET = "" if TESTI else os.environ.get("R2_BUCKET", "")
if TESTI:
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="autoerp-testi-"))

if R2_BUCKET:
    # Cloudflare R2 on S3-yhteensopiva. Ämpäri pidetään yksityisenä: kuvat näytetään
    # lyhytikäisillä allekirjoitetuilla osoitteilla sen jälkeen, kun näkymä on
    # tarkistanut, että kuva kuuluu käyttäjän liikkeelle.
    _tiedostot = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": R2_BUCKET,
            "endpoint_url": os.environ.get("R2_ENDPOINT_URL")
            or f"https://{os.environ.get('R2_ACCOUNT_ID', '')}.r2.cloudflarestorage.com",
            "access_key": os.environ.get("R2_ACCESS_KEY_ID"),
            "secret_key": os.environ.get("R2_SECRET_ACCESS_KEY"),
            "region_name": "auto",
            "signature_version": "s3v4",
            "addressing_style": "virtual",
            "default_acl": None,
            "querystring_auth": True,
            "querystring_expire": 3600,
            "file_overwrite": False,
        },
    }
else:
    _tiedostot = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

STORAGES = {
    "default": _tiedostot,
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not (DEBUG or TESTI)
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

# Kehityksessä ja testeissä WhiteNoise hakee tiedostot suoraan sovelluksista (ei collectstaticia).
WHITENOISE_USE_FINDERS = DEBUG or TESTI
WHITENOISE_AUTOREFRESH = DEBUG or TESTI

DATA_UPLOAD_MAX_MEMORY_SIZE = 40 * 1024 * 1024  # useita puhelinkuvia kerralla
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------- Tietoturva tuotannossa ----------

if not (DEBUG or TESTI):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = _bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True

# HSTS-alidomainit ja preload-lista riippuvat omasta verkkotunnuksesta: päätetään käyttöönotossa.
SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

if TESTI:
    # Nopeampi salasanatiiviste ja hiljaisemmat lokit testeissä
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    LOGGING["loggers"] = {"django.request": {"level": "ERROR"}}
