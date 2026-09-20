from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.agent.authorization import AGENT_WRITE_PERMISSION
from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.suppliers.models import ProductSupplier, Supplier
from apps.web.authorization import ADMINISTRATION_PERMISSIONS
from apps.web.demo import (
    DEMO_ADMIN_PERMISSIONS,
    DEMO_OPERATOR_PERMISSIONS,
    DEMO_PASSWORD,
)


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


@pytest.fixture
def pending_proposals():
    product = Product.objects.create(name="Review product", sku="REVIEW-ROLE")
    supplier = Supplier.objects.create(name="Review supplier")
    proposal_data = {
        "product": product,
        "supplier": supplier,
        "quantity": 2,
        "unit_price": Decimal("10.00"),
        "total_price": Decimal("20.00"),
        "risk_level": "LOW",
    }
    return (
        PurchaseProposal.objects.create(**proposal_data),
        PurchaseProposal.objects.create(**proposal_data),
    )


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


def test_demo_admin_accesses_all_administration_pages(client, demo_users):
    admin = demo_users["admin"]
    client.force_login(admin)

    assert all(admin.has_perm(name) for name in ADMINISTRATION_PERMISSIONS)
    assert client.get(reverse("web:administration_overview")).status_code == 200
    assert client.get(reverse("web:ai_configuration")).status_code == 200
    assert client.get(reverse("web:agent_audit_list")).status_code == 200
    assert client.get(reverse("web:pending_proposals")).status_code == 200

    dashboard = client.get(reverse("web:dashboard")).content.decode()
    assert "Visão geral" in dashboard
    assert "Configuração da IA" in dashboard
    assert "Auditoria" in dashboard
    assert "Propostas pendentes" in dashboard


def test_demo_admin_has_exact_application_permissions(demo_users):
    admin = demo_users["admin"]

    assert admin.is_active
    assert not admin.is_staff
    assert not admin.is_superuser
    assert admin.get_all_permissions() == set(DEMO_ADMIN_PERMISSIONS)


@pytest.mark.parametrize("username", ("admin", "usuario"))
@pytest.mark.parametrize(
    ("url_name", "action_label"),
    [
        ("web:product_list", "Novo produto"),
        ("web:supplier_list", "Novo fornecedor"),
        ("web:product_supplier_list", "Nova relação"),
        ("web:inventory_list", "Registrar movimentação"),
        ("web:movement_list", "Nova movimentação"),
        ("web:replenishment_analysis", "Analisar"),
        ("web:agent_chat", "Enviar"),
    ],
)
def test_demo_roles_see_operational_actions(
    client,
    demo_users,
    username,
    url_name,
    action_label,
):
    client.force_login(demo_users[username])

    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert action_label in response.content.decode()


def test_demo_operator_cannot_access_administration(client, demo_users):
    user = demo_users["usuario"]
    client.force_login(user)

    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert user.get_all_permissions() == set(DEMO_OPERATOR_PERMISSIONS)
    assert not user.has_perm(AGENT_WRITE_PERMISSION)
    assert not any(user.has_perm(name) for name in ADMINISTRATION_PERMISSIONS)
    assert client.get(reverse("web:administration_overview")).status_code == 403
    assert client.get(reverse("web:ai_configuration")).status_code == 403
    assert client.get(reverse("web:agent_audit_list")).status_code == 403
    assert client.get(reverse("web:pending_proposals")).status_code == 403

    dashboard = client.get(reverse("web:dashboard")).content.decode()
    assert "ADMINISTRAÇÃO" not in dashboard
    for url_name in (
        "web:administration_overview",
        "web:ai_configuration",
        "web:agent_audit_list",
        "web:pending_proposals",
    ):
        assert f'href="{reverse(url_name)}"' not in dashboard


@pytest.mark.parametrize("username", ("admin", "usuario"))
def test_demo_roles_can_execute_complete_operational_flow(
    client,
    demo_users,
    username,
):
    client.force_login(demo_users[username])
    sku = f"ROLE-{username.upper()}"

    response = client.post(
        reverse("web:product_create"),
        {
            "name": f"Product {username}",
            "sku": sku,
            "description": "Role matrix product",
            "minimum_stock": 5,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    product = Product.objects.get(sku=sku)

    response = client.post(
        reverse("web:product_update", args=(product.pk,)),
        {
            "name": f"Updated product {username}",
            "sku": sku,
            "description": "Updated by demo role",
            "minimum_stock": 5,
            "is_active": "on",
        },
    )
    assert response.status_code == 302

    response = client.post(
        reverse("web:supplier_create"),
        {
            "name": f"Supplier {username}",
            "cnpj": "",
            "email": f"{username}@example.com",
            "phone": "",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    supplier = Supplier.objects.get(name=f"Supplier {username}")

    response = client.post(
        reverse("web:supplier_update", args=(supplier.pk,)),
        {
            "name": f"Updated supplier {username}",
            "cnpj": "",
            "email": f"updated-{username}@example.com",
            "phone": "",
            "is_active": "on",
        },
    )
    assert response.status_code == 302

    response = client.post(
        reverse("web:product_supplier_create"),
        {
            "product": product.pk,
            "supplier": supplier.pk,
            "price": "10.00",
            "lead_time_days": 2,
            "is_preferred": "on",
        },
    )
    assert response.status_code == 302
    relation = ProductSupplier.objects.get(product=product, supplier=supplier)

    analysis_payload = {
        "product": product.pk,
        "product_supplier": relation.pk,
        "consumption_days": 30,
        "planning_days": 30,
    }
    response = client.post(reverse("web:replenishment_analysis"), analysis_payload)
    assert response.status_code == 200
    assert "Criar proposta de compra" in response.content.decode()

    response = client.post(
        reverse("web:proposal_create_from_analysis"),
        analysis_payload,
    )
    assert response.status_code == 302
    proposal = PurchaseProposal.objects.get(product=product, supplier=supplier)

    response = client.post(
        reverse("web:movement_create"),
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.IN,
            "quantity": 3,
            "note": "Role matrix movement",
        },
    )
    assert response.status_code == 302
    assert Inventory.objects.get(product=product).current_quantity == 3

    product_detail = client.get(
        reverse("web:product_detail", args=(product.pk,))
    ).content.decode()
    supplier_detail = client.get(
        reverse("web:supplier_detail", args=(supplier.pk,))
    ).content.decode()
    assert (
        f'href="{reverse("web:product_update", args=(product.pk,))}"'
        in product_detail
    )
    assert (
        f'href="{reverse("web:supplier_update", args=(supplier.pk,))}"'
        in supplier_detail
    )

    readable_pages = (
        reverse("web:product_detail", args=(product.pk,)),
        reverse("web:supplier_detail", args=(supplier.pk,)),
        reverse("web:product_supplier_list"),
        reverse("web:inventory_list"),
        reverse("web:movement_list"),
        reverse("web:proposal_list"),
        reverse("web:proposal_detail", args=(proposal.pk,)),
        reverse("web:agent_chat"),
    )
    for url in readable_pages:
        assert client.get(url).status_code == 200

    response = client.post(
        reverse("web:agent_chat"),
        {"message": f"Analyze role {username}"},
        follow=True,
    )
    assert response.status_code == 200
    assert f"Analyze role {username}" in response.content.decode()


def test_demo_admin_can_approve_and_reject_proposals(
    client,
    demo_users,
    pending_proposals,
):
    client.force_login(demo_users["admin"])
    proposal_to_approve, proposal_to_reject = pending_proposals

    detail = client.get(
        reverse("web:proposal_detail", args=(proposal_to_approve.pk,))
    ).content.decode()
    assert "Revisar aprovação" in detail
    assert "Revisar rejeição" in detail

    assert (
        client.post(
            reverse("web:proposal_approve", args=(proposal_to_approve.pk,))
        ).status_code
        == 302
    )
    assert (
        client.post(
            reverse("web:proposal_reject", args=(proposal_to_reject.pk,))
        ).status_code
        == 302
    )
    proposal_to_approve.refresh_from_db()
    proposal_to_reject.refresh_from_db()
    assert proposal_to_approve.status == PurchaseProposal.Status.APPROVED
    assert proposal_to_reject.status == PurchaseProposal.Status.REJECTED


def test_demo_operator_cannot_review_proposals(
    client,
    demo_users,
    pending_proposals,
):
    client.force_login(demo_users["usuario"])
    proposal_to_approve, proposal_to_reject = pending_proposals

    detail = client.get(
        reverse("web:proposal_detail", args=(proposal_to_approve.pk,))
    ).content.decode()
    assert "Revisar aprovação" not in detail
    assert "Revisar rejeição" not in detail

    assert (
        client.post(
            reverse("web:proposal_approve", args=(proposal_to_approve.pk,))
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("web:proposal_reject", args=(proposal_to_reject.pk,))
        ).status_code
        == 403
    )
    proposal_to_approve.refresh_from_db()
    proposal_to_reject.refresh_from_db()
    assert proposal_to_approve.status == PurchaseProposal.Status.PENDING
    assert proposal_to_reject.status == PurchaseProposal.Status.PENDING


def test_demo_seed_is_idempotent(settings):
    settings.DEBUG = True

    call_command("seed_demo_users", verbosity=0)
    user_model = get_user_model()
    initial_ids = dict(
        user_model.objects.filter(username__in=("admin", "usuario")).values_list(
            "username",
            "pk",
        )
    )
    call_command("seed_demo_users", verbosity=0)

    admin = user_model.objects.get(username="admin")
    user = user_model.objects.get(username="usuario")
    assert dict(
        user_model.objects.filter(username__in=("admin", "usuario")).values_list(
            "username",
            "pk",
        )
    ) == initial_ids
    assert admin.get_all_permissions() == set(DEMO_ADMIN_PERMISSIONS)
    assert user.get_all_permissions() == set(DEMO_OPERATOR_PERMISSIONS)
    assert admin.check_password(DEMO_PASSWORD)
    assert user.check_password(DEMO_PASSWORD)


def test_demo_seed_synchronizes_existing_users(settings):
    settings.DEBUG = True
    user_model = get_user_model()
    admin = user_model.objects.create_user(
        username="admin",
        password="old-password",
        is_staff=True,
        is_superuser=True,
    )
    user = user_model.objects.create_user(username="usuario")
    unrelated_permission = Permission.objects.get(
        content_type__app_label="products",
        codename="delete_product",
    )
    admin.user_permissions.add(unrelated_permission)
    user.user_permissions.add(unrelated_permission)

    call_command("seed_demo_users", verbosity=0)

    admin.refresh_from_db()
    user.refresh_from_db()
    assert admin.is_active
    assert not admin.is_staff
    assert not admin.is_superuser
    assert admin.get_all_permissions() == set(DEMO_ADMIN_PERMISSIONS)
    assert admin.check_password(DEMO_PASSWORD)
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser
    assert user.get_all_permissions() == set(DEMO_OPERATOR_PERMISSIONS)
    assert user.check_password(DEMO_PASSWORD)


def test_demo_seed_is_blocked_in_production(settings):
    settings.DEBUG = False

    with pytest.raises(CommandError, match="only be created"):
        call_command("seed_demo_users", verbosity=0)

    assert (
        not get_user_model().objects.filter(username__in=("admin", "usuario")).exists()
    )
