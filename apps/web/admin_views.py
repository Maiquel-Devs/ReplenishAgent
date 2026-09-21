from __future__ import annotations

from collections.abc import Callable
import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404, redirect, render

from apps.agent.audit import ToolExecutionStatus
from apps.agent.configuration import (
    configuration_status,
    discover_ollama_models,
    current_ai_configuration,
    save_ai_configuration,
)
from apps.agent.models import AIConfigurationChange, AgentExecution, AgentToolExecution
from apps.agent.providers.base import LLMProviderError
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import (
    approve_purchase_proposal,
    reject_purchase_proposal,
)

from .authorization import (
    CONFIGURE_AI_PERMISSION,
    REVIEW_PROPOSAL_PERMISSION,
    VIEW_AGENT_AUDIT_PERMISSION,
    administration_required,
    permission_required,
)
from .ai_forms import AIConfigurationForm, OllamaConnectionForm
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
            ).select_related("execution", "execution__user")[:5]
        ),
    }
    return render(request, "web/admin/overview.html", context)


@permission_required(CONFIGURE_AI_PERMISSION)
def ai_configuration(request: HttpRequest) -> HttpResponse:
    configuration = current_ai_configuration()
    probe_result = None
    available_models = ()
    if request.method == "POST":
        form = AIConfigurationForm(request.POST, instance=configuration)
        action = request.POST.get("action", "save")
        if action == "save":
            if form.is_valid():
                save_ai_configuration(form.save(commit=False), user=request.user)
                messages.success(request, "Configuração da IA salva.")
                return redirect("web:ai_configuration")
        elif action == "test":
            probe_form = OllamaConnectionForm(request.POST)
            if probe_form.is_valid():
                try:
                    available_models = discover_ollama_models(
                        probe_form.cleaned_data["local_endpoint"]
                    )
                except LLMProviderError:
                    probe_result = {
                        "ok": False,
                        "message": "Não foi possível conectar ao Ollama ou consultar os modelos.",
                    }
                else:
                    count = len(available_models)
                    model_label = (
                        "modelo disponível" if count == 1 else "modelos disponíveis"
                    )
                    probe_result = {
                        "ok": True,
                        "message": f"Ollama conectado. {count} {model_label}.",
                    }
            else:
                first_error = next(iter(probe_form.errors.values()))[0]
                probe_result = {"ok": False, "message": first_error}
        else:
            return HttpResponseBadRequest("Ação inválida.")
    elif request.method == "GET":
        form = AIConfigurationForm(
            instance=configuration,
            initial={"type": "LOCAL", "integration": "ollama", "is_active": True}
            if configuration is None
            else None,
        )
    else:
        return HttpResponseNotAllowed(["GET", "POST"])
    return render(
        request,
        "web/admin/ai_configuration.html",
        {
            "form": form,
            "configuration": configuration,
            "configuration_status": configuration_status(configuration),
            "credential_configured": bool(
                os.environ.get("MISTRAL_API_KEY", "").strip()
            ),
            "recent_changes": AIConfigurationChange.objects.select_related("user")[:5],
            "probe_result": probe_result,
            "available_models": available_models,
        },
    )


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
