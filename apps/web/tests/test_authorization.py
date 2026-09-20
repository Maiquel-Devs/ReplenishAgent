from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog():
    product = Product.objects.create(
        name="Protected product",
        sku="PROTECTED-1",
        minimum_stock=1,
    )
    supplier = Supplier.objects.create(name="Protected supplier")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
    )
    return product, supplier, relation


def user_with_permission(codename: str):
    user = get_user_model().objects.create_user(username=f"user-{codename}")
    user.user_permissions.add(Permission.objects.get(codename=codename))
    return user


@pytest.mark.parametrize(
    ("url_name", "args"),
    [
        ("web:product_create", ()),
        ("web:product_update", (1,)),
        ("web:supplier_create", ()),
        ("web:supplier_update", (1,)),
        ("web:product_supplier_create", ()),
        ("web:movement_create", ()),
    ],
)
def test_anonymous_user_cannot_open_state_change_forms(client, catalog, url_name, args):
    response = client.get(reverse(url_name, args=args))

    assert response.status_code == 302
    assert reverse("login") in response.url


def test_authenticated_user_without_permission_cannot_register_movement(
    client,
    catalog,
):
    product, _, _ = catalog
    client.force_login(get_user_model().objects.create_user(username="plain-web"))

    response = client.post(
        reverse("web:movement_create"),
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.IN,
            "quantity": 5,
            "note": "",
        },
    )

    assert response.status_code == 403
    assert not Inventory.objects.filter(product=product).exists()
    assert not StockMovement.objects.filter(product=product).exists()


def test_authorized_user_can_register_movement(client, catalog):
    product, _, _ = catalog
    client.force_login(user_with_permission("add_stockmovement"))

    response = client.post(
        reverse("web:movement_create"),
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.IN,
            "quantity": 5,
            "note": "",
        },
    )

    assert response.status_code == 302
    assert Inventory.objects.get(product=product).current_quantity == 5


def test_proposal_creation_rejects_get_and_requires_permission(client, catalog):
    product, _, relation = catalog
    url = reverse("web:proposal_create_from_analysis")
    payload = {
        "product": product.pk,
        "product_supplier": relation.pk,
        "consumption_days": 30,
        "planning_days": 30,
    }

    assert client.get(url).status_code == 405
    assert client.post(url, payload).status_code == 302
    assert PurchaseProposal.objects.count() == 0

    client.force_login(get_user_model().objects.create_user(username="plain-proposal"))
    assert client.post(url, payload).status_code == 403
    assert PurchaseProposal.objects.count() == 0

    client.force_login(user_with_permission("add_purchaseproposal"))
    assert client.post(url, payload).status_code == 302
    assert PurchaseProposal.objects.get().status == PurchaseProposal.Status.PENDING


def test_state_change_post_enforces_csrf(catalog):
    product, _, _ = catalog
    client = Client(enforce_csrf_checks=True)
    client.force_login(user_with_permission("add_stockmovement"))
    url = reverse("web:movement_create")

    response = client.post(
        url,
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.IN,
            "quantity": 1,
            "note": "",
        },
    )

    assert response.status_code == 403
    assert StockMovement.objects.count() == 0

def test_authorized_users_can_open_each_state_change_form(client, catalog):
    product, supplier, _ = catalog
    user = get_user_model().objects.create_user(username="full-web-operator")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=(
                "add_product",
                "change_product",
                "add_supplier",
                "change_supplier",
                "add_productsupplier",
                "add_stockmovement",
            )
        )
    )
    client.force_login(user)

    urls = [
        reverse("web:product_create"),
        reverse("web:product_update", args=[product.pk]),
        reverse("web:supplier_create"),
        reverse("web:supplier_update", args=[supplier.pk]),
        reverse("web:product_supplier_create"),
        reverse("web:movement_create"),
    ]

    assert [client.get(url).status_code for url in urls] == [200] * len(urls)


@pytest.mark.parametrize(
    ("url_name", "args", "action_label"),
    [
        ("web:product_list", (), "Novo produto"),
        ("web:product_detail", ("product",), "Editar cadastro"),
        ("web:supplier_list", (), "Novo fornecedor"),
        ("web:supplier_detail", ("supplier",), "Editar cadastro"),
        ("web:product_supplier_list", (), "Nova relação"),
        ("web:inventory_list", (), "Registrar movimentação"),
        ("web:movement_list", (), "Nova movimentação"),
    ],
)
def test_state_change_actions_are_hidden_without_permission(
    client,
    catalog,
    url_name,
    args,
    action_label,
):
    product, supplier, _ = catalog
    resolved_args = tuple(
        product.pk if value == "product" else supplier.pk
        for value in args
    )
    client.force_login(
        get_user_model().objects.create_user(username=f"plain-{url_name}")
    )

    response = client.get(reverse(url_name, args=resolved_args))

    assert response.status_code == 200
    assert action_label not in response.content.decode()


def test_proposal_action_is_hidden_without_permission(client, catalog):
    product, _, relation = catalog
    client.force_login(
        get_user_model().objects.create_user(username="plain-analysis")
    )

    response = client.post(
        reverse("web:replenishment_analysis"),
        {
            "product": product.pk,
            "product_supplier": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
    )

    assert response.status_code == 200
    assert "Criar proposta de compra" not in response.content.decode()


def test_authorized_user_sees_matching_state_change_actions(client, catalog):
    product, _, relation = catalog
    user = get_user_model().objects.create_user(username="visible-actions")
    user.user_permissions.add(
        *Permission.objects.filter(
            codename__in=(
                "add_product",
                "add_stockmovement",
                "add_purchaseproposal",
            )
        )
    )
    client.force_login(user)

    product_list = client.get(reverse("web:product_list"))
    inventory_list = client.get(reverse("web:inventory_list"))
    analysis = client.post(
        reverse("web:replenishment_analysis"),
        {
            "product": product.pk,
            "product_supplier": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
    )

    assert "Novo produto" in product_list.content.decode()
    assert "Registrar movimentação" in inventory_list.content.decode()
    assert "Criar proposta de compra" in analysis.content.decode()
