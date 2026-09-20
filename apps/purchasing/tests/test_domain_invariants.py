from __future__ import annotations

from decimal import Decimal
from dataclasses import replace

import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError

from apps.inventory.models import StockMovement
from apps.inventory.services import register_stock_movement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import create_purchase_proposal
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


def analysis_for(product, quantity=Decimal("2")):
    return ReplenishmentAnalysis(
        product=product,
        current_stock=Decimal("0"),
        average_daily_consumption=Decimal("1"),
        stock_coverage_days=Decimal("0"),
        lead_time_days=1,
        minimum_stock=Decimal("0"),
        reorder_point=Decimal("1"),
        planning_days=2,
        target_stock=Decimal("2"),
        recommended_quantity=quantity,
        risk_level=RiskLevel.CRITICAL,
    )


def test_stock_history_protects_product_from_deletion():
    product = Product.objects.create(name="Movement product", sku="PROTECT-MOVEMENT")
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=1,
    )

    with pytest.raises(ProtectedError):
        product.delete()

    assert Product.objects.filter(pk=product.pk).exists()
    assert StockMovement.objects.filter(product=product).exists()


def test_proposal_snapshot_protects_product_and_supplier_from_deletion():
    product = Product.objects.create(name="Proposal product", sku="PROTECT-PROPOSAL")
    supplier = Supplier.objects.create(name="Proposal supplier")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("5.00"),
    )
    proposal = create_purchase_proposal(
        product=product,
        product_supplier=relation,
        analysis=analysis_for(product),
    )

    with pytest.raises(ProtectedError):
        product.delete()
    with pytest.raises(ProtectedError):
        supplier.delete()

    assert PurchaseProposal.objects.filter(pk=proposal.pk).exists()


@pytest.mark.parametrize("quantity", [Decimal("1.5"), True, "2"])
def test_proposal_creation_rejects_non_integral_or_non_numeric_quantity(quantity):
    product = Product.objects.create(name="Invalid quantity", sku=f"INVALID-{quantity}")
    supplier = Supplier.objects.create(name=f"Supplier {quantity}")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("5.00"),
    )

    with pytest.raises(ValidationError):
        create_purchase_proposal(
            product=product,
            product_supplier=relation,
            analysis=analysis_for(product, quantity=quantity),
        )

    assert PurchaseProposal.objects.count() == 0


def test_proposal_creation_requires_persisted_domain_objects():
    product = Product.objects.create(name="Persisted product", sku="PERSISTED")
    supplier = Supplier.objects.create(name="Persisted supplier")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("5.00"),
    )

    with pytest.raises(ValidationError, match="persisted product"):
        create_purchase_proposal(
            product=Product(name="Unsaved", sku="UNSAVED-PROPOSAL"),
            product_supplier=relation,
            analysis=analysis_for(product),
        )

    unsaved_relation = ProductSupplier(
        product=product,
        supplier=supplier,
        price=Decimal("5.00"),
    )
    with pytest.raises(ValidationError, match="persisted ProductSupplier"):
        create_purchase_proposal(
            product=product,
            product_supplier=unsaved_relation,
            analysis=analysis_for(product),
        )


def test_proposal_creation_rejects_invalid_risk_type():
    product = Product.objects.create(name="Risk product", sku="INVALID-RISK")
    supplier = Supplier.objects.create(name="Risk supplier")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("5.00"),
    )
    invalid_analysis = replace(analysis_for(product), risk_level="CRITICAL")

    with pytest.raises(ValidationError, match="risk level"):
        create_purchase_proposal(
            product=product,
            product_supplier=relation,
            analysis=invalid_analysis,
        )

    assert PurchaseProposal.objects.count() == 0
