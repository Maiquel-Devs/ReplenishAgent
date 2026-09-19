"""URL configuration for the ReplenishAgent project."""
from django.contrib import admin
from django.urls import include, path

from config.views import health


urlpatterns = [
    path("", include("apps.web.urls")),
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
]
