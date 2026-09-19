from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=14, blank=True, null=True, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ProductSupplier(models.Model):
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="product_suppliers",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="product_suppliers",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    lead_time_days = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    is_preferred = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product__name", "supplier__name"]
        constraints = [
            models.UniqueConstraint(
                fields=("product", "supplier"),
                name="unique_product_supplier",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gt=0),
                name="product_supplier_price_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(lead_time_days__gte=0),
                name="product_supplier_lead_time_gte_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product} - {self.supplier}"
