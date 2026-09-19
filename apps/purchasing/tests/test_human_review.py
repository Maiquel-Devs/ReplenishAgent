from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction

from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import (
    approve_purchase_proposal,
    create_purchase_proposal,
    reject_purchase_proposal,
)
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


def create_proposal(suffix=""):
    product = Product.objects.create(name="Review product", sku=f"REV-{suffix}")
    supplier = Supplier.objects.create(name=f"Review supplier {suffix}")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
    )
    analysis = ReplenishmentAnalysis(
        product=product,
        current_stock=Decimal("0"),
        average_daily_consumption=Decimal("1"),
        stock_coverage_days=Decimal("0"),
        lead_time_days=0,
        minimum_stock=Decimal("0"),
        reorder_point=Decimal("0"),
        planning_days=10,
        target_stock=Decimal("10"),
        recommended_quantity=Decimal("10"),
        risk_level=RiskLevel.CRITICAL,
    )
    return create_purchase_proposal(
        product=product,
        product_supplier=relation,
        analysis=analysis,
    )


def test_human_approval_records_reviewer_and_timestamp():
    reviewer = get_user_model().objects.create_user(username="approver")
    proposal = create_proposal("APPROVE")

    decided = approve_purchase_proposal(proposal, reviewed_by=reviewer)

    assert decided.status == PurchaseProposal.Status.APPROVED
    assert decided.reviewed_by == reviewer
    assert decided.reviewed_at is not None


def test_human_rejection_records_reviewer_and_timestamp():
    reviewer = get_user_model().objects.create_user(username="rejecter")
    proposal = create_proposal("REJECT")

    decided = reject_purchase_proposal(proposal, reviewed_by=reviewer)

    assert decided.status == PurchaseProposal.Status.REJECTED
    assert decided.reviewed_by == reviewer
    assert decided.reviewed_at is not None


def test_decision_requires_persisted_authenticated_reviewer():
    proposal = create_proposal("INVALID")

    with pytest.raises(ValidationError, match="reviewer"):
        approve_purchase_proposal(proposal, reviewed_by=AnonymousUser())

    proposal.refresh_from_db()
    assert proposal.status == PurchaseProposal.Status.PENDING
    assert proposal.reviewed_at is None
    assert proposal.reviewed_by is None


def test_database_rejects_decision_without_complete_review_identity():
    proposal = create_proposal("CONSTRAINT")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PurchaseProposal.objects.filter(pk=proposal.pk).update(
                status=PurchaseProposal.Status.APPROVED,
            )


@pytest.mark.parametrize(
    "action",
    [approve_purchase_proposal, reject_purchase_proposal],
)
@pytest.mark.django_db(transaction=True)
def test_concurrent_same_decisions_have_only_one_winner(action):
    reviewer = get_user_model().objects.create_user(
        username=f"reviewer-{action.__name__}"
    )
    proposal = create_proposal(action.__name__)
    barrier = Barrier(2)

    def decide():
        close_old_connections()
        try:
            current = PurchaseProposal.objects.get(pk=proposal.pk)
            barrier.wait()
            action(current, reviewed_by=reviewer)
        except ValidationError:
            return False
        finally:
            close_old_connections()
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(decide), executor.submit(decide)]
        outcomes = [future.result() for future in results]

    proposal.refresh_from_db()
    assert sorted(outcomes) == [False, True]
    assert proposal.reviewed_by == reviewer
    assert proposal.reviewed_at is not None
