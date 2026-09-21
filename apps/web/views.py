from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import F, IntegerField, Value
from django.db.models.functions import Coalesce
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.inventory.models import Inventory, StockMovement
from apps.inventory.services import register_stock_movement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import create_purchase_proposal
from apps.replenishment.services import analyze_replenishment
from apps.suppliers.models import ProductSupplier, Supplier

from apps.agent.configuration import AIConfigurationError
from apps.agent.core import AgentIterationLimitError
from apps.agent.providers import LLMProviderError

from .agent_service import run_agent
from .authorization import (
    ADD_PRODUCT_PERMISSION,
    ADD_PRODUCT_SUPPLIER_PERMISSION,
    ADD_PURCHASE_PROPOSAL_PERMISSION,
    ADD_STOCK_MOVEMENT_PERMISSION,
    ADD_SUPPLIER_PERMISSION,
    CHANGE_PRODUCT_PERMISSION,
    CHANGE_SUPPLIER_PERMISSION,
    permission_required,
)
from .forms import (
    AgentMessageForm,
    ProductForm,
    ProductSupplierForm,
    ReplenishmentRequestForm,
    StockMovementForm,
    SupplierForm,
)

AGENT_HISTORY_SESSION_KEY = "agent_conversation"
AGENT_HISTORY_LIMIT = 20


def _domain_error_message(error: ValidationError) -> str:
    if hasattr(error, "message_dict"):
        return " ".join(
            message
            for field_messages in error.message_dict.values()
            for message in field_messages
        )
    return " ".join(error.messages)


def _products_with_stock():
    return Product.objects.annotate(
        current_quantity=Coalesce(
            "inventory__current_quantity",
            Value(0),
            output_field=IntegerField(),
        )
    )


def agent_chat(request: HttpRequest) -> HttpResponse:
    form = AgentMessageForm(request.POST or None)
    history = request.session.get(AGENT_HISTORY_SESSION_KEY, [])

    if request.method == "POST" and form.is_valid():
        user_message = form.cleaned_data["message"]
        try:
            response = run_agent(user=request.user, message=user_message)
        except AIConfigurationError:
            form.add_error(
                None,
                "A configuração da IA está ausente, inativa ou incompleta. Solicite a revisão ao administrador.",
            )
        except LLMProviderError:
            form.add_error(
                None,
                "A IA configurada está indisponível no momento. Tente novamente mais tarde.",
            )
        except AgentIterationLimitError:
            form.add_error(
                None,
                "A IA não concluiu a resposta. Tente novamente com uma mensagem mais específica.",
            )
        else:
            history.extend(
                (
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": response},
                )
            )
            request.session[AGENT_HISTORY_SESSION_KEY] = history[-AGENT_HISTORY_LIMIT:]
            return redirect("web:agent_chat")

    return render(
        request,
        "web/agent_chat.html",
        {
            "form": form,
            "conversation": history,
        },
    )


def dashboard(request: HttpRequest) -> HttpResponse:
    attention_products = (
        _products_with_stock()
        .filter(is_active=True, current_quantity__lte=F("minimum_stock"))
        .order_by("name")
    )
    context = {
        "active_product_count": Product.objects.filter(is_active=True).count(),
        "low_stock_count": attention_products.count(),
        "pending_proposal_count": PurchaseProposal.objects.filter(
            status=PurchaseProposal.Status.PENDING
        ).count(),
        "attention_products": attention_products[:8],
        "latest_proposals": PurchaseProposal.objects.select_related(
            "product",
            "supplier",
        )[:5],
    }
    return render(request, "web/dashboard.html", context)


def product_list(request: HttpRequest) -> HttpResponse:
    products = _products_with_stock().order_by("name")
    return render(request, "web/product_list.html", {"products": products})


def product_detail(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(
        Product.objects.prefetch_related("product_suppliers__supplier"),
        pk=pk,
    )
    inventory = Inventory.objects.filter(product=product).first()
    return render(
        request,
        "web/product_detail.html",
        {"product": product, "inventory": inventory},
    )


@permission_required(ADD_PRODUCT_PERMISSION)
def product_create(request: HttpRequest) -> HttpResponse:
    form = ProductForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, "Produto cadastrado com sucesso.")
        return redirect("web:product_detail", pk=product.pk)
    return render(
        request,
        "web/model_form.html",
        {"form": form, "title": "Novo produto", "cancel_url": "web:product_list"},
    )


@permission_required(CHANGE_PRODUCT_PERMISSION)
def product_update(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid():
        product = form.save()
        messages.success(request, "Produto atualizado com sucesso.")
        return redirect("web:product_detail", pk=product.pk)
    return render(
        request,
        "web/model_form.html",
        {
            "form": form,
            "title": "Editar produto",
            "cancel_url": "web:product_detail",
            "cancel_pk": pk,
        },
    )


def supplier_list(request: HttpRequest) -> HttpResponse:
    suppliers = Supplier.objects.order_by("name")
    return render(request, "web/supplier_list.html", {"suppliers": suppliers})


def supplier_detail(request: HttpRequest, pk: int) -> HttpResponse:
    supplier = get_object_or_404(
        Supplier.objects.prefetch_related("product_suppliers__product"),
        pk=pk,
    )
    return render(request, "web/supplier_detail.html", {"supplier": supplier})


@permission_required(ADD_SUPPLIER_PERMISSION)
def supplier_create(request: HttpRequest) -> HttpResponse:
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        messages.success(request, "Fornecedor cadastrado com sucesso.")
        return redirect("web:supplier_detail", pk=supplier.pk)
    return render(
        request,
        "web/model_form.html",
        {"form": form, "title": "Novo fornecedor", "cancel_url": "web:supplier_list"},
    )


@permission_required(CHANGE_SUPPLIER_PERMISSION)
def supplier_update(request: HttpRequest, pk: int) -> HttpResponse:
    supplier = get_object_or_404(Supplier, pk=pk)
    form = SupplierForm(request.POST or None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        supplier = form.save()
        messages.success(request, "Fornecedor atualizado com sucesso.")
        return redirect("web:supplier_detail", pk=supplier.pk)
    return render(
        request,
        "web/model_form.html",
        {
            "form": form,
            "title": "Editar fornecedor",
            "cancel_url": "web:supplier_detail",
            "cancel_pk": pk,
        },
    )


def product_supplier_list(request: HttpRequest) -> HttpResponse:
    relations = ProductSupplier.objects.select_related(
        "product",
        "supplier",
    ).order_by("product__name", "supplier__name")
    return render(
        request,
        "web/product_supplier_list.html",
        {"relations": relations},
    )


@permission_required(ADD_PRODUCT_SUPPLIER_PERMISSION)
def product_supplier_create(request: HttpRequest) -> HttpResponse:
    form = ProductSupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Relação de fornecimento cadastrada.")
        return redirect("web:product_supplier_list")
    return render(
        request,
        "web/model_form.html",
        {
            "form": form,
            "title": "Nova relação produto-fornecedor",
            "cancel_url": "web:product_supplier_list",
        },
    )


def inventory_list(request: HttpRequest) -> HttpResponse:
    products = _products_with_stock().order_by("name")
    return render(request, "web/inventory_list.html", {"products": products})


def movement_list(request: HttpRequest) -> HttpResponse:
    movements = StockMovement.objects.select_related("product").order_by(
        "-occurred_at",
        "-pk",
    )
    return render(request, "web/movement_list.html", {"movements": movements})


@permission_required(ADD_STOCK_MOVEMENT_PERMISSION)
def movement_create(request: HttpRequest) -> HttpResponse:
    form = StockMovementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            register_stock_movement(
                product=data["product"],
                movement_type=data["movement_type"],
                quantity=data["quantity"],
                note=data["note"],
            )
        except ValidationError as error:
            form.add_error(None, _domain_error_message(error))
        else:
            movement_label = (
                "Entrada" if data["movement_type"] == StockMovement.Type.IN else "Saída"
            )
            messages.success(
                request,
                f"{movement_label} de {data['quantity']} unidades registrada.",
            )
            return redirect("web:movement_list")
    return render(request, "web/movement_form.html", {"form": form})


def replenishment_analysis(request: HttpRequest) -> HttpResponse:
    form = ReplenishmentRequestForm(request.POST or None)
    analysis = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            analysis = analyze_replenishment(
                product_supplier=data["product_supplier"],
                consumption_days=data["consumption_days"],
                planning_days=data["planning_days"],
            )
        except (ValidationError, ValueError, TypeError) as error:
            form.add_error(None, str(error))
    return render(
        request,
        "web/replenishment_analysis.html",
        {"form": form, "analysis": analysis},
    )


@require_POST
@permission_required(ADD_PURCHASE_PROPOSAL_PERMISSION)
def proposal_create_from_analysis(request: HttpRequest) -> HttpResponse:
    form = ReplenishmentRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Dados da análise inválidos.")
        return redirect("web:replenishment_analysis")

    data = form.cleaned_data
    try:
        analysis = analyze_replenishment(
            product_supplier=data["product_supplier"],
            consumption_days=data["consumption_days"],
            planning_days=data["planning_days"],
        )
        proposal = create_purchase_proposal(
            product=data["product"],
            product_supplier=data["product_supplier"],
            analysis=analysis,
        )
    except (ValidationError, ValueError, TypeError) as error:
        message = (
            _domain_error_message(error)
            if isinstance(error, ValidationError)
            else str(error)
        )
        messages.error(request, message)
        return redirect("web:replenishment_analysis")

    messages.success(request, "Proposta de compra criada com sucesso.")
    return redirect("web:proposal_detail", pk=proposal.pk)


def proposal_list(request: HttpRequest) -> HttpResponse:
    proposals = PurchaseProposal.objects.select_related(
        "product",
        "supplier",
    ).order_by("-created_at", "-pk")
    return render(request, "web/proposal_list.html", {"proposals": proposals})


def proposal_detail(request: HttpRequest, pk: int) -> HttpResponse:
    proposal = get_object_or_404(
        PurchaseProposal.objects.select_related("product", "supplier"),
        pk=pk,
    )
    return render(request, "web/proposal_detail.html", {"proposal": proposal})
