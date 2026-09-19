from __future__ import annotations

from collections.abc import Callable

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from apps.agent.audit import ToolExecutionStatus
from apps.agent.models import AgentExecution, AgentToolExecution
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import (
    approve_purchase_proposal,
    reject_purchase_proposal,
)

from .authorization import (
    REVIEW_PROPOSAL_PERMISSION,
    VIEW_AGENT_AUDIT_PERMISSION,
    administration_required,
    permission_required,
)
from .views import _domain_error_message


@administration_required
def administration_overview(request: HttpRequest) -> HttpResponse:
    context = {
        "pending_count": PurchaseProposal.objects.filter(
            status=PurchaseProposal.Status.PENDING
        ).count(),
        "recent_executions": AgentExecution.objects.select_related("user")[:5],
        "recent_problem_tools": (
            AgentToolExecution.objects.exclude(
                status=ToolExecutionStatus.EXECUTED.value
            )
            .select_related("execution", "execution__user")[:5]
        ),
    }
    return render(request, "web/admin/overview.html", context)


@permission_required(REVIEW_PROPOSAL_PERMISSION)
def pending_proposals(request: HttpRequest) -> HttpResponse:
    proposals = (
        PurchaseProposal.objects.filter(status=PurchaseProposal.Status.PENDING)
        .select_related("product", "supplier")
        .order_by("created_at", "pk")
    )
    return render(
        request,
        "web/admin/pending_proposals.html",
        {"proposals": proposals},
    )


def _proposal_decision(
    request: HttpRequest,
    *,
    pk: int,
    action: str,
    service: Callable,
) -> HttpResponse:
    proposal = get_object_or_404(
        PurchaseProposal.objects.select_related("product", "supplier"),
        pk=pk,
    )
    if request.method == "GET":
        return render(
            request,
            "web/admin/proposal_confirm.html",
            {"proposal": proposal, "action": action},
        )

    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])

    try:
        service(proposal, reviewed_by=request.user)
    except ValidationError as error:
        messages.error(request, _domain_error_message(error))
    else:
        messages.success(request, f"Proposta {action.lower()} com sucesso.")
    return redirect("web:proposal_detail", pk=proposal.pk)


@permission_required(REVIEW_PROPOSAL_PERMISSION)
def proposal_approve(request: HttpRequest, pk: int) -> HttpResponse:
    return _proposal_decision(
        request,
        pk=pk,
        action="Aprovada",
        service=approve_purchase_proposal,
    )


@permission_required(REVIEW_PROPOSAL_PERMISSION)
def proposal_reject(request: HttpRequest, pk: int) -> HttpResponse:
    return _proposal_decision(
        request,
        pk=pk,
        action="Rejeitada",
        service=reject_purchase_proposal,
    )


@permission_required(VIEW_AGENT_AUDIT_PERMISSION)
def agent_audit_list(request: HttpRequest) -> HttpResponse:
    executions = AgentExecution.objects.select_related("user")[:100]
    return render(
        request,
        "web/admin/audit_list.html",
        {"executions": executions},
    )


@permission_required(VIEW_AGENT_AUDIT_PERMISSION)
def agent_audit_detail(request: HttpRequest, execution_id) -> HttpResponse:
    execution = get_object_or_404(
        AgentExecution.objects.select_related("user").prefetch_related(
            "tool_executions"
        ),
        pk=execution_id,
    )
    return render(
        request,
        "web/admin/audit_detail.html",
        {"execution": execution},
    )
