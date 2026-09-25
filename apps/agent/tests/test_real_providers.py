import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from mistralai.client.errors import SDKError

from apps.agent.core import ReplenishAgent
from apps.agent.providers import (
    LLMMessage,
    LLMProviderError,
    LLMRole,
    MistralProvider,
    OllamaProvider,
    ToolCall,
    ToolDefinition,
    create_llm_provider,
)
from apps.agent.tools import ExecutableTool, ToolPermission, ToolRegistry


def tool_definition():
    return ToolDefinition(
        name="check_inventory",
        description="Check inventory.",
        parameters={
            "type": "object",
            "properties": {"product_id": {"type": "integer"}},
            "required": ["product_id"],
        },
    )


def ollama_provider(response_data, *, status=200, capture=None, model="qwen-test"):
    def handler(request):
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=response_data, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaProvider(
        base_url="http://ollama.internal:11434/",
        model=model,
        timeout=7.5,
        client=client,
    )


def mistral_response(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeMistralClient:
    def __init__(
        self,
        response=None,
        error=None,
        *,
        responses=None,
        models_response=None,
        models_error=None,
    ):
        self.response = response
        self.responses = list(responses) if responses is not None else None
        self.error = error
        self.models_response = models_response
        self.models_error = models_error
        self.requests = []
        self.model_requests = 0
        self.chat = SimpleNamespace(complete=self.complete)
        self.models = SimpleNamespace(list=self.list_models)

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        if self.responses is not None:
            return self.responses.pop(0)
        return self.response

    def list_models(self):
        self.model_requests += 1
        if self.models_error:
            raise self.models_error
        return self.models_response


def test_ollama_sends_messages_model_url_timeout_and_disables_streaming():
    captured = []
    provider = ollama_provider(
        {"message": {"role": "assistant", "content": "Ready."}},
        capture=captured,
        model="gemma-configured",
    )

    response = provider.generate(
        [
            LLMMessage(role="system", content="Be concise."),
            LLMMessage(role="user", content="Check item 7."),
        ]
    )

    request = captured[0]
    payload = json.loads(request.content)
    assert str(request.url) == "http://ollama.internal:11434/api/chat"
    assert request.extensions["timeout"]["read"] == 7.5
    assert payload == {
        "model": "gemma-configured",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Check item 7."},
        ],
        "stream": False,
    }
    assert response.content == "Ready."


def test_ollama_converts_tool_definition_without_executing_anything():
    captured = []
    provider = ollama_provider(
        {"message": {"role": "assistant", "content": "No call."}},
        capture=captured,
    )

    provider.generate([LLMMessage(role="user", content="Check.")], [tool_definition()])

    function = json.loads(captured[0].content)["tools"][0]["function"]
    assert function == {
        "name": "check_inventory",
        "description": "Check inventory.",
        "parameters": {
            "type": "object",
            "properties": {"product_id": {"type": "integer"}},
            "required": ["product_id"],
        },
    }


def test_ollama_preserves_one_structured_tool_call_identity():
    provider = ollama_provider(
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-stock-42",
                        "function": {
                            "index": 0,
                            "name": "check_inventory",
                            "arguments": {"product_id": 42},
                        }
                    }
                ],
            }
        }
    )

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert response.tool_calls == (
        ToolCall(
            id="call-stock-42",
            index=0,
            name="check_inventory",
            arguments={"product_id": 42},
        ),
    )


def test_ollama_preserves_multiple_calls_in_provider_order():
    provider = ollama_provider(
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-first",
                        "function": {
                            "index": 3,
                            "name": "first",
                            "arguments": {"value": 1},
                        },
                    },
                    {
                        "id": "call-second",
                        "function": {
                            "index": 8,
                            "name": "second",
                            "arguments": {"value": 2},
                        },
                    },
                ],
            }
        }
    )

    response = provider.generate([LLMMessage(role="user", content="Both.")])

    assert [call.name for call in response.tool_calls] == ["first", "second"]
    assert [call.id for call in response.tool_calls] == ["call-first", "call-second"]
    assert [call.index for call in response.tool_calls] == [3, 8]
    assert [call.arguments["value"] for call in response.tool_calls] == [1, 2]


def test_ollama_preserves_repeated_calls_to_the_same_tool():
    provider = ollama_provider(
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-stock-1",
                        "function": {
                            "index": 0,
                            "name": "check_inventory",
                            "arguments": {"product_id": 1},
                        },
                    },
                    {
                        "id": "call-stock-2",
                        "function": {
                            "index": 1,
                            "name": "check_inventory",
                            "arguments": {"product_id": 2},
                        },
                    },
                ],
            }
        }
    )

    response = provider.generate([LLMMessage(role="user", content="Check both.")])

    assert [call.name for call in response.tool_calls] == [
        "check_inventory",
        "check_inventory",
    ]
    assert [call.id for call in response.tool_calls] == [
        "call-stock-1",
        "call-stock-2",
    ]


def test_ollama_accepts_tool_arguments_as_json_object():
    provider = ollama_provider(
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-object",
                        "function": {
                            "name": "check_inventory",
                            "arguments": {"product_id": 42},
                        },
                    }
                ],
            }
        }
    )

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert response.tool_calls[0].arguments == {"product_id": 42}


def test_ollama_accepts_tool_arguments_as_valid_json_string():
    provider = ollama_provider(
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-string",
                        "function": {
                            "name": "check_inventory",
                            "arguments": '{"product_id": 42}',
                        },
                    }
                ],
            }
        }
    )

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert response.tool_calls[0].arguments == {"product_id": 42}


def test_ollama_keeps_tool_like_json_content_as_text():
    content = (
        '{"tool_calls":[{"function":{"name":"check_inventory",'
        '"arguments":{"product_id":42}}}]}'
    )
    provider = ollama_provider({"message": {"content": content}})

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert response.content == content
    assert response.tool_calls == ()


def test_ollama_converts_assistant_calls_and_tool_result_messages():
    captured = []
    provider = ollama_provider(
        {"message": {"role": "assistant", "content": "Done."}},
        capture=captured,
    )
    call = ToolCall(
        id="provider-call-1",
        index=4,
        name="check_inventory",
        arguments={"id": 3},
    )

    provider.generate(
        [
            LLMMessage(role="assistant", content="", tool_calls=(call,)),
            LLMMessage(
                role="tool",
                content='{"stock": 8}',
                tool_call_id=call.id,
                tool_name=call.name,
            ),
        ]
    )

    messages = json.loads(captured[0].content)["messages"]
    assert messages[0]["tool_calls"] == [
        {
            "id": "provider-call-1",
            "type": "function",
            "function": {
                "index": 4,
                "name": "check_inventory",
                "arguments": {"id": 3},
            },
        }
    ]
    assert messages[1] == {
        "role": "tool",
        "content": '{"stock": 8}',
        "tool_name": "check_inventory",
    }


@pytest.mark.parametrize(
    ("response_data", "match"),
    [
        ([], "unexpected payload"),
        ({}, "valid message"),
        ({"message": {"content": None}}, "empty response"),
        (
            {"message": {"content": "", "tool_calls": "invalid"}},
            "invalid tool calls",
        ),
        (
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "tool", "arguments": "[1, 2]"}}
                    ],
                }
            },
            "not a JSON object",
        ),
    ],
)
def test_ollama_rejects_invalid_payloads(response_data, match):
    provider = ollama_provider(response_data)

    with pytest.raises(LLMProviderError, match=match):
        provider.generate([LLMMessage(role="user", content="Hello")])


def test_ollama_maps_http_error_without_exposing_response_body():
    provider = ollama_provider({"secret": "do-not-expose"}, status=503)

    with pytest.raises(LLMProviderError, match="HTTP 503") as raised:
        provider.generate([LLMMessage(role="user", content="Hello")])

    assert "do-not-expose" not in str(raised.value)


def test_ollama_maps_connection_and_timeout_errors():
    def unavailable(request):
        raise httpx.ConnectError("refused", request=request)

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    for handler, message in ((unavailable, "unavailable"), (timeout, "timed out")):
        provider = OllamaProvider(
            base_url="http://ollama",
            model="model",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with pytest.raises(LLMProviderError, match=message):
            provider.generate([LLMMessage(role="user", content="Hello")])


def test_mistral_sends_messages_tools_and_configured_model():
    client = FakeMistralClient(mistral_response(content="Ready."))
    provider = MistralProvider(
        api_key="test-key", model="mistral-configured", client=client
    )

    response = provider.generate(
        [
            LLMMessage(role="system", content="Use tools when needed."),
            LLMMessage(role="user", content="Check."),
        ],
        [tool_definition()],
    )

    request = client.requests[0]
    assert request["model"] == "mistral-configured"
    assert request["messages"] == [
        {"role": "system", "content": "Use tools when needed."},
        {"role": "user", "content": "Check."},
    ]
    assert request["stream"] is False
    assert request["tools"][0]["function"]["name"] == "check_inventory"
    assert response.content == "Ready."


def test_mistral_normalizes_one_call_preserving_id_and_arguments():
    raw_call = SimpleNamespace(
        id="call-A",
        function=SimpleNamespace(name="first", arguments='{"product_id": 1}'),
    )
    client = FakeMistralClient(mistral_response(tool_calls=[raw_call]))
    provider = MistralProvider(api_key="test-key", model="model", client=client)

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert response.tool_calls == (
        ToolCall(id="call-A", name="first", arguments={"product_id": 1}),
    )


def test_mistral_normalizes_multiple_calls_preserving_ids_and_order():
    raw_calls = [
        SimpleNamespace(
            id="call-A",
            function=SimpleNamespace(name="first", arguments='{"product_id": 1}'),
        ),
        SimpleNamespace(
            id="call-B",
            function=SimpleNamespace(name="second", arguments={"product_id": 2}),
        ),
    ]
    client = FakeMistralClient(mistral_response(tool_calls=raw_calls))
    provider = MistralProvider(api_key="test-key", model="model", client=client)

    response = provider.generate([LLMMessage(role="user", content="Check.")])

    assert [call.id for call in response.tool_calls] == ["call-A", "call-B"]
    assert response.tool_calls[0].arguments["product_id"] == 1
    assert response.tool_calls[1].arguments["product_id"] == 2


def test_mistral_completes_agent_loop_after_tool_result():
    raw_call = SimpleNamespace(
        id="call-stock",
        function=SimpleNamespace(
            name="check_inventory",
            arguments='{"product_id": 7}',
        ),
    )
    client = FakeMistralClient(
        responses=[
            mistral_response(tool_calls=[raw_call]),
            mistral_response(content="There are 12 units."),
        ]
    )
    provider = MistralProvider(api_key="test-key", model="model", client=client)
    tool = ExecutableTool(
        name="check_inventory",
        description="Check inventory.",
        parameters={
            "type": "object",
            "properties": {"product_id": {"type": "integer"}},
            "required": ["product_id"],
            "additionalProperties": False,
        },
        permission=ToolPermission.READ,
        handler=lambda arguments, context: {"stock": 12},
    )

    answer = ReplenishAgent(
        provider=provider,
        tools=ToolRegistry([tool]),
    ).run("Check product 7.")

    assert answer == "There are 12 units."
    second_messages = client.requests[1]["messages"]
    assert second_messages[2]["tool_calls"][0]["id"] == "call-stock"
    assert second_messages[3] == {
        "role": "tool",
        "content": '{"ok":true,"data":{"stock":12}}',
        "tool_call_id": "call-stock",
        "name": "check_inventory",
    }


def test_mistral_converts_assistant_calls_and_tool_result_metadata():
    client = FakeMistralClient(mistral_response(content="Done."))
    provider = MistralProvider(api_key="test-key", model="model", client=client)
    call = ToolCall(id="call-9", name="check_inventory", arguments={"id": 9})

    provider.generate(
        [
            LLMMessage(role=LLMRole.ASSISTANT, content="", tool_calls=(call,)),
            LLMMessage(
                role=LLMRole.TOOL,
                content='{"stock": 2}',
                tool_call_id=call.id,
                tool_name=call.name,
            ),
        ]
    )

    messages = client.requests[0]["messages"]
    assert json.loads(messages[0]["tool_calls"][0]["function"]["arguments"]) == {
        "id": 9
    }
    assert messages[1] == {
        "role": "tool",
        "content": '{"stock": 2}',
        "tool_call_id": "call-9",
        "name": "check_inventory",
    }


def test_mistral_rejects_invalid_arguments_and_payloads():
    invalid_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="tool", arguments="{not-json}"),
    )
    provider = MistralProvider(
        api_key="test-key",
        model="model",
        client=FakeMistralClient(mistral_response(tool_calls=[invalid_call])),
    )
    with pytest.raises(LLMProviderError, match="invalid JSON"):
        provider.generate([LLMMessage(role="user", content="Hello")])

    provider = MistralProvider(
        api_key="test-key",
        model="model",
        client=FakeMistralClient(SimpleNamespace(choices=[])),
    )
    with pytest.raises(LLMProviderError, match="unexpected payload"):
        provider.generate([LLMMessage(role="user", content="Hello")])


def test_mistral_maps_sdk_errors_without_exposing_secrets():
    client = FakeMistralClient(error=RuntimeError("api-key-secret"))
    provider = MistralProvider(api_key="api-key-secret", model="model", client=client)

    with pytest.raises(LLMProviderError, match="request failed") as raised:
        provider.generate([LLMMessage(role="user", content="Hello")])

    assert "api-key-secret" not in str(raised.value)


def test_mistral_maps_authentication_timeout_and_http_errors():
    request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    cases = [
        (
            SDKError(
                "request failed",
                httpx.Response(401, request=request, json={"detail": "secret"}),
            ),
            "authentication failed",
        ),
        (httpx.ReadTimeout("slow", request=request), "timed out"),
        (
            SDKError(
                "request failed",
                httpx.Response(503, request=request, json={"detail": "secret"}),
            ),
            "HTTP 503",
        ),
    ]

    for error, message in cases:
        provider = MistralProvider(
            api_key="test-key",
            model="model",
            client=FakeMistralClient(error=error),
        )
        with pytest.raises(LLMProviderError, match=message) as raised:
            provider.generate([LLMMessage(role="user", content="Hello")])
        assert "secret" not in str(raised.value)


def test_mistral_lists_available_models_without_chat_completion():
    client = FakeMistralClient(
        models_response=SimpleNamespace(
            data=[
                SimpleNamespace(
                    id="ministral-3b-2512",
                    aliases=["ministral-3b-latest"],
                ),
                SimpleNamespace(id="mistral-small-2603", aliases=[]),
            ]
        )
    )

    models = MistralProvider.list_models(api_key="test-key", client=client)

    assert models == (
        "ministral-3b-2512",
        "ministral-3b-latest",
        "mistral-small-2603",
    )
    assert client.model_requests == 1
    assert client.requests == []


def test_mistral_requires_api_key_only_when_constructed():
    with pytest.raises(ValueError, match="API key is required"):
        MistralProvider(api_key="", model="model")


def test_mistral_rejects_invalid_timeout():
    with pytest.raises(ValueError, match="timeout"):
        MistralProvider(api_key="key", model="model", timeout=0)


def test_factory_builds_explicit_ollama_with_environment_endpoint(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://configured-ollama:11434")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "12")

    provider = create_llm_provider(
        provider="ollama", model="llama-configured", client=Mock()
    )

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama-configured"
    assert provider.base_url == "http://configured-ollama:11434"
    assert provider.timeout == 12


def test_factory_builds_mistral_and_keeps_model_separate(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_MODEL", "environment-model")

    provider = create_llm_provider(
        provider="mistral", model="explicit-model", client=Mock()
    )

    assert isinstance(provider, MistralProvider)
    assert provider.model == "explicit-model"
    assert provider.timeout == 30


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm_provider(provider="gemma", model="not-a-provider")


def test_llm_message_tool_metadata_is_provider_independent_and_validated():
    call = ToolCall(id="call-1", name="tool", arguments={})
    message = LLMMessage(role="assistant", content="", tool_calls=(call,))
    result = LLMMessage(
        role="tool", content="result", tool_call_id=call.id, tool_name=call.name
    )

    assert message.tool_calls == (call,)
    assert result.tool_call_id == "call-1"
    with pytest.raises(ValueError, match="Only assistant"):
        LLMMessage(role="user", content="", tool_calls=(call,))
    with pytest.raises(ValueError, match="only valid for tool"):
        LLMMessage(role="user", content="", tool_call_id="call-1")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "model": "model"},
        {"base_url": "http://ollama", "model": ""},
        {"base_url": "http://ollama", "model": "model", "timeout": 0},
    ],
)
def test_ollama_rejects_missing_configuration(kwargs):
    with pytest.raises(ValueError):
        OllamaProvider(**kwargs)


def test_ollama_rejects_invalid_json_and_missing_tool_name():
    def invalid_json(request):
        return httpx.Response(200, content=b"{invalid", request=request)

    provider = OllamaProvider(
        base_url="http://ollama",
        model="model",
        client=httpx.Client(transport=httpx.MockTransport(invalid_json)),
    )
    with pytest.raises(LLMProviderError, match="invalid JSON"):
        provider.generate([LLMMessage(role="user", content="Hello")])

    provider = ollama_provider(
        {
            "message": {
                "content": "",
                "tool_calls": [{"function": {"arguments": {}}}],
            }
        }
    )
    with pytest.raises(LLMProviderError, match="without a name"):
        provider.generate([LLMMessage(role="user", content="Hello")])


def test_mistral_rejects_invalid_model_content_and_tool_identity():
    with pytest.raises(ValueError, match="model"):
        MistralProvider(api_key="key", model="")

    provider = MistralProvider(
        api_key="key",
        model="model",
        client=FakeMistralClient(mistral_response(content=123)),
    )
    with pytest.raises(LLMProviderError, match="content"):
        provider.generate([LLMMessage(role="user", content="Hello")])

    missing_id = SimpleNamespace(
        id="",
        function=SimpleNamespace(name="tool", arguments={}),
    )
    provider = MistralProvider(
        api_key="key",
        model="model",
        client=FakeMistralClient(mistral_response(tool_calls=[missing_id])),
    )
    with pytest.raises(LLMProviderError, match="without an ID"):
        provider.generate([LLMMessage(role="user", content="Hello")])


def test_factory_rejects_invalid_ollama_timeout(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT", "not-a-number")

    with pytest.raises(ValueError, match="must be a number"):
        create_llm_provider(
            provider="ollama",
            base_url="http://ollama",
            model="model",
            client=Mock(),
        )
