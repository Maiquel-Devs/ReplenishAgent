from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .base import LLMProviderError, ToolDefinition


def mutable_json(value: Any) -> Any:
    """Convert immutable internal JSON values to SDK/HTTP-friendly containers."""
    if isinstance(value, Mapping):
        return {key: mutable_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [mutable_json(item) for item in value]
    return value


def tool_definition_payload(tool: ToolDefinition) -> dict[str, Any]:
    if not isinstance(tool, ToolDefinition):
        raise TypeError("tools must contain only ToolDefinition objects.")
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": mutable_json(tool.parameters),
        },
    }


def field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def parse_arguments(value: Any, *, provider: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise LLMProviderError(
                f"{provider} returned invalid JSON tool arguments."
            ) from exc
    if not isinstance(value, Mapping):
        raise LLMProviderError(
            f"{provider} returned tool arguments that are not a JSON object."
        )
    return dict(value)
