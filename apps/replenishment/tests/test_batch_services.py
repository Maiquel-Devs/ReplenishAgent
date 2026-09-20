from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.replenishment.services import (
    analyze_replenishment,
    analyze_replenishments,
)
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


def create_relation(suffix: str, *, stock: int, consumption: int):
    product = Product.objects.create(
        name=f"Batch product {suffix}",
        sku=f"BATCH-{suffix}",
        minimum_stock=3,
    )
    supplier = Supplier.objects.create(name=f"Batch supplier {suffix}")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("7.50"),
        lead_time_days=4,
    )
    Inventory.objects.create(product=product, current_quantity=stock)
    StockMovement.objects.create(
        product=product,
        type=StockMovement.Type.OUT,
        quantity=consumption,
        occurred_at=datetime(2026, 9, 18, 12, tzinfo=UTC),
    )
    return relation


def test_batch_analysis_is_equivalent_to_individual_analysis_and_preserves_order(
    django_assert_num_queries,
):
    as_of = datetime(2026, 9, 19, 12, tzinfo=UTC)
    first = create_relation("A", stock=8, consumption=30)
    second = create_relation("B", stock=0, consumption=60)
    relations = [second, first]

    expected = [
        analyze_replenishment(
            product_supplier=relation,
            consumption_days=30,
            planning_days=20,
            as_of=as_of,
        )
        for relation in relations
    ]

    with django_assert_num_queries(3):
        actual = analyze_replenishments(
            product_suppliers=relations,
            consumption_days=30,
            planning_days=20,
            as_of=as_of,
        )

    assert actual == expected
    assert [analysis.product.pk for analysis in actual] == [
        second.product_id,
        first.product_id,
    ]


def test_batch_analysis_handles_empty_input_without_queries(django_assert_num_queries):
    with django_assert_num_queries(0):
        assert analyze_replenishments(
            product_suppliers=[],
            consumption_days=30,
            planning_days=30,
        ) == []


def test_batch_analysis_uses_same_half_open_time_window_as_individual():
    as_of = datetime(2026, 9, 19, 12, tzinfo=UTC)
    relation = create_relation("BOUNDARY", stock=5, consumption=30)
    product = relation.product
    StockMovement.objects.create(
        product=product,
        type=StockMovement.Type.OUT,
        quantity=300,
        occurred_at=as_of,
    )
    StockMovement.objects.create(
        product=product,
        type=StockMovement.Type.OUT,
        quantity=300,
        occurred_at=as_of - timedelta(days=30, microseconds=1),
    )

    result = analyze_replenishments(
        product_suppliers=[relation],
        consumption_days=30,
        planning_days=30,
        as_of=as_of,
    )[0]

    assert result.average_daily_consumption == Decimal("1")
