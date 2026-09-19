from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.replenishment.calculations import RiskLevel


RISK_LEVEL_CHOICES = [(level.value, level.value) for level in RiskLevel]
IMMUTABLE_SNAPSHOT_FIELDS = (
    "product_id",
    "supplier_id",
    "quantity",
    "unit_price",
    "total_price",
    "risk_level",
)


class PurchaseProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        APPROVED = "APPROVED", "Aprovada"
        REJECTED = "REJECTED", "Rejeitada"

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="purchase_proposals",
    )
    supplier = models.ForeignKey(
        "suppliers.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_proposals",
    )
    quantity = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    total_price = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    risk_level = models.CharField(max_length=8, choices=RISK_LEVEL_CHOICES)
    status = models.CharField(
        max_length=8,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Proposta de compra"
        verbose_name_plural = "Propostas de compra"
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="purchase_proposal_quantity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gt=0),
                name="purchase_proposal_unit_price_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(total_price__gt=0),
                name="purchase_proposal_total_price_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(total_price=F("quantity") * F("unit_price")),
                name="purchase_proposal_total_matches",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("PENDING", "APPROVED", "REJECTED")),
                name="purchase_proposal_valid_status",
            ),
            models.CheckConstraint(
                condition=Q(risk_level__in=("CRITICAL", "HIGH", "MEDIUM", "LOW")),
                name="purchase_proposal_valid_risk",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="PENDING", reviewed_at__isnull=True)
                    | Q(
                        status__in=("APPROVED", "REJECTED"),
                        reviewed_at__isnull=False,
                    )
                ),
                name="purchase_proposal_review_state",
            ),
        ]

    def clean(self):
        super().clean()

        if self.status == self.Status.PENDING and self.reviewed_at is not None:
            raise ValidationError(
                {"reviewed_at": "A pending proposal cannot have a review date."}
            )
        if (
            self.status in (self.Status.APPROVED, self.Status.REJECTED)
            and self.reviewed_at is None
        ):
            raise ValidationError(
                {"reviewed_at": "A decided proposal must have a review date."}
            )

        if (
            self.quantity is not None
            and self.unit_price is not None
            and self.total_price is not None
            and self.total_price != Decimal(self.quantity) * self.unit_price
        ):
            raise ValidationError(
                {"total_price": "Total price must equal quantity times unit price."}
            )

        if self.pk is None:
            return

        original = type(self).objects.filter(pk=self.pk).values(
            *IMMUTABLE_SNAPSHOT_FIELDS,
            "status",
        ).first()
        if original is None:
            return

        changed_fields = [
            field
            for field in IMMUTABLE_SNAPSHOT_FIELDS
            if getattr(self, field) != original[field]
        ]
        if changed_fields:
            raise ValidationError(
                "Proposal snapshot fields cannot be changed after creation."
            )

        if original["status"] != self.status and original["status"] != self.Status.PENDING:
            raise ValidationError("A decided proposal cannot change status.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Proposal #{self.pk} - {self.product} - {self.status}"
