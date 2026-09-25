"""Testien apufunktiot: liike täysine tietoineen."""

import io
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from autot.models import (
    Ajoneuvo,
    AjoneuvonVaruste,
    Kierto,
    Koodi,
    Kulu,
    Kuntoraportti,
    Kuva,
    Muutosloki,
    Rengassarja,
    Tehtava,
    Tehtavapohja,
    Tilahistoria,
    Varuste,
    Vaurio,
    Yritys,
)
from autot.perusdata import alusta_liike
from liikkeet.models import Kayttaja, Liike
from liikkeet.rajaus import liike_kaytossa

SALASANA = "salasana-123"


def kuvatiedosto(nimi="kuva.jpg", koko=(40, 30)):
    puskuri = io.BytesIO()
    Image.new("RGB", koko, (200, 30, 30)).save(puskuri, "JPEG")
    return SimpleUploadedFile(nimi, puskuri.getvalue(), content_type="image/jpeg")


def luo_liike(nimi, tunnus, rek="ABC-123", vin="VIN0000000000001"):
    """Liike, jolla on käyttäjät ja rivi jokaiseen liikekohtaiseen tauluun."""
    liike = Liike.objects.create(nimi=nimi)
    alusta_liike(liike)
    admin = Kayttaja.objects.create_user(
        f"admin@{tunnus}.fi", SALASANA, liike=liike, nimi=f"{nimi} Admin", rooli="admin"
    )
    myyja = Kayttaja.objects.create_user(
        f"myynti@{tunnus}.fi", SALASANA, liike=liike, nimi=f"{nimi} Myyjä", rooli="myynti"
    )
    with liike_kaytossa(liike):
        yritys = Yritys.objects.create(nimi=f"{nimi} Toimittaja Oy")
        asiakas = Yritys.objects.create(nimi=f"{nimi} Asiakas Oy")
        ajoneuvo = Ajoneuvo.objects.create(rekisterinumero=rek, vin=vin, merkki="Volvo", malli=f"Malli-{tunnus}")
        varuste = Varuste.objects.first()
        AjoneuvonVaruste.objects.create(ajoneuvo=ajoneuvo, varuste=varuste)
        kierto = Kierto.objects.create(
            ajoneuvo=ajoneuvo,
            tila="myynnissa",
            toimittaja=yritys,
            ostohinta=1_000_000,
            pyyntihinta=1_300_000,
            luonut=admin,
        )
        Tilahistoria.objects.create(kierto=kierto, uusi_tila="myynnissa", kayttaja=admin)
        kulu = Kulu.objects.create(kierto=kierto, tyyppi="huolto", summa_veroton=12_300, kuvaus=f"Kulu {tunnus}")
        tehtava = Tehtava.objects.create(kierto=kierto, otsikko=f"Tehtävä {tunnus}", vastuu=myyja)
        rengas = Rengassarja.objects.create(kierto=kierto, tyyppi="kesa")
        raportti = Kuntoraportti.objects.create(kierto=kierto, vaihe="tarjous", avaimet=2)
        kuva = Kuva.objects.create(kierto=kierto, avain=f"liike_{liike.pk}/kierto_{kierto.pk}/x.jpg", paakuva=True)
        vaurio = Vaurio.objects.create(kierto=kierto, kohta=f"Vaurio {tunnus}", kuva=kuva)
        Muutosloki.objects.create(
            kayttaja=admin, kohde="kierto", kohde_id=kierto.pk, kentta="ostohinta", uusi=f"Loki {tunnus}"
        )
        return SimpleNamespace(
            liike=liike,
            admin=admin,
            myyja=myyja,
            yritys=yritys,
            asiakas=asiakas,
            ajoneuvo=ajoneuvo,
            varuste=varuste,
            kategoria=varuste.kategoria,
            kierto=kierto,
            kulu=kulu,
            tehtava=tehtava,
            rengas=rengas,
            raportti=raportti,
            kuva=kuva,
            vaurio=vaurio,
            koodi=Koodi.objects.first(),
            pohja=Tehtavapohja.objects.first(),
        )
