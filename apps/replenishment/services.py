from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.suppliers.models import ProductSupplier

from .calculations import (
    ReplenishmentAnalysis,
    calculate_reorder_point,
    calculate_replenishment_quantity,
    calculate_stock_coverage,
    calculate_target_stock,
    classify_replenishment_risk,
    validate_positive_days,
)


def calculate_average_daily_consumption(
    product: Product,
    days: int,
    *,
    as_of: datetime | None = None,
) -> Decimal:
    """Average OUT quantity in the half-open window [as_of - days, as_of)."""
    period_days = validate_positive_days(days, "days")
    window_end = as_of or timezone.now()
    if timezone.is_naive(window_end):
        raise ValueError("as_of must be timezone-aware.")
    window_start = window_end - timedelta(days=period_days)

    total = (
        StockMovement.objects.filter(
            product=product,
            type=StockMovement.Type.OUT,
            occurred_at__gte=window_start,
            occurred_at__lt=window_end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    return Decimal(total) / Decimal(period_days)


def _build_replenishment_analysis(
    *,
    product_supplier: ProductSupplier,
    current_stock: Decimal,
    average_daily_consumption: Decimal,
    planning_days: int,
) -> ReplenishmentAnalysis:
    product = product_supplier.product
    minimum_stock = Decimal(product.minimum_stock)
    lead_time_days = product_supplier.lead_time_days
    coverage = calculate_stock_coverage(
        current_stock,
        average_daily_consumption,
    )
    reorder_point = calculate_reorder_point(
        average_daily_consumption,
        lead_time_days,
        minimum_stock,
    )
    target_stock = calculate_target_stock(
        average_daily_consumption,
        planning_days,
        minimum_stock,
    )
    recommended_quantity = calculate_replenishment_quantity(
        current_stock,
        average_daily_consumption,
        planning_days,
        minimum_stock,
    )
    risk_level = classify_replenishment_risk(
        current_stock,
        average_daily_consumption,
        lead_time_days,
        reorder_point,
    )
    return ReplenishmentAnalysis(
        product=product,
        current_stock=current_stock,
        average_daily_consumption=average_daily_consumption,
        stock_coverage_days=coverage,
        lead_time_days=lead_time_days,
        minimum_stock=minimum_stock,
        reorder_point=reorder_point,
        planning_days=planning_days,
        target_stock=target_stock,
        recommended_quantity=recommended_quantity,
        risk_level=risk_level,
    )


def analyze_replenishment(
    *,
    product_supplier: ProductSupplier,
    consumption_days: int,
    planning_days: int,
    as_of: datetime | None = None,
) -> ReplenishmentAnalysis:
    """Build a read-only replenishment analysis for the supplied relationship."""
    if not isinstance(product_supplier, ProductSupplier) or product_supplier.pk is None:
        raise ValueError("product_supplier must be a persisted ProductSupplier.")

    product = product_supplier.product
    stored_quantity = (
        Inventory.objects.filter(product=product)
        .values_list("current_quantity", flat=True)
        .first()
    )
    current_stock = Decimal(stored_quantity if stored_quantity is not None else 0)
    average = calculate_average_daily_consumption(
        product,
        consumption_days,
        as_of=as_of,
    )
    return _build_replenishment_analysis(
        product_supplier=product_supplier,
        current_stock=current_stock,
        average_daily_consumption=average,
        planning_days=planning_days,
    )


def analyze_replenishments(
    *,
    product_suppliers: Sequence[ProductSupplier],
    consumption_days: int,
    planning_days: int,
    as_of: datetime | None = None,
) -> list[ReplenishmentAnalysis]:
    """Analyze several relations with set-based inventory and movement queries."""
    relations = list(product_suppliers)
    if not relations:
        return []
    if any(
        not isinstance(relation, ProductSupplier) or relation.pk is None
        for relation in relations
    ):
        raise ValueError("All product_suppliers must be persisted.")

    period_days = validate_positive_days(consumption_days, "consumption_days")
    planning = validate_positive_days(planning_days, "planning_days")
    window_end = as_of or timezone.now()
    if timezone.is_naive(window_end):
        raise ValueError("as_of must be timezone-aware.")
    window_start = window_end - timedelta(days=period_days)

    relation_ids = [relation.pk for relation in relations]
    fetched = ProductSupplier.objects.filter(pk__in=relation_ids).select_related(
        "product"
    )
    by_id = {relation.pk: relation for relation in fetched}
    if len(by_id) != len(set(relation_ids)):
        raise ValueError("A product_supplier no longer exists.")
    ordered_relations = [by_id[relation_id] for relation_id in relation_ids]
    product_ids = {relation.product_id for relation in ordered_relations}

    inventories = dict(
        Inventory.objects.filter(product_id__in=product_ids).values_list(
            "product_id", "current_quantity"
        )
    )
    consumption_totals = {
        row["product_id"]: row["total"]
        for row in StockMovement.objects.filter(
            product_id__in=product_ids,
            type=StockMovement.Type.OUT,
            occurred_at__gte=window_start,
            occurred_at__lt=window_end,
        )
        .values("product_id")
        .annotate(total=Sum("quantity"))
    }

    return [
        _build_replenishment_analysis(
            product_supplier=relation,
            current_stock=Decimal(inventories.get(relation.product_id, 0)),
            average_daily_consumption=Decimal(
                consumption_totals.get(relation.product_id, 0)
            )
            / Decimal(period_days),
            planning_days=planning,
        )
        for relation in ordered_relations
    ]
