from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction

from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import (
    approve_purchase_proposal,
    create_purchase_proposal,
    reject_purchase_proposal,
)
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db

@pytest.fixture
def reviewer():
    return get_user_model().objects.create_user(
        username="purchase-reviewer",
        password="test-password",
    )


@pytest.fixture
def product():
    return Product.objects.create(
        name="Cafe para compras",
        sku="BUY-001",
        minimum_stock=5,
    )


@pytest.fixture
def supplier():
    return Supplier.objects.create(name="Fornecedor de compras")


@pytest.fixture
def product_supplier(product, supplier):
    return ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("92.00"),
        lead_time_days=5,
    )


def make_analysis(
    product,
    *,
    recommended_quantity=Decimal("10"),
    risk_level=RiskLevel.HIGH,
):
    return ReplenishmentAnalysis(
        product=product,
        current_stock=Decimal("5"),
        average_daily_consumption=Decimal("2"),
        stock_coverage_days=Decimal("2.5"),
        lead_time_days=5,
        minimum_stock=Decimal("5"),
        reorder_point=Decimal("15"),
        planning_days=5,
        target_stock=Decimal("15"),
        recommended_quantity=recommended_quantity,
        risk_level=risk_level,
    )


@pytest.fixture
def proposal(product, product_supplier):
    return create_purchase_proposal(
        product=product,
        product_supplier=product_supplier,
        analysis=make_analysis(product),
    )


def test_create_purchase_proposal_uses_analysis_and_supplier_snapshot(
    product,
    product_supplier,
):
    proposal = create_purchase_proposal(
        product=product,
        product_supplier=product_supplier,
        analysis=make_analysis(product),
    )

    assert proposal.product == product
    assert proposal.supplier == product_supplier.supplier
    assert proposal.quantity == 10
    assert proposal.unit_price == Decimal("92.00")
    assert proposal.total_price == Decimal("920.00")
    assert proposal.risk_level == RiskLevel.HIGH.value
    assert proposal.status == PurchaseProposal.Status.PENDING
    assert proposal.reviewed_at is None


def test_creation_rejects_zero_recommended_quantity(product, product_supplier):
    with pytest.raises(ValidationError):
        create_purchase_proposal(
            product=product,
            product_supplier=product_supplier,
            analysis=make_analysis(product, recommended_quantity=Decimal("0")),
        )

    assert PurchaseProposal.objects.count() == 0


def test_creation_rejects_analysis_from_another_product(product_supplier):
    other_product = Product.objects.create(name="Outro", sku="BUY-002")

    with pytest.raises(ValidationError, match="another product"):
        create_purchase_proposal(
            product=other_product,
            product_supplier=product_supplier,
            analysis=make_analysis(product_supplier.product),
        )


def test_creation_rejects_product_supplier_from_another_product(
    product,
    product_supplier,
):
    other_product = Product.objects.create(name="Outro", sku="BUY-003")

    with pytest.raises(ValidationError, match="another product"):
        create_purchase_proposal(
            product=other_product,
            product_supplier=product_supplier,
            analysis=make_analysis(other_product),
        )


def test_creation_does_not_change_inventory_or_movements(
    product,
    product_supplier,
):
    inventory = Inventory.objects.create(product=product, current_quantity=8)
    movement_count = StockMovement.objects.count()

    create_purchase_proposal(
        product=product,
        product_supplier=product_supplier,
        analysis=make_analysis(product),
    )

    inventory.refresh_from_db()
    assert inventory.current_quantity == 8
    assert StockMovement.objects.count() == movement_count


def test_price_and_total_are_historical_snapshots(proposal, product_supplier):
    product_supplier.price = Decimal("100.00")
    product_supplier.save(update_fields=("price", "updated_at"))
    proposal.refresh_from_db()

    assert proposal.unit_price == Decimal("92.00")
    assert proposal.total_price == Decimal("920.00")


def test_snapshot_fields_cannot_be_changed(proposal):
    proposal.quantity = 20
    proposal.total_price = Decimal("1840.00")

    with pytest.raises(ValidationError, match="snapshot"):
        proposal.save()


def test_arbitrary_total_is_rejected(product, supplier):
    proposal = PurchaseProposal(
        product=product,
        supplier=supplier,
        quantity=2,
        unit_price=Decimal("10.00"),
        total_price=Decimal("999.00"),
        risk_level=RiskLevel.LOW.value,
    )

    with pytest.raises(ValidationError, match="quantity times unit price"):
        proposal.save()


def test_approve_pending_proposal(proposal, reviewer):
    decided = approve_purchase_proposal(proposal, reviewed_by=reviewer)

    assert decided.status == PurchaseProposal.Status.APPROVED
    assert decided.reviewed_at is not None


def test_repeated_approval_is_rejected(proposal, reviewer):
    decided = approve_purchase_proposal(proposal, reviewed_by=reviewer)

    with pytest.raises(ValidationError):
        approve_purchase_proposal(decided, reviewed_by=reviewer)


def test_approval_of_rejected_proposal_is_rejected(proposal, reviewer):
    rejected = reject_purchase_proposal(proposal, reviewed_by=reviewer)

    with pytest.raises(ValidationError):
        approve_purchase_proposal(rejected, reviewed_by=reviewer)


def test_approval_does_not_change_stock_or_create_movement(product, proposal, reviewer):
    inventory = Inventory.objects.create(product=product, current_quantity=4)
    movement_count = StockMovement.objects.count()

    approve_purchase_proposal(proposal, reviewed_by=reviewer)

    inventory.refresh_from_db()
    assert inventory.current_quantity == 4
    assert StockMovement.objects.count() == movement_count


def test_reject_pending_proposal(proposal, reviewer):
    decided = reject_purchase_proposal(proposal, reviewed_by=reviewer)

    assert decided.status == PurchaseProposal.Status.REJECTED
    assert decided.reviewed_at is not None


def test_repeated_rejection_is_rejected(proposal, reviewer):
    decided = reject_purchase_proposal(proposal, reviewed_by=reviewer)

    with pytest.raises(ValidationError):
        reject_purchase_proposal(decided, reviewed_by=reviewer)


def test_rejection_of_approved_proposal_is_rejected(proposal, reviewer):
    approved = approve_purchase_proposal(proposal, reviewed_by=reviewer)

    with pytest.raises(ValidationError):
        reject_purchase_proposal(approved, reviewed_by=reviewer)


def test_rejection_does_not_change_stock(product, proposal, reviewer):
    inventory = Inventory.objects.create(product=product, current_quantity=4)
    movement_count = StockMovement.objects.count()

    reject_purchase_proposal(proposal, reviewed_by=reviewer)

    inventory.refresh_from_db()
    assert inventory.current_quantity == 4
    assert StockMovement.objects.count() == movement_count


@pytest.mark.parametrize(
    "invalid_values",
    [
        {
            "quantity": 0,
            "unit_price": Decimal("10.00"),
            "total_price": Decimal("0.00"),
            "risk_level": "LOW",
            "status": "PENDING",
        },
        {
            "quantity": 1,
            "unit_price": Decimal("0.00"),
            "total_price": Decimal("0.00"),
            "risk_level": "LOW",
            "status": "PENDING",
        },
        {
            "quantity": 1,
            "unit_price": Decimal("10.00"),
            "total_price": Decimal("0.00"),
            "risk_level": "LOW",
            "status": "PENDING",
        },
        {
            "quantity": 1,
            "unit_price": Decimal("10.00"),
            "total_price": Decimal("10.00"),
            "risk_level": "LOW",
            "status": "INVALID",
        },
        {
            "quantity": 1,
            "unit_price": Decimal("10.00"),
            "total_price": Decimal("10.00"),
            "risk_level": "INVALID",
            "status": "PENDING",
        },
    ],
)
def test_database_constraints_reject_invalid_values(
    product,
    supplier,
    invalid_values,
):
    invalid_proposal = PurchaseProposal(
        product=product,
        supplier=supplier,
        **invalid_values,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PurchaseProposal.objects.bulk_create([invalid_proposal])


@pytest.mark.django_db(transaction=True)
def test_concurrent_decisions_allow_only_one_winner():
    product = Product.objects.create(name="Produto concorrente", sku="BUY-CONC")
    supplier = Supplier.objects.create(name="Fornecedor concorrente")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
    )
    proposal = create_purchase_proposal(
        product=product,
        product_supplier=relation,
        analysis=make_analysis(product),
    )
    reviewer = get_user_model().objects.create_user(
        username="concurrent-reviewer"
    )
    barrier = Barrier(2)

    def decide(action):
        close_old_connections()
        try:
            thread_proposal = PurchaseProposal.objects.get(pk=proposal.pk)
            barrier.wait()
            action(thread_proposal, reviewed_by=reviewer)
        except ValidationError:
            return False
        finally:
            close_old_connections()
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        approve_future = executor.submit(decide, approve_purchase_proposal)
        reject_future = executor.submit(decide, reject_purchase_proposal)
        results = [approve_future.result(), reject_future.result()]

    proposal.refresh_from_db()
    assert sorted(results) == [False, True]
    assert proposal.status in (
        PurchaseProposal.Status.APPROVED,
        PurchaseProposal.Status.REJECTED,
    )
    assert proposal.reviewed_at is not None
