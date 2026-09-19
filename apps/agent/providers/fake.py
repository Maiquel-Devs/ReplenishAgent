from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .base import (
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    ToolDefinition,
)


@dataclass(frozen=True, slots=True)
class FakeLLMCall:
    messages: tuple[LLMMessage, ...]
    tools: tuple[ToolDefinition, ...]


class FakeLLMProvider(LLMProvider):
    """Deterministic provider backed by a finite sequence of responses."""

    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        configured_responses = tuple(responses)
        if any(not isinstance(response, LLMResponse) for response in configured_responses):
            raise TypeError("Fake responses must contain only LLMResponse objects.")
        self._responses = configured_responses
        self._next_response = 0
        self._calls: list[FakeLLMCall] = []

    @property
    def calls(self) -> tuple[FakeLLMCall, ...]:
        return tuple(self._calls)

    @property
    def configured_responses(self) -> tuple[LLMResponse, ...]:
        return self._responses

    def generate(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolDefinition] = (),
    ) -> LLMResponse:
        normalized_messages = tuple(messages)
        normalized_tools = tuple(tools)
        if any(not isinstance(message, LLMMessage) for message in normalized_messages):
            raise TypeError("messages must contain only LLMMessage objects.")
        if any(not isinstance(tool, ToolDefinition) for tool in normalized_tools):
            raise TypeError("tools must contain only ToolDefinition objects.")
        self._calls.append(
            FakeLLMCall(messages=normalized_messages, tools=normalized_tools)
        )
        if self._next_response >= len(self._responses):
            raise LLMProviderError("No configured LLM responses remain.")
        response = self._responses[self._next_response]
        self._next_response += 1
        return response
