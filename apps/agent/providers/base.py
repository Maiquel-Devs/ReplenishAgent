from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any


class LLMProviderError(Exception):
    """Base exception for failures exposed by an LLM provider."""


class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


def _freeze_json(value: Any) -> Any:
    """Return an immutable representation of a JSON-compatible value."""
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings.")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("JSON numbers must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}.")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Tool description must be a non-empty string.")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("Tool parameters must be a mapping.")
        object.__setattr__(self, "parameters", _freeze_json(self.parameters))


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Tool call id must be a non-empty string.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool call name must be a non-empty string.")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("Tool call arguments must be a mapping.")
        object.__setattr__(self, "arguments", _freeze_json(self.arguments))


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: LLMRole | str
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None

    def __post_init__(self) -> None:
        try:
            role = LLMRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid LLM message role: {self.role!r}.") from exc
        if not isinstance(self.content, str):
            raise TypeError("Message content must be a string.")
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, ToolCall) for call in calls):
            raise TypeError("Message tool_calls must contain only ToolCall objects.")
        if calls and role is not LLMRole.ASSISTANT:
            raise ValueError("Only assistant messages may contain tool calls.")
        for field_name, value in (
            ("tool_call_id", self.tool_call_id),
            ("tool_name", self.tool_name),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field_name} must be a non-empty string or None.")
            if value is not None and role is not LLMRole.TOOL:
                raise ValueError(f"{field_name} is only valid for tool messages.")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "tool_calls", calls)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.content is not None and not isinstance(self.content, str):
            raise TypeError("Response content must be a string or None.")
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, ToolCall) for call in calls):
            raise TypeError("Response tool_calls must contain only ToolCall objects.")
        if self.content is None and not calls:
            raise ValueError("An LLM response must contain content or at least one tool call.")
        object.__setattr__(self, "tool_calls", calls)


class LLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> LLMResponse:
        """Generate one normalized response from messages and optional tools."""
        raise NotImplementedError
