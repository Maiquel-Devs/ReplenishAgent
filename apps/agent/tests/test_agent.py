import json

import pytest

from apps.agent.core import AgentIterationLimitError, ReplenishAgent, SYSTEM_PROMPT
from apps.agent.providers import FakeLLMProvider, LLMResponse, ToolCall
from apps.agent.tools import (
    ExecutableTool,
    ToolDomainError,
    ToolExecutionContext,
    ToolExecutionPolicy,
    ToolPermission,
    ToolRegistry,
)


def make_tool(
    *,
    name="lookup",
    permission=ToolPermission.READ,
    handler=None,
):
    return ExecutableTool(
        name=name,
        description=f"Execute {name}.",
        parameters={
            "type": "object",
            "properties": {
                "value": {"type": "integer", "minimum": 1},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        permission=permission,
        handler=handler or (lambda arguments, context: {"value": arguments["value"]}),
    )


def run_tool_flow(call, registry, *, policy=None, context=None):
    provider = FakeLLMProvider(
        [
            LLMResponse(tool_calls=(call,)),
            LLMResponse(content="Final answer"),
        ]
    )
    agent = ReplenishAgent(
        provider=provider,
        tools=registry,
        policy=policy,
        context=context,
    )
    return agent.run("Question"), provider


def tool_result(provider, call_index=0):
    message = provider.calls[1].messages[3 + call_index]
    return json.loads(message.content)


def test_agent_returns_direct_text_response():
    provider = FakeLLMProvider([LLMResponse(content="Direct answer")])
    agent = ReplenishAgent(provider=provider, tools=ToolRegistry())

    assert agent.run("Hello") == "Direct answer"
    assert provider.calls[0].messages[0].content == SYSTEM_PROMPT
    assert provider.calls[0].messages[1].content == "Hello"


def test_agent_executes_tool_and_returns_final_text():
    executed = []
    tool = make_tool(
        handler=lambda arguments, context: (
            executed.append(arguments["value"]) or {"found": True}
        )
    )
    answer, provider = run_tool_flow(
        ToolCall(id="call-1", name="lookup", arguments={"value": 7}),
        ToolRegistry([tool]),
    )

    assert answer == "Final answer"
    assert executed == [7]
    assert tool_result(provider) == {"ok": True, "data": {"found": True}}


def test_agent_executes_multiple_calls_sequentially_in_requested_order():
    order = []
    registry = ToolRegistry(
        [
            make_tool(
                name="first",
                handler=lambda arguments, context: order.append("first") or 1,
            ),
            make_tool(
                name="second",
                handler=lambda arguments, context: order.append("second") or 2,
            ),
        ]
    )
    provider = FakeLLMProvider(
        [
            LLMResponse(
                content="Checking.",
                tool_calls=(
                    ToolCall(id="a", name="first", arguments={"value": 1}),
                    ToolCall(id="b", name="second", arguments={"value": 2}),
                ),
            ),
            LLMResponse(content="Done"),
        ]
    )

    assert ReplenishAgent(provider=provider, tools=registry).run("Run both") == "Done"
    assert order == ["first", "second"]
    second_messages = provider.calls[1].messages
    assert [message.tool_call_id for message in second_messages[-2:]] == ["a", "b"]


def test_unknown_tool_becomes_controlled_result():
    _, provider = run_tool_flow(
        ToolCall(id="missing-1", name="not_registered", arguments={}),
        ToolRegistry(),
    )

    result = tool_result(provider)
    assert result["ok"] is False
    assert result["error"]["code"] == "tool_not_found"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"value": "one"},
        {"value": 0},
        {"value": 1, "unexpected": True},
    ],
)
def test_invalid_arguments_do_not_execute_tool(arguments):
    handler = pytest.fail
    _, provider = run_tool_flow(
        ToolCall(id="invalid", name="lookup", arguments=arguments),
        ToolRegistry([make_tool(handler=handler)]),
    )

    result = tool_result(provider)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


def test_controlled_tool_error_is_returned_without_crashing_agent():
    def fail(arguments, context):
        raise ToolDomainError("Stock rule prevented the operation.")

    _, provider = run_tool_flow(
        ToolCall(id="domain-1", name="lookup", arguments={"value": 1}),
        ToolRegistry([make_tool(handler=fail)]),
    )

    result = tool_result(provider)
    assert result["error"] == {
        "code": "domain_error",
        "message": "Stock rule prevented the operation.",
    }


def test_unexpected_tool_error_is_sanitized():
    def fail(arguments, context):
        raise RuntimeError("database-password-must-not-leak")

    _, provider = run_tool_flow(
        ToolCall(id="unexpected-1", name="lookup", arguments={"value": 1}),
        ToolRegistry([make_tool(handler=fail)]),
    )

    result = tool_result(provider)
    assert result["error"]["code"] == "internal_error"
    assert "database-password" not in result["error"]["message"]


def test_write_is_blocked_by_default_policy():
    executed = []
    tool = make_tool(
        permission=ToolPermission.WRITE,
        handler=lambda arguments, context: executed.append(True),
    )
    _, provider = run_tool_flow(
        ToolCall(id="write-1", name="lookup", arguments={"value": 1}),
        ToolRegistry([tool]),
    )

    assert executed == []
    assert tool_result(provider)["error"]["code"] == "not_authorized"


def test_write_executes_when_backend_policy_allows_it():
    executed = []
    tool = make_tool(
        permission=ToolPermission.WRITE,
        handler=lambda arguments, context: executed.append(True) or {"saved": True},
    )
    _, provider = run_tool_flow(
        ToolCall(id="write-1", name="lookup", arguments={"value": 1}),
        ToolRegistry([tool]),
        policy=ToolExecutionPolicy(allow_write=True),
        context=ToolExecutionContext(
            user_id=1,
            is_authenticated=True,
            permissions=frozenset({"agent.execute_agent_write"}),
        ),
    )

    assert executed == [True]
    assert tool_result(provider)["data"] == {"saved": True}


def test_critical_is_always_blocked_even_when_write_is_allowed():
    executed = []
    tool = make_tool(
        permission=ToolPermission.CRITICAL,
        handler=lambda arguments, context: executed.append(True),
    )
    _, provider = run_tool_flow(
        ToolCall(id="critical-1", name="lookup", arguments={"value": 1}),
        ToolRegistry([tool]),
        policy=ToolExecutionPolicy(allow_write=True),
        context=ToolExecutionContext(
            user_id=1,
            is_authenticated=True,
            permissions=frozenset({"agent.execute_agent_write"}),
        ),
    )

    assert executed == []
    result = tool_result(provider)
    assert result["error"]["code"] == "not_authorized"
    assert "human approval" in result["error"]["message"]


def test_agent_stops_at_iteration_limit_without_executing_last_calls():
    executions = []
    registry = ToolRegistry(
        [
            make_tool(
                handler=lambda arguments, context: executions.append(arguments["value"])
            )
        ]
    )
    provider = FakeLLMProvider(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(id="first", name="lookup", arguments={"value": 1}),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(id="second", name="lookup", arguments={"value": 2}),
                )
            ),
        ]
    )
    agent = ReplenishAgent(
        provider=provider,
        tools=registry,
        max_iterations=2,
    )

    with pytest.raises(AgentIterationLimitError, match="maximum"):
        agent.run("Keep calling")

    assert executions == [1]
    assert len(provider.calls) == 2


def test_tool_ids_names_and_originating_assistant_message_are_preserved():
    call = ToolCall(id="provider-call-42", name="lookup", arguments={"value": 5})
    _, provider = run_tool_flow(call, ToolRegistry([make_tool()]))

    history = provider.calls[1].messages
    assistant = history[2]
    result = history[3]
    assert assistant.role.value == "assistant"
    assert assistant.tool_calls == (call,)
    assert result.role.value == "tool"
    assert result.tool_call_id == "provider-call-42"
    assert result.tool_name == "lookup"


def test_registry_rejects_duplicate_names_and_lists_definitions():
    registry = ToolRegistry([make_tool()])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(make_tool())

    definitions = registry.definitions()
    assert definitions[0].name == "lookup"
    assert definitions[0].parameters["additionalProperties"] is False


def test_agent_validates_public_inputs_and_iteration_limit():
    provider = FakeLLMProvider([LLMResponse(content="unused")])
    with pytest.raises(ValueError, match="positive"):
        ReplenishAgent(provider=provider, tools=ToolRegistry(), max_iterations=0)

    agent = ReplenishAgent(provider=provider, tools=ToolRegistry())
    with pytest.raises(ValueError, match="non-empty"):
        agent.run(" ")


def test_system_prompt_sets_tool_selection_boundaries():
    assert "sem Tools" in SYSTEM_PROMPT
    assert "READ" in SYSTEM_PROMPT
    assert "COMPUTE" in SYSTEM_PROMPT
    assert "WRITE somente" in SYSTEM_PROMPT
    assert "Analisar ou recomendar compra não autoriza criar proposta" in SYSTEM_PROMPT
    assert "aprovação humana" in SYSTEM_PROMPT
    assert "perguntas sobre suas capacidades" in SYSTEM_PROMPT
    assert "fonte de verdade" in SYSTEM_PROMPT
    assert "0 unidades" in SYSTEM_PROMPT
    assert "fornecedor preferido" in SYSTEM_PROMPT
    assert "somente um humano pode aprovar ou rejeitar" in SYSTEM_PROMPT


def test_write_stays_blocked_without_user_permission_even_when_policy_allows():
    executed = []
    tool = make_tool(
        permission=ToolPermission.WRITE,
        handler=lambda arguments, context: executed.append(True) or {"saved": True},
    )
    _, provider = run_tool_flow(
        ToolCall(id="write-unprivileged", name="lookup", arguments={"value": 1}),
        ToolRegistry([tool]),
        policy=ToolExecutionPolicy(allow_write=True),
        context=ToolExecutionContext(user_id=1, is_authenticated=True),
    )
    assert executed == []
    assert tool_result(provider)["error"]["code"] == "not_authorized"
