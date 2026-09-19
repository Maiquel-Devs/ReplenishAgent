import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import register_stock_movement
from apps.products.models import Product


pytestmark = pytest.mark.django_db


@pytest.fixture
def product():
    return Product.objects.create(name="Cafe em graos", sku="CAFE-001")


def test_inventory_starts_with_zero_quantity(product):
    inventory = Inventory.objects.create(product=product)

    assert inventory.current_quantity == 0


def test_in_movement_increases_inventory(product):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=10,
    )

    assert Inventory.objects.get(product=product).current_quantity == 10


def test_out_movement_decreases_inventory(product):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=10,
    )
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.OUT,
        quantity=4,
    )

    assert Inventory.objects.get(product=product).current_quantity == 6


def test_multiple_movements_produce_correct_quantity(product):
    movements = [
        (StockMovement.Type.IN, 20),
        (StockMovement.Type.OUT, 3),
        (StockMovement.Type.IN, 5),
        (StockMovement.Type.OUT, 7),
    ]

    for movement_type, quantity in movements:
        register_stock_movement(
            product=product,
            movement_type=movement_type,
            quantity=quantity,
        )

    assert Inventory.objects.get(product=product).current_quantity == 15


def test_out_movement_greater_than_available_stock_is_rejected(product):
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=5,
    )

    with pytest.raises(ValidationError, match="Estoque insuficiente"):
        register_stock_movement(
            product=product,
            movement_type=StockMovement.Type.OUT,
            quantity=6,
        )

    assert Inventory.objects.get(product=product).current_quantity == 5
    assert StockMovement.objects.count() == 1


def test_negative_stock_attempt_does_not_persist_partial_changes(product):
    with pytest.raises(ValidationError):
        register_stock_movement(
            product=product,
            movement_type=StockMovement.Type.OUT,
            quantity=1,
        )

    assert not Inventory.objects.filter(product=product).exists()
    assert not StockMovement.objects.filter(product=product).exists()


@pytest.mark.parametrize("invalid_quantity", [0, -1])
def test_non_positive_quantity_is_rejected_without_changes(product, invalid_quantity):
    with pytest.raises(ValidationError):
        register_stock_movement(
            product=product,
            movement_type=StockMovement.Type.IN,
            quantity=invalid_quantity,
        )

    assert not Inventory.objects.filter(product=product).exists()
    assert not StockMovement.objects.filter(product=product).exists()


def test_invalid_movement_type_is_rejected_without_changes(product):
    with pytest.raises(ValidationError):
        register_stock_movement(
            product=product,
            movement_type="TRANSFER",
            quantity=5,
        )

    assert not Inventory.objects.filter(product=product).exists()
    assert not StockMovement.objects.filter(product=product).exists()


def test_product_cannot_have_two_inventories(product):
    Inventory.objects.create(product=product)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Inventory.objects.create(product=product)


def test_stock_movement_history_is_preserved(product):
    first = register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=12,
        note="Recebimento inicial",
    )
    second = register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.OUT,
        quantity=2,
        note="Consumo",
    )

    assert list(
        StockMovement.objects.order_by("pk").values_list(
            "pk", "type", "quantity", "note"
        )
    ) == [
        (first.pk, "IN", 12, "Recebimento inicial"),
        (second.pk, "OUT", 2, "Consumo"),
    ]
    assert Inventory.objects.get(product=product).current_quantity == 10


def test_database_constraints_protect_quantities_and_types(product):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Inventory.objects.create(product=product, current_quantity=-1)

    for invalid_values in (
        {"type": StockMovement.Type.IN, "quantity": 0},
        {"type": "BAD", "quantity": 1},
    ):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                StockMovement.objects.create(product=product, **invalid_values)


@pytest.mark.django_db(transaction=True)
def test_concurrent_out_movements_cannot_oversell_stock():
    product = Product.objects.create(name="Produto concorrente", sku="CONC-001")
    register_stock_movement(
        product=product,
        movement_type=StockMovement.Type.IN,
        quantity=10,
    )
    barrier = Barrier(2)

    def register_out():
        close_old_connections()
        try:
            thread_product = Product.objects.get(pk=product.pk)
            barrier.wait()
            register_stock_movement(
                product=thread_product,
                movement_type=StockMovement.Type.OUT,
                quantity=7,
            )
        except ValidationError:
            return False
        finally:
            close_old_connections()
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register_out(), range(2)))

    assert sorted(results) == [False, True]
    assert Inventory.objects.get(product=product).current_quantity == 3
    assert list(
        StockMovement.objects.filter(product=product)
        .order_by("pk")
        .values_list("type", "quantity")
    ) == [("IN", 10), ("OUT", 7)]
