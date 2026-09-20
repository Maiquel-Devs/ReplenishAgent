from __future__ import annotations

import logging
import time
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from apps.web.auth_forms import INVALID_CREDENTIALS_MESSAGE


pytestmark = pytest.mark.django_db


@pytest.fixture
def login_user():
    return get_user_model().objects.create_user(
        username="login-user",
        password="correct-password",
    )


def login_payload(username="login-user", password="correct-password", **extra):
    return {
        "username": username,
        "password": password,
        **extra,
    }


def test_login_page_uses_replenish_agent_identity_without_old_visuals(client):
    response = client.get(reverse("login"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "ReplenishAgent" in content
    assert "Análise e planejamento seguro de reposição" in content
    assert 'class="login-mark' not in content
    assert ">R<" not in content
    assert "Operações determinísticas de estoque e reposição" not in content


@override_settings(DEBUG=True)
def test_demo_credentials_are_rendered_in_development(client):
    response = client.get(reverse("login"))
    content = response.content.decode()

    assert "Credenciais de Demonstração:" in content
    assert "admin / 123456" in content
    assert "usuario / 123456" in content


@override_settings(DEBUG=False)
def test_demo_credentials_are_never_rendered_in_production(client):
    response = client.get(reverse("login"))
    content = response.content.decode()

    assert "Credenciais de Demonstração:" not in content
    assert "admin / 123456" not in content
    assert "usuario / 123456" not in content


def test_valid_login_redirects_to_agent(client, login_user):
    response = client.post(reverse("login"), login_payload())

    assert response.status_code == 302
    assert response.url == reverse("web:agent_chat")
    assert client.session["_auth_user_id"] == str(login_user.pk)


def test_invalid_password_uses_generic_error(client, login_user):
    response = client.post(
        reverse("login"),
        login_payload(password="wrong-password"),
    )

    assert response.status_code == 200
    assert INVALID_CREDENTIALS_MESSAGE in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_unknown_user_has_same_generic_error(client):
    response = client.post(
        reverse("login"),
        login_payload(username="unknown-user", password="wrong-password"),
    )

    assert response.status_code == 200
    assert INVALID_CREDENTIALS_MESSAGE in response.content.decode()
    assert "inexistente" not in response.content.decode().lower()
    assert "incorreta" not in response.content.decode().lower()


def test_anonymous_user_returns_to_requested_page_after_login(client, login_user):
    protected_url = reverse("web:product_list")
    redirect_response = client.get(protected_url)

    assert redirect_response.status_code == 302
    assert redirect_response.url == (f"{reverse('login')}?next={protected_url}")

    response = client.post(
        reverse("login"),
        login_payload(next=protected_url),
    )

    assert response.status_code == 302
    assert response.url == protected_url


def test_external_next_url_is_rejected(client, login_user):
    response = client.post(
        reverse("login"),
        login_payload(next="https://attacker.example/phishing"),
    )

    assert response.status_code == 302
    assert response.url == reverse("web:agent_chat")


def test_logout_requires_post_and_ends_session(client, login_user):
    client.force_login(login_user)

    assert client.get(reverse("logout")).status_code == 405

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert response.url == reverse("login")
    assert "_auth_user_id" not in client.session


def test_login_post_enforces_csrf(login_user):
    csrf_client = Client(enforce_csrf_checks=True)

    response = csrf_client.post(reverse("login"), login_payload())

    assert response.status_code == 403
    assert "_auth_user_id" not in csrf_client.session


@override_settings(
    AXES_FAILURE_LIMIT=3,
    AXES_COOLOFF_TIME=timedelta(minutes=5),
)
def test_repeated_failures_temporarily_block_login(client, login_user):
    for _ in range(3):
        client.post(
            reverse("login"),
            login_payload(password="wrong-password"),
            REMOTE_ADDR="192.0.2.10",
        )

    response = client.post(
        reverse("login"),
        login_payload(),
        REMOTE_ADDR="192.0.2.10",
    )

    assert response.status_code == 429
    assert "Aguarde alguns minutos" in response.content.decode()
    assert int(response["Retry-After"]) > 0
    assert "_auth_user_id" not in client.session


@override_settings(
    AXES_FAILURE_LIMIT=2,
    AXES_COOLOFF_TIME=timedelta(minutes=5),
)
def test_forwarded_header_cannot_bypass_lockout(client, login_user):
    for forwarded_ip in ("198.51.100.1", "198.51.100.2"):
        client.post(
            reverse("login"),
            login_payload(password="wrong-password"),
            REMOTE_ADDR="192.0.2.20",
            HTTP_X_FORWARDED_FOR=forwarded_ip,
        )

    response = client.post(
        reverse("login"),
        login_payload(),
        REMOTE_ADDR="192.0.2.20",
        HTTP_X_FORWARDED_FOR="203.0.113.99",
    )

    assert response.status_code == 429


@override_settings(
    AXES_FAILURE_LIMIT=1,
    AXES_COOLOFF_TIME=timedelta(seconds=1),
)
def test_lockout_expires_after_cooloff(client, login_user):
    client.post(
        reverse("login"),
        login_payload(password="wrong-password"),
        REMOTE_ADDR="192.0.2.30",
    )
    assert (
        client.post(
            reverse("login"),
            login_payload(),
            REMOTE_ADDR="192.0.2.30",
        ).status_code
        == 429
    )

    time.sleep(1.1)
    response = client.post(
        reverse("login"),
        login_payload(),
        REMOTE_ADDR="192.0.2.30",
    )

    assert response.status_code == 302


def test_password_is_not_written_to_logs(client, caplog):
    secret = "never-log-this-password"

    with caplog.at_level(logging.DEBUG):
        client.post(
            reverse("login"),
            login_payload(username="missing", password=secret),
        )

    assert secret not in caplog.text


def test_health_check_remains_public(client):
    response = client.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
