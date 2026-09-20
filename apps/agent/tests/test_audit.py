from concurrent.futures import ThreadPoolExecutor
import json
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections

from apps.agent.audit import AgentExecutionStatus, ToolExecutionStatus
from apps.agent.audit_django import DjangoAgentAuditRecorder
from apps.agent.authorization import tool_context_for_user
from apps.agent.core import AgentIterationLimitError, ReplenishAgent
from apps.agent.models import AgentExecution, AgentToolExecution
from apps.agent.providers import (
    FakeLLMProvider,
    LLMProviderError,
    LLMResponse,
    ToolCall,
)
from apps.agent.tools import (
    ExecutableTool,
    ToolDomainError,
    ToolExecutionPolicy,
    ToolPermission,
    ToolRegistry,
    create_default_tool_registry,
)
from apps.inventory.models import Inventory
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="agent-operator")


@pytest.fixture
def write_user(user):
    permission = Permission.objects.get(codename="execute_agent_write")
    user.user_permissions.add(permission)
    return user


def make_tool(name, permission, handler, properties=None):
    properties = properties or {"value": {"type": "integer"}}
    return ExecutableTool(
        name=name,
        description=f"Tool {name}",
        parameters={
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
        permission=permission,
        handler=handler,
    )


def audited_agent(provider, registry, user, *, max_iterations=8, allow_write=True):
    return ReplenishAgent(
        provider=provider,
        tools=registry,
        policy=ToolExecutionPolicy(allow_write=allow_write),
        context=tool_context_for_user(user),
        audit=DjangoAgentAuditRecorder(),
        max_iterations=max_iterations,
    )


def test_completed_execution_records_identity_provider_model_and_response(user):
    provider = FakeLLMProvider([LLMResponse(content="Final")])

    result = audited_agent(provider, ToolRegistry(), user).run("Request")

    execution = AgentExecution.objects.get()
    assert result == "Final"
    assert execution.user == user
    assert execution.provider == "FakeLLMProvider"
    assert execution.model == ""
    assert execution.status == AgentExecutionStatus.COMPLETED.value
    assert execution.user_request == "Request"
    assert execution.final_response == "Final"
    assert execution.finished_at is not None
    assert execution.duration_ms is not None
    assert execution.error_code == ""


def test_execution_redacts_secrets_from_observable_text(user):
    provider = FakeLLMProvider(
        [LLMResponse(content="Authorization: Bearer response-secret")]
    )

    audited_agent(provider, ToolRegistry(), user).run(
        "password=request-secret"
    )

    execution = AgentExecution.objects.get()
    assert execution.user_request == "password=[REDACTED]"
    assert execution.final_response == "Authorization: [REDACTED]"


def test_execution_failure_is_recorded_without_internal_message(user):
    provider = FakeLLMProvider([])

    with pytest.raises(LLMProviderError):
        audited_agent(provider, ToolRegistry(), user).run("Will fail")

    execution = AgentExecution.objects.get()
    assert execution.status == AgentExecutionStatus.FAILED.value
    assert execution.error_code == "agent_error"
    assert execution.final_response == ""


def test_iteration_limit_is_recorded(user):
    call = ToolCall(id="loop", name="read", arguments={"value": 1})
    provider = FakeLLMProvider(
        [
            LLMResponse(tool_calls=(call,)),
            LLMResponse(tool_calls=(ToolCall(id="loop-2", name="read", arguments={"value": 2}),)),
        ]
    )
    registry = ToolRegistry(
        [make_tool("read", ToolPermission.READ, lambda arguments, context: arguments)]
    )

    with pytest.raises(AgentIterationLimitError):
        audited_agent(
            provider,
            registry,
            user,
            max_iterations=2,
        ).run("Loop")

    execution = AgentExecution.objects.get()
    assert execution.status == AgentExecutionStatus.LIMIT_REACHED.value
    assert execution.error_code == "iteration_limit"


def test_tool_events_record_executed_blocked_and_failed(user):
    registry = ToolRegistry(
        [
            make_tool(
                "read",
                ToolPermission.READ,
                lambda arguments, context: {"value": arguments["value"]},
            ),
            make_tool(
                "write",
                ToolPermission.WRITE,
                lambda arguments, context: {"saved": True},
            ),
            make_tool(
                "failing",
                ToolPermission.COMPUTE,
                lambda arguments, context: (_ for _ in ()).throw(
                    ToolDomainError("Controlled failure")
                ),
            ),
        ]
    )
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(id="read-1", name="read", arguments={"value": 1}),
                    ToolCall(id="write-1", name="write", arguments={"value": 2}),
                    ToolCall(id="fail-1", name="failing", arguments={"value": 3}),
                )
            ),
            LLMResponse(content="Done"),
        ]
    )

    audited_agent(provider, registry, user).run("Use tools")

    events = {event.tool_call_id: event for event in AgentToolExecution.objects.all()}
    assert events["read-1"].status == ToolExecutionStatus.EXECUTED.value
    assert events["write-1"].status == ToolExecutionStatus.BLOCKED.value
    assert events["write-1"].error_code == "not_authorized"
    assert events["fail-1"].status == ToolExecutionStatus.FAILED.value
    assert events["fail-1"].error_code == "domain_error"


def test_audit_sanitizes_sensitive_arguments_and_results(user):
    tool = make_tool(
        "safe",
        ToolPermission.READ,
        lambda arguments, context: {
            "api_key": "result-secret",
            "visible": "ok",
        },
        properties={
            "token": {"type": "string"},
            "visible": {"type": "string"},
        },
    )
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="safe-1",
                        name="safe",
                        arguments={"token": "input-secret", "visible": "hello"},
                    ),
                )
            ),
            LLMResponse(content="Done"),
        ]
    )

    audited_agent(provider, ToolRegistry([tool]), user).run("Sensitive")

    event = AgentToolExecution.objects.get()
    assert event.arguments == {"token": "[REDACTED]", "visible": "hello"}
    assert event.result["data"]["api_key"] == "[REDACTED]"
    assert event.result["data"]["visible"] == "ok"


def proposal_setup():
    product = Product.objects.create(
        name="Idempotent product",
        sku=f"IDEMP-{uuid4()}",
        minimum_stock=5,
    )
    supplier = Supplier.objects.create(name=f"Supplier {uuid4()}")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("10.00"),
        lead_time_days=2,
    )
    Inventory.objects.create(product=product, current_quantity=0)
    return relation


def proposal_call(call_id, relation):
    return ToolCall(
        id=call_id,
        name="criar_proposta_compra",
        arguments={"product_supplier_id": relation.pk},
    )


def test_repeated_write_tool_call_in_same_execution_is_idempotent(write_user):
    relation = proposal_setup()
    repeated = proposal_call("same-call", relation)
    provider = FakeLLMProvider(
        [
            LLMResponse(tool_calls=(repeated,)),
            LLMResponse(tool_calls=(repeated,)),
            LLMResponse(content="Done"),
        ]
    )

    audited_agent(
        provider,
        create_default_tool_registry(),
        write_user,
    ).run("Create once")

    assert PurchaseProposal.objects.count() == 1
    assert AgentToolExecution.objects.count() == 1
    first_result = provider.calls[1].messages[-1].content
    second_result = provider.calls[2].messages[-1].content
    assert json.loads(first_result) == json.loads(second_result)


def test_different_write_call_ids_remain_distinct_actions(write_user):
    relation = proposal_setup()
    provider = FakeLLMProvider(
        [
            LLMResponse(tool_calls=(proposal_call("call-a", relation),)),
            LLMResponse(tool_calls=(proposal_call("call-b", relation),)),
            LLMResponse(content="Done"),
        ]
    )

    audited_agent(
        provider,
        create_default_tool_registry(),
        write_user,
    ).run("Create twice explicitly")

    assert PurchaseProposal.objects.count() == 2
    assert AgentToolExecution.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_retry_of_same_write_call_creates_one_proposal():
    user = get_user_model().objects.create_user(username="concurrent-agent")
    permission = Permission.objects.get(codename="execute_agent_write")
    user.user_permissions.add(permission)
    context = tool_context_for_user(user, execution_id=str(uuid4()))
    recorder = DjangoAgentAuditRecorder()
    execution_id = recorder.start(
        context=context,
        provider="FakeLLMProvider",
        model="",
        user_request="Concurrent write",
    )
    relation = proposal_setup()
    call = proposal_call("concurrent-call", relation)
    registry = create_default_tool_registry()
    policy = ToolExecutionPolicy(allow_write=True)
    barrier = Barrier(2)

    def execute():
        close_old_connections()
        try:
            barrier.wait()
            return recorder.execute_tool(
                execution_id,
                call=call,
                permission_level=ToolPermission.WRITE.value,
                operation=lambda: registry.execute(
                    call,
                    policy=policy,
                    context=context,
                ),
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(execute), executor.submit(execute)]
        values = [future.result() for future in results]

    assert values[0] == values[1]
    assert PurchaseProposal.objects.count() == 1
    assert AgentToolExecution.objects.count() == 1


def test_models_do_not_store_chain_of_thought_fields():
    field_names = {field.name for field in AgentExecution._meta.fields}
    assert "reasoning" not in field_names
    assert "chain_of_thought" not in field_names
    assert "internal_thoughts" not in field_names
    assert "hidden_reasoning" not in field_names
