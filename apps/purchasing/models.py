from decimal import Decimal

from django.conf import settings
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
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_purchase_proposals",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Proposta de compra"
        verbose_name_plural = "Propostas de compra"
        permissions = [
            ("review_purchaseproposal", "Can review purchase proposals"),
        ]
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
                    Q(
                        status="PENDING",
                        reviewed_at__isnull=True,
                        reviewed_by__isnull=True,
                    )
                    | Q(
                        status__in=("APPROVED", "REJECTED"),
                        reviewed_at__isnull=False,
                        reviewed_by__isnull=False,
                    )
                ),
                name="purchase_proposal_review_state",
            ),
        ]

    def clean(self):
        super().clean()
        is_pending = self.status == self.Status.PENDING
        has_review = self.reviewed_at is not None or self.reviewed_by_id is not None
        if is_pending and has_review:
            raise ValidationError(
                "A pending proposal cannot contain review information."
            )
        if not is_pending and (
            self.reviewed_at is None or self.reviewed_by_id is None
        ):
            raise ValidationError(
                "A decided proposal requires review date and reviewer."
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
            "reviewed_at",
            "reviewed_by_id",
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
        if original["status"] != self.Status.PENDING and (
            original["reviewed_at"] != self.reviewed_at
            or original["reviewed_by_id"] != self.reviewed_by_id
        ):
            raise ValidationError("Proposal review information is immutable.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Proposal #{self.pk} - {self.product} - {self.status}"
