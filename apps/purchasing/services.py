from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.products.models import Product
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier

from .models import PurchaseProposal


@transaction.atomic
def create_purchase_proposal(
    *,
    product: Product,
    product_supplier: ProductSupplier,
    analysis: ReplenishmentAnalysis,
) -> PurchaseProposal:
    if not isinstance(product, Product) or product.pk is None:
        raise ValidationError({"product": "A persisted product is required."})
    if not isinstance(product_supplier, ProductSupplier) or product_supplier.pk is None:
        raise ValidationError(
            {"product_supplier": "A persisted ProductSupplier is required."}
        )
    if not isinstance(analysis, ReplenishmentAnalysis):
        raise ValidationError({"analysis": "A ReplenishmentAnalysis is required."})
    if not isinstance(analysis.product, Product) or analysis.product.pk is None:
        raise ValidationError(
            {"analysis": "Analysis must reference a persisted product."}
        )
    if analysis.product.pk != product.pk:
        raise ValidationError({"analysis": "Analysis belongs to another product."})

    current_relation = (
        ProductSupplier.objects.select_for_update()
        .select_related("supplier")
        .get(pk=product_supplier.pk)
    )
    if current_relation.product_id != product.pk:
        raise ValidationError(
            {"product_supplier": "ProductSupplier belongs to another product."}
        )

    quantity_value = analysis.recommended_quantity
    if isinstance(quantity_value, bool) or not isinstance(
        quantity_value,
        (Decimal, int),
    ):
        raise ValidationError({"quantity": "Recommended quantity must use Decimal."})
    quantity = Decimal(quantity_value)
    if quantity <= 0:
        raise ValidationError(
            {"quantity": "Recommended quantity must be greater than zero."}
        )
    if quantity != quantity.to_integral_value():
        raise ValidationError(
            {"quantity": "Recommended quantity must represent whole units."}
        )
    if not isinstance(analysis.risk_level, RiskLevel):
        raise ValidationError({"risk_level": "Analysis has an invalid risk level."})

    unit_price = current_relation.price
    total_price = quantity * unit_price

    return PurchaseProposal.objects.create(
        product=product,
        supplier=current_relation.supplier,
        quantity=int(quantity),
        unit_price=unit_price,
        total_price=total_price,
        risk_level=analysis.risk_level.value,
        status=PurchaseProposal.Status.PENDING,
    )


def _decide_purchase_proposal(
    *,
    proposal: PurchaseProposal,
    status: str,
) -> PurchaseProposal:
    if not isinstance(proposal, PurchaseProposal) or proposal.pk is None:
        raise ValidationError({"proposal": "A persisted proposal is required."})

    with transaction.atomic():
        locked_proposal = PurchaseProposal.objects.select_for_update().get(
            pk=proposal.pk
        )
        if locked_proposal.status != PurchaseProposal.Status.PENDING:
            raise ValidationError(
                {"status": "Only pending proposals can be decided."}
            )

        locked_proposal.status = status
        locked_proposal.reviewed_at = timezone.now()
        locked_proposal.save(
            update_fields=("status", "reviewed_at", "updated_at"),
        )
        return locked_proposal


def approve_purchase_proposal(
    proposal: PurchaseProposal,
) -> PurchaseProposal:
    return _decide_purchase_proposal(
        proposal=proposal,
        status=PurchaseProposal.Status.APPROVED,
    )


def reject_purchase_proposal(
    proposal: PurchaseProposal,
) -> PurchaseProposal:
    return _decide_purchase_proposal(
        proposal=proposal,
        status=PurchaseProposal.Status.REJECTED,
    )
