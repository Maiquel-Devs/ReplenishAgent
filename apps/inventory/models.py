from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Inventory(models.Model):
    product = models.OneToOneField(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="inventory",
    )
    current_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name"]
        verbose_name = "Estoque"
        verbose_name_plural = "Estoques"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(current_quantity__gte=0),
                name="inventory_current_quantity_gte_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product}: {self.current_quantity}"


class StockMovement(models.Model):
    class Type(models.TextChoices):
        IN = "IN", "Entrada"
        OUT = "OUT", "Saida"

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    type = models.CharField(max_length=3, choices=Type.choices)
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    occurred_at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        verbose_name = "Movimentacao de estoque"
        verbose_name_plural = "Movimentacoes de estoque"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="stock_movement_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(type__in=("IN", "OUT")),
                name="stock_movement_valid_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} - {self.get_type_display()}: {self.quantity}"
