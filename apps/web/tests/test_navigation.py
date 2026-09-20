import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.web.authorization import (
    ADMINISTRATION_PERMISSIONS,
    CONFIGURE_AI_PERMISSION,
    REVIEW_PROPOSAL_PERMISSION,
    VIEW_AGENT_AUDIT_PERMISSION,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(username="navigation-operator")


def grant_permissions(user, *permission_names):
    for permission_name in permission_names:
        app_label, codename = permission_name.split(".", maxsplit=1)
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )
        )
    return user


@pytest.fixture
def administrator():
    user = get_user_model().objects.create_user(username="navigation-admin")
    return grant_permissions(user, *ADMINISTRATION_PERMISSIONS)


def test_anonymous_user_is_redirected_without_application_sidebar(client):
    response = client.get(reverse("web:dashboard"), follow=True)
    content = response.content.decode()

    assert response.redirect_chain[0][0].startswith(reverse("login"))
    assert 'class="app-sidebar' not in content
    assert 'id="mobileNavigation"' not in content


def test_operator_sees_main_and_operation_navigation_only(client, operator):
    client.force_login(operator)

    response = client.get(reverse("web:agent_chat"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Principal" in content
    assert "Operação" in content
    assert reverse("web:dashboard") in content
    assert reverse("web:agent_chat") in content
    assert reverse("web:product_list") in content
    assert reverse("web:proposal_list") in content
    assert "Administração" not in content
    assert reverse("web:administration_overview") not in content
    assert reverse("web:ai_configuration") not in content
    assert reverse("web:agent_audit_list") not in content
    assert reverse("web:pending_proposals") not in content
    assert "navigation-operator" in content
    assert "Operador" in content
    assert ">Conta</h2>" not in content
    assert 'id="account-title-' not in content


def test_administrator_sees_permission_based_administration_navigation(
    client,
    administrator,
):
    client.force_login(administrator)

    response = client.get(reverse("web:dashboard"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Administração" in content
    assert reverse("web:administration_overview") in content
    assert reverse("web:ai_configuration") in content
    assert reverse("web:agent_audit_list") in content
    assert reverse("web:pending_proposals") in content
    assert "navigation-admin" in content
    assert "Administrador" in content


@pytest.mark.parametrize(
    ("permission_name", "allowed_url_name", "hidden_url_names"),
    [
        (
            CONFIGURE_AI_PERMISSION,
            "web:ai_configuration",
            ("web:agent_audit_list", "web:pending_proposals"),
        ),
        (
            VIEW_AGENT_AUDIT_PERMISSION,
            "web:agent_audit_list",
            ("web:ai_configuration", "web:pending_proposals"),
        ),
        (
            REVIEW_PROPOSAL_PERMISSION,
            "web:pending_proposals",
            ("web:ai_configuration", "web:agent_audit_list"),
        ),
    ],
)
def test_each_administrative_permission_shows_only_matching_navigation(
    client,
    permission_name,
    allowed_url_name,
    hidden_url_names,
):
    user = get_user_model().objects.create_user(
        username=f"navigation-{permission_name}",
    )
    grant_permissions(user, permission_name)
    client.force_login(user)

    response = client.get(reverse("web:dashboard"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Administração" in content
    assert reverse("web:administration_overview") in content
    assert reverse(allowed_url_name) in content
    for hidden_url_name in hidden_url_names:
        assert reverse(hidden_url_name) not in content
    assert client.get(reverse("web:administration_overview")).status_code == 200
    assert client.get(reverse(allowed_url_name)).status_code == 200


@pytest.mark.parametrize(
    ("url_name", "label"),
    [
        ("web:administration_overview", "Visão geral"),
        ("web:ai_configuration", "Configuração da IA"),
        ("web:agent_audit_list", "Auditoria"),
        ("web:pending_proposals", "Propostas pendentes"),
    ],
)
def test_administration_navigation_has_one_coherent_active_item(
    client,
    administrator,
    url_name,
    label,
):
    client.force_login(administrator)
    url = reverse(url_name)

    response = client.get(url)
    content = response.content.decode()

    active_link = (
        f'class="app-nav-link active" href="{url}" '
        f'aria-current="page">{label}</a>'
    )
    assert response.status_code == 200
    assert content.count(active_link) == 2
    assert content.count('class="app-nav-link active"') == 2


def test_navigation_renders_desktop_mobile_and_active_item(client, operator):
    client.force_login(operator)

    response = client.get(reverse("web:agent_chat"))
    content = response.content.decode()

    assert 'class="app-sidebar d-none d-lg-block"' in content
    assert 'id="mobileNavigation"' in content
    assert 'data-bs-toggle="offcanvas"' in content
    assert (
        f'class="app-nav-link app-nav-link-agent active" '
        f'href="{reverse("web:agent_chat")}" aria-current="page"'
    ) in content


def test_sidebar_logout_remains_post_with_csrf(client, operator):
    client.force_login(operator)

    response = client.get(reverse("web:dashboard"))
    content = response.content.decode()

    assert f'<form method="post" action="{reverse("logout")}"' in content
    assert "csrfmiddlewaretoken" in content
    assert client.get(reverse("logout")).status_code == 405


def test_sidebar_logout_rejects_post_without_csrf(operator):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(operator)

    response = csrf_client.post(reverse("logout"))

    assert response.status_code == 403
