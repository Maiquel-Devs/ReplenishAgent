from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.products.models import Product

WHOLE_UNIT_TOLERANCE = Decimal("1e-9")


class RiskLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class ReplenishmentAnalysis:
    product: Product
    current_stock: Decimal
    average_daily_consumption: Decimal
    stock_coverage_days: Decimal | None
    lead_time_days: int
    minimum_stock: Decimal
    reorder_point: Decimal
    planning_days: int
    target_stock: Decimal
    recommended_quantity: Decimal
    risk_level: RiskLevel


def _as_decimal(value: Decimal | int, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise TypeError(f"{field_name} must be an int or Decimal.")
    return Decimal(value)


def _non_negative_decimal(value: Decimal | int, field_name: str) -> Decimal:
    decimal_value = _as_decimal(value, field_name)
    if decimal_value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return decimal_value


def validate_positive_days(days: int, field_name: str) -> int:
    if isinstance(days, bool) or not isinstance(days, int):
        raise TypeError(f"{field_name} must be an integer.")
    if days <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return days


def calculate_stock_coverage(
    current_stock: Decimal | int,
    average_daily_consumption: Decimal | int,
) -> Decimal | None:
    """Return finite coverage in days, or None when no consumption was observed."""
    stock = _non_negative_decimal(current_stock, "current_stock")
    consumption = _non_negative_decimal(
        average_daily_consumption,
        "average_daily_consumption",
    )
    if consumption == 0:
        return None
    return stock / consumption


def calculate_reorder_point(
    average_daily_consumption: Decimal | int,
    lead_time_days: Decimal | int,
    minimum_stock: Decimal | int,
) -> Decimal:
    consumption = _non_negative_decimal(
        average_daily_consumption,
        "average_daily_consumption",
    )
    lead_time = _non_negative_decimal(lead_time_days, "lead_time_days")
    minimum = _non_negative_decimal(minimum_stock, "minimum_stock")
    return (consumption * lead_time) + minimum


def calculate_target_stock(
    average_daily_consumption: Decimal | int,
    planning_days: int,
    minimum_stock: Decimal | int,
) -> Decimal:
    consumption = _non_negative_decimal(
        average_daily_consumption,
        "average_daily_consumption",
    )
    planning = validate_positive_days(planning_days, "planning_days")
    minimum = _non_negative_decimal(minimum_stock, "minimum_stock")
    return (consumption * Decimal(planning)) + minimum


def calculate_replenishment_quantity(
    current_stock: Decimal | int,
    average_daily_consumption: Decimal | int,
    planning_days: int,
    minimum_stock: Decimal | int,
) -> Decimal:
    stock = _non_negative_decimal(current_stock, "current_stock")
    target_stock = calculate_target_stock(
        average_daily_consumption,
        planning_days,
        minimum_stock,
    )
    requirement = target_stock - stock
    if requirement <= 0:
        return Decimal("0")
    nearest_unit = requirement.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(requirement - nearest_unit) <= WHOLE_UNIT_TOLERANCE:
        return nearest_unit
    return requirement.to_integral_value(rounding=ROUND_CEILING)


def classify_replenishment_risk(
    current_stock: Decimal | int,
    average_daily_consumption: Decimal | int,
    lead_time_days: Decimal | int,
    reorder_point: Decimal | int,
) -> RiskLevel:
    stock = _non_negative_decimal(current_stock, "current_stock")
    consumption = _non_negative_decimal(
        average_daily_consumption,
        "average_daily_consumption",
    )
    lead_time = _non_negative_decimal(lead_time_days, "lead_time_days")
    reorder = _non_negative_decimal(reorder_point, "reorder_point")

    if stock == 0:
        return RiskLevel.CRITICAL
    if consumption == 0:
        return RiskLevel.LOW

    coverage = calculate_stock_coverage(stock, consumption)
    if coverage is not None and coverage <= lead_time:
        return RiskLevel.HIGH
    if stock <= reorder:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
