from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx

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


class OllamaProvider(LLMProvider):
    """Ollama adapter for its non-streaming POST /api/chat API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Ollama base_url must be a non-empty string.")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Ollama model must be a non-empty string.")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("Ollama timeout must be a positive number.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = float(timeout)
        self._client = client or httpx.Client(trust_env=False, follow_redirects=False)

    @staticmethod
    def list_models(
        *, base_url: str, timeout: float = 3.0, client: httpx.Client | None = None
    ) -> tuple[str, ...]:
        """Read installed model names without running inference or following redirects."""
        owned_client = client is None
        http_client = client or httpx.Client(trust_env=False, follow_redirects=False)
        try:
            with http_client.stream(
                "GET",
                f"{base_url.rstrip('/')}/api/tags",
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise LLMProviderError("Ollama model discovery failed.")
                chunks = []
                size = 0
                deadline = monotonic() + 4.0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1_000_000 or monotonic() > deadline:
                        raise LLMProviderError(
                            "Ollama model list exceeded the response limit."
                        )
                    chunks.append(chunk)
            data = json.loads(b"".join(chunks))
        except httpx.TimeoutException as exc:
            raise LLMProviderError("Ollama model discovery timed out.") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("Ollama is unavailable.") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise LLMProviderError("Ollama returned an invalid model list.") from exc
        finally:
            if owned_client:
                http_client.close()

        if not isinstance(data, Mapping) or not isinstance(data.get("models"), list):
            raise LLMProviderError("Ollama returned an invalid model list.")
        names = []
        for item in data["models"]:
            name = item.get("name") if isinstance(item, Mapping) else None
            if not isinstance(name, str) or not name.strip() or len(name) > 255:
                raise LLMProviderError("Ollama returned an invalid model list.")
            names.append(name)
        return tuple(dict.fromkeys(names))

    def generate(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [tool_definition_payload(tool) for tool in tools]

        try:
            response = self._client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderError("Ollama request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"Ollama returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError("Ollama is unavailable.") from exc
        except ValueError as exc:
            raise LLMProviderError("Ollama returned invalid JSON.") from exc

        return self._normalize_response(data)

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
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": mutable_json(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role is LLMRole.TOOL and message.tool_name:
            payload["tool_name"] = message.tool_name
        return payload

    @staticmethod
    def _normalize_response(data: Any) -> LLMResponse:
        if not isinstance(data, Mapping):
            raise LLMProviderError("Ollama returned an unexpected payload.")
        message = field(data, "message")
        if not isinstance(message, Mapping):
            raise LLMProviderError("Ollama response is missing a valid message.")
        content = field(message, "content")
        if content is not None and not isinstance(content, str):
            raise LLMProviderError("Ollama returned invalid message content.")

        raw_calls = field(message, "tool_calls", ()) or ()
        if not isinstance(raw_calls, (list, tuple)):
            raise LLMProviderError("Ollama returned invalid tool calls.")
        calls = []
        for raw_call in raw_calls:
            function = field(raw_call, "function")
            name = field(function, "name")
            if not isinstance(name, str) or not name.strip():
                raise LLMProviderError("Ollama returned a tool call without a name.")
            arguments = parse_arguments(field(function, "arguments"), provider="Ollama")
            calls.append(
                ToolCall(
                    id=f"ollama-{uuid4().hex}",
                    name=name,
                    arguments=arguments,
                )
            )
        if content is None and not calls:
            raise LLMProviderError("Ollama returned an empty response.")
        return LLMResponse(content=content, tool_calls=tuple(calls))
