import json
from decimal import Decimal

import pytest

from apps.agent.core import ReplenishAgent
from apps.agent.providers import FakeLLMProvider, LLMResponse, ToolCall
from apps.agent.tools import (
    ToolExecutionContext,
    ToolExecutionPolicy,
    create_default_tool_registry,
)
from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def product_relation():
    product = Product.objects.create(
        name="Produto do fluxo",
        sku="FLOW-001",
        minimum_stock=5,
    )
    supplier = Supplier.objects.create(name="Fornecedor do fluxo")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
        lead_time_days=3,
        is_preferred=True,
    )
    return product, relation


def test_complete_stock_then_replenishment_flow(product_relation):
    product, relation = product_relation
    Inventory.objects.create(product=product, current_quantity=2)
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="stock-call",
                        name="consultar_estoque",
                        arguments={"product_id": product.pk},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="analysis-call",
                        name="calcular_reposicao",
                        arguments={
                            "product_supplier_id": relation.pk,
                            "consumption_days": 30,
                            "planning_days": 30,
                        },
                    ),
                )
            ),
            LLMResponse(content="Precisamos preparar a reposicao."),
        ]
    )
    agent = ReplenishAgent(
        provider=provider,
        tools=create_default_tool_registry(),
    )

    answer = agent.run("Analise o produto e veja se precisamos comprar mais.")

    assert answer == "Precisamos preparar a reposicao."
    final_tools = [
        message
        for message in provider.calls[2].messages
        if message.role.value == "tool"
    ]
    assert [message.tool_name for message in final_tools] == [
        "consultar_estoque",
        "calcular_reposicao",
    ]
    stock_result = json.loads(final_tools[0].content)
    analysis_result = json.loads(final_tools[1].content)
    assert stock_result["data"]["current_quantity"] == 2
    analysis = analysis_result["data"]
    assert analysis["current_stock"] == "2"
    assert analysis["recommended_quantity"] == "3"
    assert provider.calls[2].messages[2].tool_calls[0].id == "stock-call"
    assert provider.calls[2].messages[4].tool_calls[0].id == "analysis-call"


def test_complete_write_enabled_proposal_flow_stays_pending(product_relation):
    product, relation = product_relation
    inventory = Inventory.objects.create(product=product, current_quantity=0)
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="analysis-call",
                        name="calcular_reposicao",
                        arguments={"product_supplier_id": relation.pk},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="proposal-call",
                        name="criar_proposta_compra",
                        arguments={"product_supplier_id": relation.pk},
                    ),
                )
            ),
            LLMResponse(content="Proposta pendente preparada."),
        ]
    )
    agent = ReplenishAgent(
        provider=provider,
        tools=create_default_tool_registry(),
        policy=ToolExecutionPolicy(allow_write=True),
        context=ToolExecutionContext(
            user_id=1,
            is_authenticated=True,
            permissions=frozenset({"agent.execute_agent_write"}),
        ),
    )

    answer = agent.run("Prepare uma proposta de compra para esse produto.")

    proposal = PurchaseProposal.objects.get()
    inventory.refresh_from_db()
    assert answer == "Proposta pendente preparada."
    assert proposal.status == PurchaseProposal.Status.PENDING
    assert proposal.reviewed_at is None
    assert proposal.quantity == 5
    assert proposal.unit_price == Decimal("10.00")
    assert proposal.total_price == Decimal("50.00")
    assert inventory.current_quantity == 0
    assert StockMovement.objects.count() == 0

    final_history = provider.calls[2].messages
    assert [message.tool_name for message in final_history if message.tool_name] == [
        "calcular_reposicao",
        "criar_proposta_compra",
    ]
    proposal_result = json.loads(final_history[-1].content)
    assert proposal_result["data"]["status"] == "PENDING"


def test_named_product_analysis_uses_deterministic_tool_without_write(product_relation):
    product, _relation = product_relation
    Inventory.objects.create(product=product, current_quantity=0)
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="named-analysis",
                        name="calcular_reposicao",
                        arguments={
                            "name": product.name,
                            "product_supplier_id": None,
                            "consumption_days": "30",
                            "planning_days": "30",
                        },
                    ),
                )
            ),
            LLMResponse(content="Reposição recomendada com base no cálculo."),
        ]
    )
    answer = ReplenishAgent(
        provider=provider, tools=create_default_tool_registry()
    ).run("Analise a situação do produto.")

    result = json.loads(provider.calls[1].messages[-1].content)
    assert answer == "Reposição recomendada com base no cálculo."
    assert result["ok"] is True
    assert result["data"]["current_stock"] == "0"
    assert result["data"]["recommended_quantity"] == "5"
    assert PurchaseProposal.objects.count() == 0
    assert [
        message.tool_name for message in provider.calls[1].messages if message.tool_name
    ] == ["calcular_reposicao"]
