from dataclasses import FrozenInstanceError

import pytest

from apps.agent.providers import (
    FakeLLMProvider,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMRole,
    ToolCall,
    ToolDefinition,
)


def make_tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="check_inventory",
        description="Check current inventory for a product.",
        parameters={
            "type": "object",
            "properties": {
                "product_id": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["product_id"],
        },
    )


def make_tool_call(call_id: str = "call-1") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="check_inventory",
        arguments={"product_id": 42, "tags": ["urgent"]},
    )


def test_llm_provider_is_abstract():
    with pytest.raises(TypeError):
        LLMProvider()


@pytest.mark.parametrize("role", list(LLMRole))
def test_llm_message_accepts_supported_roles(role):
    message = LLMMessage(role=role.value, content="Content")

    assert message.role is role
    assert message.content == "Content"


def test_llm_message_rejects_invalid_role():
    with pytest.raises(ValueError, match="Invalid LLM message role"):
        LLMMessage(role="developer", content="Content")


def test_llm_message_is_immutable():
    message = LLMMessage(role=LLMRole.USER, content="Hello")

    with pytest.raises(FrozenInstanceError):
        message.content = "Changed"


def test_tool_definition_is_valid_and_deeply_immutable():
    tool = make_tool_definition()

    assert tool.name == "check_inventory"
    assert tool.parameters["required"] == ("product_id",)
    assert tool.parameters["properties"]["product_id"]["type"] == "integer"

    with pytest.raises(TypeError):
        tool.parameters["type"] = "array"
    with pytest.raises(TypeError):
        tool.parameters["properties"]["product_id"]["type"] = "string"


def test_tool_call_has_normalized_immutable_arguments():
    call = make_tool_call()

    assert call.arguments["product_id"] == 42
    assert call.arguments["tags"] == ("urgent",)

    with pytest.raises(TypeError):
        call.arguments["product_id"] = 99


def test_tool_call_rejects_non_mapping_arguments():
    with pytest.raises(TypeError, match="arguments must be a mapping"):
        ToolCall(id="call-1", name="tool", arguments='{"value": 1}')


def test_textual_llm_response():
    response = LLMResponse(content="Text response")

    assert response.content == "Text response"
    assert response.tool_calls == ()


def test_llm_response_with_one_tool_call():
    call = make_tool_call()
    response = LLMResponse(tool_calls=[call])

    assert response.content is None
    assert response.tool_calls == (call,)


def test_llm_response_with_multiple_tool_calls():
    first = make_tool_call("call-1")
    second = make_tool_call("call-2")
    response = LLMResponse(content="Checking.", tool_calls=(first, second))

    assert response.content == "Checking."
    assert response.tool_calls == (first, second)


def test_empty_llm_response_is_rejected():
    with pytest.raises(ValueError, match="must contain content"):
        LLMResponse()


def test_fake_returns_configured_responses_in_order():
    first = LLMResponse(content="First")
    second = LLMResponse(tool_calls=(make_tool_call(),))
    provider = FakeLLMProvider([first, second])
    messages = [LLMMessage(role="user", content="Analyze")]

    assert provider.generate(messages) is first
    assert provider.generate(messages) is second


def test_fake_records_messages_and_tools():
    provider = FakeLLMProvider([LLMResponse(content="Response")])
    messages = [LLMMessage(role="system", content="Be concise.")]
    tools = [make_tool_definition()]

    provider.generate(messages, tools)

    assert provider.calls[0].messages == tuple(messages)
    assert provider.calls[0].tools == tuple(tools)


def test_fake_records_multiple_calls_in_order():
    provider = FakeLLMProvider(
        [LLMResponse(content="A"), LLMResponse(content="B")]
    )
    first_messages = [LLMMessage(role="user", content="First")]
    second_messages = [LLMMessage(role="user", content="Second")]

    provider.generate(first_messages)
    provider.generate(second_messages)

    assert provider.calls[0].messages == tuple(first_messages)
    assert provider.calls[1].messages == tuple(second_messages)


def test_fake_fails_explicitly_when_responses_are_exhausted():
    provider = FakeLLMProvider([LLMResponse(content="Only")])
    messages = [LLMMessage(role="user", content="Question")]
    provider.generate(messages)

    with pytest.raises(LLMProviderError, match="No configured LLM responses remain"):
        provider.generate(messages)

    assert len(provider.calls) == 2


def test_fake_does_not_modify_preconfigured_responses():
    arguments = {"product_id": 7, "filters": ["active"]}
    response = LLMResponse(
        tool_calls=(
            ToolCall(id="call-1", name="check_inventory", arguments=arguments),
        )
    )
    responses = [response]
    provider = FakeLLMProvider(responses)

    responses.clear()
    arguments["product_id"] = 999
    returned = provider.generate([LLMMessage(role="user", content="Check")])

    assert returned is response
    assert provider.configured_responses == (response,)
    assert returned.tool_calls[0].arguments["product_id"] == 7


def test_fake_rejects_invalid_message_and_tool_collections():
    provider = FakeLLMProvider(
        [LLMResponse(content="A"), LLMResponse(content="B")]
    )

    with pytest.raises(TypeError, match="LLMMessage"):
        provider.generate([{"role": "user", "content": "Hello"}])
    with pytest.raises(TypeError, match="ToolDefinition"):
        provider.generate([LLMMessage(role="user", content="Hello")], [{"name": "x"}])
