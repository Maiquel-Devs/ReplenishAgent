import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.agent.providers import ToolCall
from apps.agent.tools import (
    ToolExecutionContext,
    ToolExecutionPolicy,
    ToolPermission,
    create_default_tool_registry,
)
from apps.inventory.models import Inventory, StockMovement
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def product():
    return Product.objects.create(
        name="Cafe especial",
        sku="AGENT-001",
        minimum_stock=5,
    )


@pytest.fixture
def relation(product):
    supplier = Supplier.objects.create(name="Fornecedor preferencial")
    return ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("12.50"),
        lead_time_days=5,
        is_preferred=True,
    )


@pytest.fixture
def registry():
    return create_default_tool_registry()


def execute(registry, name, arguments, *, allow_write=False):
    return registry.execute(
        ToolCall(id="test-call", name=name, arguments=arguments),
        policy=ToolExecutionPolicy(allow_write=allow_write),
        context=(
            ToolExecutionContext(
                user_id=1,
                is_authenticated=True,
                permissions=frozenset({"agent.execute_agent_write"}),
            )
            if allow_write
            else ToolExecutionContext()
        ),
    )


def assert_json_serializable(result):
    serialized = json.dumps(result)
    assert serialized
    assert "QuerySet" not in serialized
    assert "Product:" not in serialized


def test_default_registry_contains_expected_tools_and_permissions(registry):
    expected = {
        "consultar_produto": ToolPermission.READ,
        "consultar_estoque": ToolPermission.READ,
        "consultar_movimentacoes": ToolPermission.READ,
        "consultar_consumo": ToolPermission.COMPUTE,
        "consultar_fornecedores": ToolPermission.READ,
        "calcular_reposicao": ToolPermission.COMPUTE,
        "consultar_produtos_em_risco": ToolPermission.COMPUTE,
        "criar_proposta_compra": ToolPermission.WRITE,
    }

    assert {name: registry.get(name).permission for name in expected} == expected


def test_consultar_produto_returns_only_serializable_fields(registry, product):
    result = execute(registry, "consultar_produto", {"product_id": product.pk})

    assert result == {
        "ok": True,
        "data": {
            "id": product.pk,
            "sku": "AGENT-001",
            "name": "Cafe especial",
            "minimum_stock": 5,
            "is_active": True,
        },
    }
    assert_json_serializable(result)


def test_consultar_produto_handles_missing_product(registry):
    result = execute(registry, "consultar_produto", {"product_id": 999999})

    assert result["ok"] is False
    assert result["error"]["code"] == "resource_not_found"


def test_consultar_estoque_reads_inventory_without_changing_it(registry, product):
    inventory = Inventory.objects.create(product=product, current_quantity=17)

    result = execute(registry, "consultar_estoque", {"product_id": product.pk})

    inventory.refresh_from_db()
    assert result["data"]["current_quantity"] == 17
    assert inventory.current_quantity == 17
    assert StockMovement.objects.count() == 0


def test_consultar_estoque_treats_missing_inventory_as_zero(registry, product):
    result = execute(registry, "consultar_estoque", {"product_id": product.pk})

    assert result["data"]["current_quantity"] == 0
    assert result["data"]["summary"] == "Estoque atual: 0 unidades."
    assert not Inventory.objects.filter(product=product).exists()


def test_consultar_movimentacoes_applies_default_limit_and_serializes_dates(
    registry,
    product,
):
    now = timezone.now()
    for offset in range(25):
        StockMovement.objects.create(
            product=product,
            type=StockMovement.Type.OUT,
            quantity=offset + 1,
            occurred_at=now - timedelta(minutes=offset),
        )

    result = execute(
        registry,
        "consultar_movimentacoes",
        {"product_id": product.pk},
    )

    assert result["data"]["limit"] == 20
    assert len(result["data"]["movements"]) == 20
    assert isinstance(result["data"]["movements"][0]["occurred_at"], str)
    assert_json_serializable(result)


@pytest.mark.parametrize("limit", [0, 51, "ten", True])
def test_consultar_movimentacoes_rejects_invalid_limits(
    registry,
    product,
    limit,
):
    result = execute(
        registry,
        "consultar_movimentacoes",
        {"product_id": product.pk, "limit": limit},
    )

    assert result["error"]["code"] == "invalid_arguments"


def test_consultar_consumo_reuses_domain_service_and_serializes_decimal(
    registry,
    product,
):
    StockMovement.objects.create(
        product=product,
        type=StockMovement.Type.OUT,
        quantity=30,
        occurred_at=timezone.now() - timedelta(days=1),
    )

    result = execute(
        registry,
        "consultar_consumo",
        {"product_id": product.pk, "days": 30},
    )

    assert result["data"]["period_days"] == 30
    assert result["data"]["average_daily_consumption"] == "1"
    assert_json_serializable(result)


def test_consultar_fornecedores_returns_relationship_data(
    registry,
    product,
    relation,
):
    result = execute(
        registry,
        "consultar_fornecedores",
        {"product_id": product.pk},
    )

    supplier = result["data"]["suppliers"][0]
    assert supplier == {
        "product_supplier_id": relation.pk,
        "supplier_id": relation.supplier_id,
        "supplier_name": "Fornecedor preferencial",
        "price": "12.50",
        "lead_time_days": 5,
        "is_preferred": True,
    }
    assert_json_serializable(result)


def test_calcular_reposicao_uses_deterministic_engine(
    registry,
    product,
    relation,
):
    Inventory.objects.create(product=product, current_quantity=20)
    StockMovement.objects.create(
        product=product,
        type=StockMovement.Type.OUT,
        quantity=60,
        occurred_at=timezone.now() - timedelta(days=1),
    )

    result = execute(
        registry,
        "calcular_reposicao",
        {
            "product_supplier_id": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
    )

    data = result["data"]
    assert data["current_stock"] == "20"
    assert data["average_daily_consumption"] == "2"
    assert data["recommended_quantity"] == "45"
    assert data["risk_level"] == "LOW"
    assert data["supplier_name"] == "Fornecedor preferencial"
    assert_json_serializable(result)


def test_calcular_reposicao_handles_missing_relation(registry):
    result = execute(
        registry,
        "calcular_reposicao",
        {"product_supplier_id": 999999},
    )

    assert result["error"]["code"] == "resource_not_found"


def test_produtos_em_risco_is_bounded_serializable_and_uses_four_queries(
    registry,
    relation,
    django_assert_num_queries,
):
    with django_assert_num_queries(4):
        result = execute(
            registry,
            "consultar_produtos_em_risco",
            {"limit": 5},
        )

    assert result["data"]["limit"] == 5
    assert result["data"]["products"][0]["risk_level"] == "CRITICAL"
    assert_json_serializable(result)


def test_produtos_em_risco_rejects_unbounded_limit(registry):
    result = execute(
        registry,
        "consultar_produtos_em_risco",
        {"limit": 51},
    )

    assert result["error"]["code"] == "invalid_arguments"


def test_create_proposal_is_blocked_by_default(
    registry,
    product,
    relation,
):
    result = execute(
        registry,
        "criar_proposta_compra",
        {"product_supplier_id": relation.pk},
    )

    assert result["error"]["code"] == "not_authorized"
    assert PurchaseProposal.objects.count() == 0


def test_create_proposal_uses_real_analysis_and_stays_pending(
    registry,
    product,
    relation,
):
    inventory = Inventory.objects.create(product=product, current_quantity=0)
    result = execute(
        registry,
        "criar_proposta_compra",
        {
            "product_supplier_id": relation.pk,
            "consumption_days": 30,
            "planning_days": 30,
        },
        allow_write=True,
    )

    proposal = PurchaseProposal.objects.get()
    inventory.refresh_from_db()
    assert result["ok"] is True
    assert result["data"]["proposal_id"] == proposal.pk
    assert result["data"]["unit_price"] == "12.50"
    assert result["data"]["total_price"] == "62.50"
    assert proposal.quantity == 5
    assert proposal.status == PurchaseProposal.Status.PENDING
    assert proposal.reviewed_at is None
    assert inventory.current_quantity == 0
    assert StockMovement.objects.count() == 0


def test_create_proposal_rejects_zero_recommendation_as_domain_error(
    registry,
    product,
    relation,
):
    Inventory.objects.create(product=product, current_quantity=100)

    result = execute(
        registry,
        "criar_proposta_compra",
        {"product_supplier_id": relation.pk},
        allow_write=True,
    )

    assert result["error"]["code"] == "domain_error"
    assert PurchaseProposal.objects.count() == 0


def test_unexpected_arguments_are_rejected_before_database_access(
    registry,
    django_assert_num_queries,
):
    with django_assert_num_queries(0):
        result = execute(
            registry,
            "consultar_produto",
            {"product_id": 1, "python_function": "dangerous"},
        )

    assert result["error"]["code"] == "invalid_arguments"


def test_consultar_produto_finds_name_without_guessing_id(registry, product):
    result = execute(registry, "consultar_produto", {"name": " cafe especial "})
    assert result["ok"] is True
    assert result["data"]["id"] == product.pk
    assert result["data"]["name"] == product.name


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"name": " "},
        {"name": "x" * 256},
        {"name": "Cafe especial", "product_id": 1},
    ],
)
def test_consultar_produto_requires_exactly_one_valid_identifier(registry, arguments):
    result = execute(registry, "consultar_produto", arguments)
    assert result["error"]["code"] == "invalid_arguments"


def test_consultar_produto_rejects_ambiguous_or_unknown_names(registry, product):
    missing = execute(registry, "consultar_produto", {"name": "Inexistente"})
    assert missing["error"]["code"] == "resource_not_found"
    Product.objects.create(name="CAFE ESPECIAL", sku="AGENT-002")
    ambiguous = execute(registry, "consultar_produto", {"name": "Cafe especial"})
    assert ambiguous["error"]["code"] == "domain_error"


def test_tool_definitions_explain_read_compute_and_write_boundaries(registry):
    definitions = {item.name: item for item in registry.definitions()}
    assert "nome" in definitions["consultar_produto"].description
    assert "name" in definitions["consultar_produto"].parameters["properties"]
    assert "READ" in definitions["consultar_estoque"].description
    assert "COMPUTE" in definitions["calcular_reposicao"].description
    proposal = definitions["criar_proposta_compra"].description
    assert "WRITE" in proposal
    assert "ALTERA DADOS" in proposal
    assert "pedido explícito" in proposal
    assert "recomendação" in proposal


def test_consultar_estoque_accepts_exact_product_name(registry, product):
    Inventory.objects.create(product=product, current_quantity=17)
    result = execute(registry, "consultar_estoque", {"name": "CAFE ESPECIAL"})
    assert result["ok"] is True
    assert result["data"]["product_id"] == product.pk
    assert result["data"]["current_quantity"] == 17


def test_consultar_estoque_rejects_mixed_or_fabricated_identity(registry, product):
    mixed = execute(
        registry,
        "consultar_estoque",
        {"name": product.name, "product_id": product.pk},
    )
    invented = execute(
        registry,
        "consultar_estoque",
        {"name": product.name, "product_id": "consultar_produto"},
    )
    assert mixed["error"]["code"] == "invalid_arguments"
    assert invented["error"]["code"] == "invalid_arguments"


def test_consumption_and_suppliers_accept_product_name(registry, product, relation):
    consumption = execute(registry, "consultar_consumo", {"name": product.name})
    suppliers = execute(registry, "consultar_fornecedores", {"name": product.name})
    assert consumption["ok"] is True
    assert consumption["data"]["product_id"] == product.pk
    assert suppliers["ok"] is True
    assert suppliers["data"]["suppliers"][0]["product_supplier_id"] == relation.pk


def test_replenishment_analysis_by_name_uses_preferred_relation_without_write(
    registry, product, relation
):
    other_supplier = Supplier.objects.create(name="Outro fornecedor")
    ProductSupplier.objects.create(
        product=product,
        supplier=other_supplier,
        price=Decimal("9.00"),
        lead_time_days=2,
        is_preferred=False,
    )
    relation.is_preferred = True
    relation.save(update_fields=["is_preferred"])
    Inventory.objects.create(product=product, current_quantity=0)
    result = execute(registry, "calcular_reposicao", {"name": "CAFE ESPECIAL"})
    assert result["ok"] is True
    assert result["data"]["product_supplier_id"] == relation.pk
    assert result["data"]["current_stock"] == "0"
    assert result["data"]["stock_coverage_days"] is None
    assert result["data"]["recommended_quantity"] == "5"
    assert result["data"]["summary"] == (
        "Estoque atual: 0 unidades. Risco: CRITICAL. "
        "Quantidade recomendada para reposição: 5 unidades. "
        "Conclusão: reposição necessária."
    )
    assert PurchaseProposal.objects.count() == 0


def test_replenishment_analysis_by_name_rejects_ambiguous_identity(
    registry, product, relation
):
    result = execute(
        registry,
        "calcular_reposicao",
        {"name": product.name, "product_supplier_id": relation.pk},
    )
    assert result["error"]["code"] == "invalid_arguments"
    assert PurchaseProposal.objects.count() == 0


def test_numeric_text_limit_is_normalized_before_bounded_query(registry, product):
    result = execute(
        registry,
        "consultar_movimentacoes",
        {"product_id": product.pk, "limit": "10"},
    )
    assert result["ok"] is True
    assert result["data"]["limit"] == 10


def test_identity_tool_schemas_require_exactly_one_name_or_numeric_id(registry):
    definitions = {definition.name: definition for definition in registry.definitions()}

    def required_fields(tool_name):
        parameters = definitions[tool_name].parameters
        assert "anyOf" not in parameters
        return tuple(
            branch["required"][0]
            for branch in parameters["oneOf"]
        )

    assert required_fields("consultar_produto") == ("name", "product_id")
    assert required_fields("consultar_estoque") == ("name", "product_id")
    assert required_fields("consultar_consumo") == ("name", "product_id")
    assert required_fields("calcular_reposicao") == ("name", "product_supplier_id")
    assert required_fields("consultar_fornecedores") == ("name", "product_id")
