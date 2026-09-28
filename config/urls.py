from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path


@login_not_required
def terveys(request):
    """Renderin terveystarkistus: sovellus vastaa ja tietokanta on tavoitettavissa."""
    with connection.cursor() as kursori:
        kursori.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("terveys/", terveys, name="terveys"),
    path("", include("liikkeet.urls")),
    path("", include("autot.urls")),
]
