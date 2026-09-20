from __future__ import annotations

import os
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.urls import reverse


SETTINGS_PATH = Path(__file__).resolve().parents[1] / "settings.py"
BASE_ENVIRONMENT = {
    "DJANGO_SECRET_KEY": "test-secret-key",
    "POSTGRES_DB": "test-db",
    "POSTGRES_USER": "test-user",
    "POSTGRES_PASSWORD": "test-password",
}


def load_settings(**overrides):
    environment = BASE_ENVIRONMENT | overrides
    with patch.dict(os.environ, environment, clear=True):
        return runpy.run_path(str(SETTINGS_PATH))


def test_development_http_defaults_remain_simple_and_safe():
    configured = load_settings(DJANGO_DEBUG="True")

    assert configured["DEBUG"] is True
    assert configured["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1"]
    assert configured["CSRF_TRUSTED_ORIGINS"] == []
    assert configured["SESSION_COOKIE_SECURE"] is False
    assert configured["CSRF_COOKIE_SECURE"] is False
    assert configured["SECURE_SSL_REDIRECT"] is False
    assert configured["SECURE_HSTS_SECONDS"] == 0
    assert "SECURE_PROXY_SSL_HEADER" not in configured


def test_production_https_configuration_uses_secure_defaults():
    configured = load_settings(
        DJANGO_DEBUG="False",
        DJANGO_ALLOWED_HOSTS="app.example.com, admin.example.com ",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://app.example.com",
        DJANGO_HTTPS_ENABLED="True",
        DJANGO_TRUST_PROXY_SSL_HEADER="True",
    )

    assert configured["DEBUG"] is False
    assert configured["ALLOWED_HOSTS"] == [
        "app.example.com",
        "admin.example.com",
    ]
    assert configured["CSRF_TRUSTED_ORIGINS"] == [
        "https://app.example.com"
    ]
    assert configured["SESSION_COOKIE_SECURE"] is True
    assert configured["CSRF_COOKIE_SECURE"] is True
    assert configured["SECURE_SSL_REDIRECT"] is True
    assert configured["SECURE_HSTS_SECONDS"] == 3600
    assert configured["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is False
    assert configured["SECURE_HSTS_PRELOAD"] is False
    assert configured["SECURE_CONTENT_TYPE_NOSNIFF"] is True
    assert configured["X_FRAME_OPTIONS"] == "DENY"
    assert configured["SECURE_PROXY_SSL_HEADER"] == (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )


def test_invalid_security_environment_value_fails_closed():
    with pytest.raises(ImproperlyConfigured, match="must be a boolean"):
        load_settings(DJANGO_HTTPS_ENABLED="sometimes")


def test_secret_key_is_required_from_environment():
    environment = BASE_ENVIRONMENT.copy()
    environment.pop("DJANGO_SECRET_KEY")

    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(KeyError, match="DJANGO_SECRET_KEY"):
            runpy.run_path(str(SETTINGS_PATH))


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=None,
)
def test_http_request_is_redirected_when_ssl_redirect_is_enabled(client):
    response = client.get(reverse("health"))

    assert response.status_code == 301
    assert response["Location"].startswith("https://")


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
def test_trusted_proxy_https_header_prevents_redirect_loop(client):
    response = client.get(
        reverse("health"),
        HTTP_X_FORWARDED_PROTO="https",
    )

    assert response.status_code == 200


@override_settings(
    SECURE_HSTS_SECONDS=3600,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
    SECURE_CONTENT_TYPE_NOSNIFF=True,
    X_FRAME_OPTIONS="DENY",
)
def test_secure_response_contains_security_headers(client):
    response = client.get(reverse("health"), secure=True)

    assert response.status_code == 200
    assert response["Strict-Transport-Security"] == (
        "max-age=3600; includeSubDomains; preload"
    )
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"


@override_settings(DEBUG=False)
def test_production_not_found_response_does_not_expose_traceback(client):
    response = client.get("/missing-page/")

    assert response.status_code == 404
    assert "Traceback" not in response.content.decode()


@pytest.mark.django_db
@override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
def test_authentication_cookies_are_secure_when_enabled(client):
    get_user_model().objects.create_user(
        username="secure-cookie-user",
        password="test-password",
    )

    login_page = client.get(reverse("login"))
    login_response = client.post(
        reverse("login"),
        {"username": "secure-cookie-user", "password": "test-password"},
    )

    assert login_page.cookies["csrftoken"]["secure"] is True
    assert login_response.cookies["sessionid"]["secure"] is True
