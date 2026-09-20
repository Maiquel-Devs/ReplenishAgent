"""URL configuration for the ReplenishAgent project."""
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path

from apps.web.auth_views import ReplenishLoginView
from config.views import health


urlpatterns = [
    path("", include("apps.web.urls")),
    path("conta/entrar/", ReplenishLoginView.as_view(), name="login"),
    path("conta/sair/", LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
]
