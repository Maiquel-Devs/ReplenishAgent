from decimal import Decimal

import pytest

from apps.replenishment.calculations import (
    RiskLevel,
    calculate_reorder_point,
    calculate_replenishment_quantity,
    calculate_stock_coverage,
    classify_replenishment_risk,
)


def test_stock_coverage_is_calculated_with_decimal():
    assert calculate_stock_coverage(20, Decimal("2")) == Decimal("10")


def test_stock_coverage_is_none_when_consumption_is_zero():
    assert calculate_stock_coverage(20, Decimal("0")) is None


def test_stock_coverage_is_zero_when_stock_is_zero():
    assert calculate_stock_coverage(0, Decimal("2")) == Decimal("0")


def test_reorder_point_is_calculated():
    assert calculate_reorder_point(Decimal("2"), 5, 5) == Decimal("15")


def test_reorder_point_accepts_zero_lead_time():
    assert calculate_reorder_point(Decimal("2"), 0, 5) == Decimal("5")


def test_reorder_point_accepts_zero_minimum_stock():
    assert calculate_reorder_point(Decimal("2"), 5, 0) == Decimal("10")


@pytest.mark.parametrize(
    ("consumption", "lead_time", "minimum"),
    [
        (Decimal("-0.1"), 1, 0),
        (Decimal("1"), -1, 0),
        (Decimal("1"), 1, -1),
    ],
)
def test_reorder_point_rejects_negative_inputs(consumption, lead_time, minimum):
    with pytest.raises(ValueError):
        calculate_reorder_point(consumption, lead_time, minimum)


def test_replenishment_quantity_is_calculated():
    result = calculate_replenishment_quantity(20, Decimal("2"), 30, 5)

    assert result == Decimal("45")


def test_replenishment_quantity_is_zero_when_stock_is_sufficient():
    result = calculate_replenishment_quantity(100, Decimal("2"), 30, 5)

    assert result == Decimal("0")


def test_fractional_replenishment_quantity_is_rounded_up():
    result = calculate_replenishment_quantity(1, Decimal("0.5"), 3, 0)

    assert result == Decimal("1")


@pytest.mark.parametrize("planning_days", [0, -1])
def test_replenishment_quantity_rejects_invalid_planning_days(planning_days):
    with pytest.raises(ValueError):
        calculate_replenishment_quantity(0, Decimal("1"), planning_days, 0)


@pytest.mark.parametrize(
    ("stock", "consumption", "minimum"),
    [
        (-1, Decimal("1"), 0),
        (0, Decimal("-1"), 0),
        (0, Decimal("1"), -1),
    ],
)
def test_replenishment_quantity_rejects_negative_inputs(
    stock,
    consumption,
    minimum,
):
    with pytest.raises(ValueError):
        calculate_replenishment_quantity(stock, consumption, 10, minimum)


def test_risk_is_critical_when_stock_is_zero():
    assert (
        classify_replenishment_risk(0, Decimal("2"), 5, Decimal("15"))
        == RiskLevel.CRITICAL
    )


def test_risk_is_high_when_coverage_reaches_lead_time():
    assert (
        classify_replenishment_risk(4, Decimal("2"), 2, Decimal("5"))
        == RiskLevel.HIGH
    )


def test_risk_is_medium_when_stock_reaches_reorder_point():
    assert (
        classify_replenishment_risk(10, Decimal("1"), 5, Decimal("10"))
        == RiskLevel.MEDIUM
    )


def test_risk_is_low_when_stock_is_above_thresholds():
    assert (
        classify_replenishment_risk(20, Decimal("1"), 5, Decimal("10"))
        == RiskLevel.LOW
    )


def test_risk_is_low_with_stock_and_zero_consumption():
    assert (
        classify_replenishment_risk(1, Decimal("0"), 30, Decimal("100"))
        == RiskLevel.LOW
    )


def test_float_input_is_rejected():
    with pytest.raises(TypeError):
        calculate_stock_coverage(20, 2.0)

def test_replenishment_ignores_decimal_noise_at_whole_unit_boundary():
    repeating_average = Decimal(35) / Decimal(30)

    result = calculate_replenishment_quantity(
        current_stock=5,
        average_daily_consumption=repeating_average,
        planning_days=30,
        minimum_stock=5,
    )

    assert result == Decimal("35")
