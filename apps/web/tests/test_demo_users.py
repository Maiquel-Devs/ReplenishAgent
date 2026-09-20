import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.web.authorization import ADMINISTRATION_PERMISSIONS
from apps.web.demo import DEMO_PASSWORD


pytestmark = pytest.mark.django_db


@pytest.fixture
def demo_users(settings):
    settings.DEBUG = True
    call_command("seed_demo_users", verbosity=0)
    user_model = get_user_model()
    return {
        username: user_model.objects.get(username=username)
        for username in ("admin", "usuario")
    }


@pytest.mark.parametrize("username", ("admin", "usuario"))
def test_demo_credentials_can_authenticate(client, demo_users, username):
    response = client.post(
        reverse("login"),
        {"username": username, "password": DEMO_PASSWORD},
    )

    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(demo_users[username].pk)


def test_demo_passwords_are_hashed(demo_users):
    for user in demo_users.values():
        assert user.password != DEMO_PASSWORD
        assert user.check_password(DEMO_PASSWORD)


def test_demo_admin_accesses_administration_and_ai_configuration(
    client,
    demo_users,
):
    admin = demo_users["admin"]
    client.force_login(admin)

    assert all(admin.has_perm(name) for name in ADMINISTRATION_PERMISSIONS)
    assert client.get(reverse("web:administration_overview")).status_code == 200
    assert client.get(reverse("web:ai_configuration")).status_code == 200


def test_demo_user_cannot_access_administration_or_ai_configuration(
    client,
    demo_users,
):
    user = demo_users["usuario"]
    client.force_login(user)

    assert not any(user.has_perm(name) for name in ADMINISTRATION_PERMISSIONS)
    assert client.get(reverse("web:administration_overview")).status_code == 403
    assert client.get(reverse("web:ai_configuration")).status_code == 403


def test_demo_seed_is_blocked_in_production(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError, match="only be created"):
        call_command("seed_demo_users", verbosity=0)

    assert (
        not get_user_model().objects.filter(username__in=("admin", "usuario")).exists()
    )
