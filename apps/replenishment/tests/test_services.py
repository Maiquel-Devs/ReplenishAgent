from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import register_stock_movement
from apps.products.models import Product
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.replenishment.services import (
    analyze_replenishment,
    calculate_average_daily_consumption,
)
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def product():
    return Product.objects.create(
        name="Cafe em graos",
        sku="CAFE-REPL-001",
        minimum_stock=5,
    )


@pytest.fixture
def as_of():
    return datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def create_movement(product, movement_type, quantity, occurred_at):
    return StockMovement.objects.create(
        product=product,
        type=movement_type,
        quantity=quantity,
        occurred_at=occurred_at,
    )


def test_average_daily_consumption_is_calculated(product, as_of):
    create_movement(product, StockMovement.Type.OUT, 60, as_of - timedelta(days=1))

    result = calculate_average_daily_consumption(product, 30, as_of=as_of)

    assert result == Decimal("2")
    assert isinstance(result, Decimal)


def test_average_consumption_only_counts_out_movements(product, as_of):
    create_movement(product, StockMovement.Type.OUT, 30, as_of - timedelta(days=1))
    create_movement(product, StockMovement.Type.IN, 300, as_of - timedelta(days=1))

    result = calculate_average_daily_consumption(product, 30, as_of=as_of)

    assert result == Decimal("1")


def test_average_consumption_is_zero_without_out_movements(product, as_of):
    create_movement(product, StockMovement.Type.IN, 30, as_of - timedelta(days=1))

    assert calculate_average_daily_consumption(product, 30, as_of=as_of) == Decimal(
        "0"
    )


@pytest.mark.parametrize("days", [0, -1])
def test_average_consumption_rejects_invalid_period(product, as_of, days):
    with pytest.raises(ValueError):
        calculate_average_daily_consumption(product, days, as_of=as_of)


def test_average_consumption_uses_half_open_time_window(product, as_of):
    window_start = as_of - timedelta(days=30)
    create_movement(product, StockMovement.Type.OUT, 30, window_start)
    create_movement(
        product,
        StockMovement.Type.OUT,
        300,
        window_start - timedelta(microseconds=1),
    )
    create_movement(product, StockMovement.Type.OUT, 300, as_of)

    result = calculate_average_daily_consumption(product, 30, as_of=as_of)

    assert result == Decimal("1")


def test_average_consumption_rejects_naive_as_of(product):
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_average_daily_consumption(
            product,
            30,
            as_of=datetime(2026, 9, 19, 12, 0),
        )


@pytest.fixture
def product_supplier(product):
    supplier = Supplier.objects.create(name="Fornecedor principal")
    return ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
        lead_time_days=5,
    )


def test_consolidated_analysis_returns_coherent_results(
    product,
    product_supplier,
    as_of,
):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=80,
        occurred_at=as_of - timedelta(days=2),
    )
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.OUT,
        quantity=60,
        occurred_at=as_of - timedelta(days=1),
    )

    result = analyze_replenishment(
        product_supplier=product_supplier,
        consumption_days=30,
        planning_days=30,
        as_of=as_of,
    )

    assert isinstance(result, ReplenishmentAnalysis)
    assert result.product == product
    assert result.current_stock == Decimal("20")
    assert result.average_daily_consumption == Decimal("2")
    assert result.stock_coverage_days == Decimal("10")
    assert result.lead_time_days == 5
    assert result.minimum_stock == Decimal("5")
    assert result.reorder_point == Decimal("15")
    assert result.planning_days == 30
    assert result.target_stock == Decimal("65")
    assert result.recommended_quantity == Decimal("45")
    assert result.risk_level == RiskLevel.LOW


def test_analysis_uses_the_informed_product_supplier(
    product,
    product_supplier,
    as_of,
):
    alternate_supplier = Supplier.objects.create(name="Fornecedor alternativo")
    alternate_relation = ProductSupplier.objects.create(
        product=product,
        supplier=alternate_supplier,
        price=Decimal("12.00"),
        lead_time_days=10,
    )
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=80,
        occurred_at=as_of - timedelta(days=2),
    )
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.OUT,
        quantity=60,
        occurred_at=as_of - timedelta(days=1),
    )

    result = analyze_replenishment(
        product_supplier=alternate_relation,
        consumption_days=30,
        planning_days=30,
        as_of=as_of,
    )

    assert result.lead_time_days == 10
    assert result.reorder_point == Decimal("25")
    assert result.risk_level == RiskLevel.HIGH
    assert result.product == product_supplier.product


def test_analysis_has_no_persistence_side_effects(
    product,
    product_supplier,
    as_of,
):
    inventory = Inventory.objects.create(product=product, current_quantity=7)
    inventory_updated_at = inventory.updated_at
    inventory_count = Inventory.objects.count()
    movement_count = StockMovement.objects.count()

    result = analyze_replenishment(
        product_supplier=product_supplier,
        consumption_days=30,
        planning_days=10,
        as_of=as_of,
    )

    inventory.refresh_from_db()
    assert result.current_stock == Decimal("7")
    assert Inventory.objects.count() == inventory_count
    assert StockMovement.objects.count() == movement_count
    assert inventory.current_quantity == 7
    assert inventory.updated_at == inventory_updated_at


def test_analysis_treats_missing_inventory_as_zero(
    product,
    product_supplier,
    as_of,
):
    result = analyze_replenishment(
        product_supplier=product_supplier,
        consumption_days=30,
        planning_days=10,
        as_of=as_of,
    )

    assert result.current_stock == Decimal("0")
    assert result.risk_level == RiskLevel.CRITICAL
    assert not Inventory.objects.filter(product=product).exists()
