from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError


from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.services import create_purchase_proposal
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.replenishment.services import (
    analyze_replenishment,
    analyze_replenishments,
    calculate_average_daily_consumption,
)
from apps.suppliers.models import ProductSupplier

from .base import (
    ExecutableTool,
    ToolDomainError,
    ToolExecutionContext,
    ToolPermission,
    ToolResourceNotFoundError,
)
from .registry import ToolRegistry


DEFAULT_CONSUMPTION_DAYS = 30
DEFAULT_PLANNING_DAYS = 30
DEFAULT_MOVEMENT_LIMIT = 20
MAX_MOVEMENT_LIMIT = 50
DEFAULT_SUPPLIER_LIMIT = 20
MAX_SUPPLIER_LIMIT = 50
DEFAULT_RISK_LIMIT = 10
MAX_RISK_LIMIT = 50
MAX_RISK_SCAN = 100


def _product(product_id: int) -> Product:
    try:
        return Product.objects.only(
            "id", "sku", "name", "minimum_stock", "is_active"
        ).get(pk=product_id)
    except Product.DoesNotExist as exc:
        raise ToolResourceNotFoundError("Product was not found.") from exc


def _relation(product_supplier_id: int) -> ProductSupplier:
    try:
        return ProductSupplier.objects.select_related(
            "product", "supplier"
        ).get(pk=product_supplier_id)
    except ProductSupplier.DoesNotExist as exc:
        raise ToolResourceNotFoundError(
            "Product-supplier relationship was not found."
        ) from exc


def _analysis_data(analysis: ReplenishmentAnalysis) -> dict[str, Any]:
    return {
        "product_id": analysis.product.pk,
        "sku": analysis.product.sku,
        "current_stock": analysis.current_stock,
        "average_daily_consumption": analysis.average_daily_consumption,
        "stock_coverage_days": analysis.stock_coverage_days,
        "lead_time_days": analysis.lead_time_days,
        "minimum_stock": analysis.minimum_stock,
        "reorder_point": analysis.reorder_point,
        "planning_days": analysis.planning_days,
        "target_stock": analysis.target_stock,
        "recommended_quantity": analysis.recommended_quantity,
        "risk_level": analysis.risk_level,
    }


def _domain_message(error: ValidationError) -> str:
    if hasattr(error, "message_dict"):
        return " ".join(
            message
            for messages in error.message_dict.values()
            for message in messages
        )
    return " ".join(error.messages)


def consultar_produto(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    product = _product(arguments["product_id"])
    return {
        "id": product.pk,
        "sku": product.sku,
        "name": product.name,
        "minimum_stock": product.minimum_stock,
        "is_active": product.is_active,
    }


def consultar_estoque(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    product = _product(arguments["product_id"])
    quantity = (
        Inventory.objects.filter(product_id=product.pk)
        .values_list("current_quantity", flat=True)
        .first()
    )
    return {
        "product_id": product.pk,
        "sku": product.sku,
        "current_quantity": quantity if quantity is not None else 0,
    }


def consultar_movimentacoes(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    product = _product(arguments["product_id"])
    limit = arguments["limit"]
    rows = list(
        StockMovement.objects.filter(product_id=product.pk)
        .values("id", "type", "quantity", "occurred_at", "note")[:limit]
    )
    return {
        "product_id": product.pk,
        "sku": product.sku,
        "limit": limit,
        "movements": rows,
    }


def consultar_consumo(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    product = _product(arguments["product_id"])
    days = arguments["days"]
    average = calculate_average_daily_consumption(product, days)
    return {
        "product_id": product.pk,
        "sku": product.sku,
        "period_days": days,
        "average_daily_consumption": average,
    }


def consultar_fornecedores(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    product = _product(arguments["product_id"])
    limit = arguments["limit"]
    relations = list(
        ProductSupplier.objects.filter(product_id=product.pk)
        .select_related("supplier")
        .order_by("-is_preferred", "supplier__name", "pk")[:limit]
    )
    return {
        "product_id": product.pk,
        "sku": product.sku,
        "suppliers": [
            {
                "product_supplier_id": relation.pk,
                "supplier_id": relation.supplier_id,
                "supplier_name": relation.supplier.name,
                "price": relation.price,
                "lead_time_days": relation.lead_time_days,
                "is_preferred": relation.is_preferred,
            }
            for relation in relations
        ],
    }


def calcular_reposicao(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    relation = _relation(arguments["product_supplier_id"])
    analysis = analyze_replenishment(
        product_supplier=relation,
        consumption_days=arguments["consumption_days"],
        planning_days=arguments["planning_days"],
    )
    data = _analysis_data(analysis)
    data["product_supplier_id"] = relation.pk
    data["supplier_id"] = relation.supplier_id
    data["supplier_name"] = relation.supplier.name
    return data


def consultar_produtos_em_risco(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    limit = arguments["limit"]
    relations = list(
        ProductSupplier.objects.filter(product__is_active=True)
        .select_related("product")
        .order_by("product_id", "-is_preferred", "pk")
        .distinct("product_id")[:MAX_RISK_SCAN]
    )
    analyses = analyze_replenishments(
        product_suppliers=relations,
        consumption_days=arguments["consumption_days"],
        planning_days=arguments["planning_days"],
    )
    severity = {
        RiskLevel.CRITICAL: 0,
        RiskLevel.HIGH: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.LOW: 3,
    }
    analyses.sort(key=lambda item: (severity[item.risk_level], item.product.name))
    risky = [item for item in analyses if item.risk_level is not RiskLevel.LOW][
        :limit
    ]
    return {
        "limit": limit,
        "products": [
            {
                "product_id": analysis.product.pk,
                "sku": analysis.product.sku,
                "name": analysis.product.name,
                "current_stock": analysis.current_stock,
                "risk_level": analysis.risk_level,
                "recommended_quantity": analysis.recommended_quantity,
            }
            for analysis in risky
        ],
    }


def criar_proposta_compra(
    arguments: Mapping[str, Any],
    _context: ToolExecutionContext,
) -> dict[str, Any]:
    relation = _relation(arguments["product_supplier_id"])
    analysis = analyze_replenishment(
        product_supplier=relation,
        consumption_days=arguments["consumption_days"],
        planning_days=arguments["planning_days"],
    )
    try:
        proposal = create_purchase_proposal(
            product=relation.product,
            product_supplier=relation,
            analysis=analysis,
        )
    except ValidationError as exc:
        raise ToolDomainError(_domain_message(exc)) from exc
    return {
        "proposal_id": proposal.pk,
        "product_id": proposal.product_id,
        "supplier_id": proposal.supplier_id,
        "quantity": proposal.quantity,
        "unit_price": proposal.unit_price,
        "total_price": proposal.total_price,
        "risk_level": proposal.risk_level,
        "status": proposal.status,
    }


def _object_schema(
    properties: Mapping[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required,
        "additionalProperties": False,
    }


PRODUCT_ID = {"type": "integer", "minimum": 1}
RELATION_ID = {"type": "integer", "minimum": 1}
CONSUMPTION_DAYS = {
    "type": "integer",
    "minimum": 1,
    "maximum": 365,
    "default": DEFAULT_CONSUMPTION_DAYS,
}
PLANNING_DAYS = {
    "type": "integer",
    "minimum": 1,
    "maximum": 365,
    "default": DEFAULT_PLANNING_DAYS,
}


def create_default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ExecutableTool(
                name="consultar_produto",
                description="Consulta dados cadastrais de um produto pelo ID.",
                parameters=_object_schema(
                    {"product_id": PRODUCT_ID}, ["product_id"]
                ),
                permission=ToolPermission.READ,
                handler=consultar_produto,
            ),
            ExecutableTool(
                name="consultar_estoque",
                description="Consulta o estoque atual de um produto.",
                parameters=_object_schema(
                    {"product_id": PRODUCT_ID}, ["product_id"]
                ),
                permission=ToolPermission.READ,
                handler=consultar_estoque,
            ),
            ExecutableTool(
                name="consultar_movimentacoes",
                description="Consulta movimentacoes recentes de um produto.",
                parameters=_object_schema(
                    {
                        "product_id": PRODUCT_ID,
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_MOVEMENT_LIMIT,
                            "default": DEFAULT_MOVEMENT_LIMIT,
                        },
                    },
                    ["product_id"],
                ),
                permission=ToolPermission.READ,
                handler=consultar_movimentacoes,
            ),
            ExecutableTool(
                name="consultar_consumo",
                description="Calcula o consumo medio diario observado.",
                parameters=_object_schema(
                    {"product_id": PRODUCT_ID, "days": CONSUMPTION_DAYS},
                    ["product_id"],
                ),
                permission=ToolPermission.COMPUTE,
                handler=consultar_consumo,
            ),
            ExecutableTool(
                name="consultar_fornecedores",
                description="Consulta fornecedores vinculados a um produto.",
                parameters=_object_schema(
                    {
                        "product_id": PRODUCT_ID,
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_SUPPLIER_LIMIT,
                            "default": DEFAULT_SUPPLIER_LIMIT,
                        },
                    },
                    ["product_id"],
                ),
                permission=ToolPermission.READ,
                handler=consultar_fornecedores,
            ),
            ExecutableTool(
                name="calcular_reposicao",
                description="Calcula reposicao pelo motor deterministico.",
                parameters=_object_schema(
                    {
                        "product_supplier_id": RELATION_ID,
                        "consumption_days": CONSUMPTION_DAYS,
                        "planning_days": PLANNING_DAYS,
                    },
                    ["product_supplier_id"],
                ),
                permission=ToolPermission.COMPUTE,
                handler=calcular_reposicao,
            ),
            ExecutableTool(
                name="consultar_produtos_em_risco",
                description="Analisa produtos e lista riscos calculados.",
                parameters=_object_schema(
                    {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_RISK_LIMIT,
                            "default": DEFAULT_RISK_LIMIT,
                        },
                        "consumption_days": CONSUMPTION_DAYS,
                        "planning_days": PLANNING_DAYS,
                    },
                    [],
                ),
                permission=ToolPermission.COMPUTE,
                handler=consultar_produtos_em_risco,
            ),
            ExecutableTool(
                name="criar_proposta_compra",
                description=(
                    "Cria uma proposta pendente usando analise e preco reais."
                ),
                parameters=_object_schema(
                    {
                        "product_supplier_id": RELATION_ID,
                        "consumption_days": CONSUMPTION_DAYS,
                        "planning_days": PLANNING_DAYS,
                    },
                    ["product_supplier_id"],
                ),
                permission=ToolPermission.WRITE,
                handler=criar_proposta_compra,
            ),
        ]
    )
