from django.contrib.auth import views as auth_views
from django.urls import path

from .forms import KirjautumisLomake

urlpatterns = [
    path(
        "kirjaudu/",
        auth_views.LoginView.as_view(
            template_name="registration/kirjaudu.html",
            authentication_form=KirjautumisLomake,
            redirect_authenticated_user=True,
        ),
        name="kirjaudu",
    ),
    path("kirjaudu-ulos/", auth_views.LogoutView.as_view(), name="kirjaudu_ulos"),
]
