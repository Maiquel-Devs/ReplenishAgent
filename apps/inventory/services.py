from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.products.models import Product

from .models import Inventory, StockMovement


@transaction.atomic
def register_stock_movement(
    *,
    product: Product,
    movement_type: str,
    quantity: int,
    occurred_at: datetime | None = None,
    note: str = "",
) -> StockMovement:
    """Register a movement and update its inventory as one atomic operation."""
    if not isinstance(product, Product) or product.pk is None:
        raise ValidationError({"product": "Informe um produto persistido valido."})

    movement = StockMovement(
        product=product,
        type=movement_type,
        quantity=quantity,
        note=note,
    )
    if occurred_at is not None:
        movement.occurred_at = occurred_at
    movement.full_clean()
    movement_type = movement.type
    quantity = movement.quantity

    # Locking the product serializes both the existing-inventory path and the
    # first movement, when there is no Inventory row available to lock yet.
    locked_product = Product.objects.select_for_update().get(pk=product.pk)
    inventory, _ = Inventory.objects.select_for_update().get_or_create(
        product=locked_product,
    )

    if movement_type == StockMovement.Type.IN:
        new_quantity = inventory.current_quantity + quantity
    else:
        new_quantity = inventory.current_quantity - quantity

    if new_quantity < 0:
        raise ValidationError(
            {"quantity": "Estoque insuficiente para registrar esta saida."}
        )

    movement.product = locked_product
    movement.save()
    inventory.current_quantity = new_quantity
    inventory.save(update_fields=("current_quantity", "updated_at"))
    return movement
