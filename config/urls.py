"""URL configuration for the ReplenishAgent project."""
from django.contrib import admin
from django.urls import path

from config.views import health


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
]
