from django.urls import path

from .views import autot, hallinta, kortti, raportit, tehtavat

app_name = "autot"

urlpatterns = [
    path("", tehtavat.etusivu, name="etusivu"),
    # Autot
    path("autot/", autot.lista, name="lista"),
    path("autot/uusi/", autot.uusi, name="uusi"),
    path("autot/tarkista/", autot.tarkista, name="tarkista"),
    path("autot/<int:kid>/", kortti.kortti, name="kortti"),
    path("autot/<int:kid>/v/<slug:valilehti>/", kortti.valilehti, name="valilehti"),
    path("autot/<int:kid>/tila/", kortti.vaihda_tila, name="vaihda_tila"),
    path("autot/<int:kid>/palaa/", kortti.palaa, name="palaa"),
    path("autot/<int:kid>/ajoneuvo/", kortti.tallenna_ajoneuvo, name="tallenna_ajoneuvo"),
    path("autot/<int:kid>/kauppa/", kortti.tallenna_kauppa, name="tallenna_kauppa"),
    path("autot/<int:kid>/kulu/", kortti.lisaa_kulu, name="lisaa_kulu"),
    path("autot/<int:kid>/kulu/<int:kulu_id>/poista/", kortti.poista_kulu, name="poista_kulu"),
    path("autot/<int:kid>/kunto/<slug:vaihe>/", kortti.tallenna_kunto, name="tallenna_kunto"),
    path("autot/<int:kid>/rengas/", kortti.lisaa_rengas, name="lisaa_rengas"),
    path("autot/<int:kid>/rengas/<int:rid>/poista/", kortti.poista_rengas, name="poista_rengas"),
    path("autot/<int:kid>/vaurio/", kortti.lisaa_vaurio, name="lisaa_vaurio"),
    path("autot/<int:kid>/vaurio/<int:vid>/korjattu/", kortti.vaurio_korjattu, name="vaurio_korjattu"),
    path("autot/<int:kid>/kuvat/", kortti.lataa_kuvat, name="lataa_kuvat"),
    path("autot/<int:kid>/varusteet/", kortti.tallenna_varusteet, name="tallenna_varusteet"),
    path("autot/<int:kid>/varusteet/kopioi/", kortti.kopioi_varusteet, name="kopioi_varusteet"),
    path("autot/<int:kid>/tehtava/", kortti.lisaa_tehtava, name="lisaa_tehtava"),
    path("autot/<int:kid>/tehtava/<int:tid>/poista/", kortti.poista_tehtava, name="poista_tehtava"),
    # Kuvat
    path("kuva/<int:kuva_id>/", kortti.nayta_kuva, name="kuva"),
    path("kuva/<int:kuva_id>/<slug:koko>/", kortti.nayta_kuva, name="kuva_koko"),
    path("kuva/<int:kuva_id>/toiminto/paakuva/", kortti.aseta_paakuva, name="aseta_paakuva"),
    path("kuva/<int:kuva_id>/toiminto/tyyppi/", kortti.vaihda_kuvatyyppi, name="vaihda_kuvatyyppi"),
    path("kuva/<int:kuva_id>/toiminto/siirra/<slug:suunta>/", kortti.siirra_kuva, name="siirra_kuva"),
    path("kuva/<int:kuva_id>/toiminto/poista/", kortti.poista_kuva, name="poista_kuva"),
    # Tehtävät
    path("tehtavat/", tehtavat.lista, name="tehtavat"),
    path("tehtavat/<int:tid>/kuittaa/", tehtavat.kuittaa, name="kuittaa"),
    # Hallinta
    path("yritykset/", hallinta.yritykset, name="yritykset"),
    path("yritykset/<int:yid>/", hallinta.yritys, name="yritys"),
    path("hallinta/kayttajat/", hallinta.kayttajat, name="kayttajat"),
    path("hallinta/varusteet/", hallinta.varusteet, name="varusteet"),
    path("hallinta/tehtavapohjat/", hallinta.tehtavapohjat, name="tehtavapohjat"),
    path("hallinta/asetukset/", hallinta.asetukset, name="asetukset"),
    # Raportit
    path("raportit/", raportit.index, name="raportit"),
]
