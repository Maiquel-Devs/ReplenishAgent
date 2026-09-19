from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import register_stock_movement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import (
    approve_purchase_proposal,
    create_purchase_proposal,
)
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier, Supplier


from apps.web.templatetags.formatting import brl
pytestmark = pytest.mark.django_db

@pytest.fixture
def reviewer():
    user = get_user_model().objects.create_user(username="web-reviewer")
    user.user_permissions.add(
        Permission.objects.get(codename="review_purchaseproposal")
    )
    return user


@pytest.fixture
def product():
    return Product.objects.create(
        name="Produto Web",
        sku="WEB-001",
        minimum_stock=5,
    )


@pytest.fixture
def supplier():
    return Supplier.objects.create(name="Fornecedor Web")


@pytest.fixture
def relation(product, supplier):
    return ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("92.00"),
        lead_time_days=5,
    )


def make_analysis(product, quantity=Decimal("5")):
    return ReplenishmentAnalysis(
        product=product,
        current_stock=Decimal("0"),
        average_daily_consumption=Decimal("0"),
        stock_coverage_days=None,
        lead_time_days=5,
        minimum_stock=Decimal("5"),
        reorder_point=Decimal("5"),
        planning_days=30,
        target_stock=Decimal("5"),
        recommended_quantity=quantity,
        risk_level=RiskLevel.CRITICAL,
    )


@pytest.fixture
def proposal(product, relation):
    return create_purchase_proposal(
        product=product,
        product_supplier=relation,
        analysis=make_analysis(product),
    )


def test_dashboard_responds_and_shows_indicators(client, product):
    response = client.get(reverse("web:dashboard"))

    assert response.status_code == 200
    assert response.context["active_product_count"] == 1
    assert response.context["low_stock_count"] == 1


def test_product_list(client, product):
    response = client.get(reverse("web:product_list"))

    assert response.status_code == 200
    assert product.name in response.content.decode()


def test_valid_product_creation(client):
    response = client.post(
        reverse("web:product_create"),
        {
            "name": "Novo Produto",
            "sku": "WEB-NEW",
            "description": "Descricao",
            "minimum_stock": 3,
            "is_active": "on",
        },
    )

    product = Product.objects.get(sku="WEB-NEW")
    assert response.status_code == 302
    assert response.url == reverse("web:product_detail", args=[product.pk])


def test_product_form_cannot_change_inventory(client, product):
    Inventory.objects.create(product=product, current_quantity=7)

    response = client.post(
        reverse("web:product_update", args=[product.pk]),
        {
            "name": product.name,
            "sku": product.sku,
            "description": "",
            "minimum_stock": 5,
            "is_active": "on",
            "current_quantity": 999,
        },
    )

    assert response.status_code == 302
    assert Inventory.objects.get(product=product).current_quantity == 7


def test_supplier_list(client, supplier):
    response = client.get(reverse("web:supplier_list"))

    assert response.status_code == 200
    assert supplier.name in response.content.decode()


def test_valid_supplier_creation(client):
    response = client.post(
        reverse("web:supplier_create"),
        {
            "name": "Novo Fornecedor",
            "cnpj": "12345678000199",
            "email": "web@example.com",
            "phone": "11999990000",
            "is_active": "on",
        },
    )

    supplier = Supplier.objects.get(name="Novo Fornecedor")
    assert response.status_code == 302
    assert response.url == reverse("web:supplier_detail", args=[supplier.pk])


def test_inventory_consultation_shows_low_stock(client, product):
    Inventory.objects.create(product=product, current_quantity=3)

    response = client.get(reverse("web:inventory_list"))

    assert response.status_code == 200
    assert "BAIXO" in response.content.decode()
    assert "3" in response.content.decode()


def test_register_in_movement_through_interface_and_service(client, product):
    with patch(
        "apps.web.views.register_stock_movement",
        wraps=register_stock_movement,
    ) as service:
        response = client.post(
            reverse("web:movement_create"),
            {
                "product": product.pk,
                "movement_type": StockMovement.Type.IN,
                "quantity": 20,
                "note": "Entrada web",
            },
        )

    assert response.status_code == 302
    assert service.call_count == 1
    assert Inventory.objects.get(product=product).current_quantity == 20
    assert StockMovement.objects.filter(product=product, quantity=20).exists()


def test_register_out_movement_through_interface(client, product):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=20,
    )

    response = client.post(
        reverse("web:movement_create"),
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.OUT,
            "quantity": 6,
            "note": "",
        },
    )

    assert response.status_code == 302
    assert Inventory.objects.get(product=product).current_quantity == 14


def test_insufficient_stock_is_presented_without_partial_changes(client, product):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=2,
    )

    response = client.post(
        reverse("web:movement_create"),
        {
            "product": product.pk,
            "movement_type": StockMovement.Type.OUT,
            "quantity": 3,
            "note": "",
        },
    )

    assert response.status_code == 200
    assert "Estoque insuficiente" in response.content.decode()
    assert Inventory.objects.get(product=product).current_quantity == 2
    assert StockMovement.objects.count() == 1


def test_replenishment_analysis_through_interface(client, product, relation):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=80,
    )
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.OUT,
        quantity=60,
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
    assert response.context["analysis"] is not None
    assert "Quantidade recomendada" in response.content.decode()
    assert "45" in response.content.decode()


def test_none_coverage_is_displayed_as_no_consumption(client, product, relation):
    Inventory.objects.create(product=product, current_quantity=10)

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
    assert "Sem consumo observado" in response.content.decode()


def test_create_proposal_from_analysis(client, product, relation):
    response = client.post(
        reverse("web:proposal_create_from_analysis"),
        {
            "product": product.pk,
            "product_supplier": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
    )

    proposal = PurchaseProposal.objects.get()
    assert response.status_code == 302
    assert proposal.quantity == 5
    assert proposal.unit_price == relation.price


def test_zero_recommendation_cannot_create_proposal(client, supplier):
    product = Product.objects.create(
        name="Sem necessidade",
        sku="WEB-ZERO",
        minimum_stock=0,
    )
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
    )

    response = client.post(
        reverse("web:proposal_create_from_analysis"),
        {
            "product": product.pk,
            "product_supplier": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
        follow=True,
    )

    assert response.status_code == 200
    assert PurchaseProposal.objects.count() == 0
    assert "greater than zero" in response.content.decode()


def test_approve_proposal_requires_human_confirmation(client, proposal, reviewer):
    client.force_login(reviewer)
    confirm_url = reverse("web:proposal_approve", args=[proposal.pk])

    confirmation = client.get(confirm_url)
    proposal.refresh_from_db()
    assert confirmation.status_code == 200
    assert proposal.status == PurchaseProposal.Status.PENDING

    with patch(
        "apps.web.admin_views.approve_purchase_proposal",
        wraps=approve_purchase_proposal,
    ) as service:
        response = client.post(confirm_url)

    proposal.refresh_from_db()
    assert response.status_code == 302
    assert service.call_count == 1
    assert proposal.status == PurchaseProposal.Status.APPROVED
    assert proposal.reviewed_by == reviewer


def test_reject_proposal_requires_human_confirmation(client, proposal, reviewer):
    client.force_login(reviewer)
    confirm_url = reverse("web:proposal_reject", args=[proposal.pk])

    assert client.get(confirm_url).status_code == 200
    proposal.refresh_from_db()
    assert proposal.status == PurchaseProposal.Status.PENDING

    response = client.post(confirm_url)

    proposal.refresh_from_db()
    assert response.status_code == 302
    assert proposal.status == PurchaseProposal.Status.REJECTED
    assert proposal.reviewed_by == reviewer


def test_invalid_decision_is_presented_to_authorized_user(client, proposal, reviewer):
    client.force_login(reviewer)
    client.post(reverse("web:proposal_approve", args=[proposal.pk]))

    response = client.post(
        reverse("web:proposal_reject", args=[proposal.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "Only pending proposals can be decided" in response.content.decode()
    proposal.refresh_from_db()
    assert proposal.status == PurchaseProposal.Status.APPROVED

def test_brl_formatting_is_presentation_only():
    assert brl(Decimal("4140.00")) == "R$ 4.140,00"


def test_product_and_supplier_detail_pages(client, product, supplier):
    product_response = client.get(reverse("web:product_detail", args=[product.pk]))
    supplier_response = client.get(reverse("web:supplier_detail", args=[supplier.pk]))

    assert product_response.status_code == 200
    assert supplier_response.status_code == 200
