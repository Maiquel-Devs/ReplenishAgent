from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mistralai.client import Mistral

from ._conversion import field, mutable_json, parse_arguments, tool_definition_payload
from .base import (
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    LLMRole,
    ToolCall,
    ToolDefinition,
)


class MistralProvider(LLMProvider):
    """Adapter for the official Mistral Python SDK chat completion API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Mistral API key is required.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Mistral model must be a non-empty string.")
        self.model = model
        self._client = client or Mistral(api_key=api_key)

    def generate(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
        }
        if tools:
            request["tools"] = [tool_definition_payload(tool) for tool in tools]
        try:
            response = self._client.chat.complete(**request)
        except Exception as exc:
            raise LLMProviderError("Mistral request failed.") from exc
        return self._normalize_response(response)

    @staticmethod
    def _message_payload(message: LLMMessage) -> dict[str, Any]:
        if not isinstance(message, LLMMessage):
            raise TypeError("messages must contain only LLMMessage objects.")
        payload: dict[str, Any] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            mutable_json(call.arguments), ensure_ascii=False
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role is LLMRole.TOOL:
            if message.tool_call_id:
                payload["tool_call_id"] = message.tool_call_id
            if message.tool_name:
                payload["name"] = message.tool_name
        return payload

    @staticmethod
    def _normalize_response(response: Any) -> LLMResponse:
        choices = field(response, "choices")
        if not isinstance(choices, (list, tuple)) or not choices:
            raise LLMProviderError("Mistral returned an unexpected payload.")
        message = field(choices[0], "message")
        if message is None:
            raise LLMProviderError("Mistral response is missing a message.")
        content = field(message, "content")
        if content is not None and not isinstance(content, str):
            raise LLMProviderError("Mistral returned invalid message content.")

        raw_calls = field(message, "tool_calls", ()) or ()
        if not isinstance(raw_calls, (list, tuple)):
            raise LLMProviderError("Mistral returned invalid tool calls.")
        calls = []
        for raw_call in raw_calls:
            call_id = field(raw_call, "id")
            function = field(raw_call, "function")
            name = field(function, "name")
            if not isinstance(call_id, str) or not call_id.strip():
                raise LLMProviderError("Mistral returned a tool call without an ID.")
            if not isinstance(name, str) or not name.strip():
                raise LLMProviderError("Mistral returned a tool call without a name.")
            arguments = parse_arguments(
                field(function, "arguments"), provider="Mistral"
            )
            calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
        if content is None and not calls:
            raise LLMProviderError("Mistral returned an empty response.")
        return LLMResponse(content=content, tool_calls=tuple(calls))
