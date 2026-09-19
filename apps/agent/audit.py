from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import Any

from apps.agent.providers import ToolCall


class AgentExecutionStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    LIMIT_REACHED = "LIMIT_REACHED"


class ToolExecutionStatus(str, Enum):
    RUNNING = "RUNNING"
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class AgentAuditRecorder(ABC):
    @abstractmethod
    def start(
        self,
        *,
        context: Any,
        provider: str,
        model: str,
        user_request: str,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def execute_tool(
        self,
        execution: Any,
        *,
        call: ToolCall,
        permission_level: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def complete(self, execution: Any, *, final_response: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def fail(
        self,
        execution: Any,
        *,
        status: AgentExecutionStatus,
        error_code: str,
    ) -> None:
        raise NotImplementedError


class NoOpAgentAuditRecorder(AgentAuditRecorder):
    def start(self, **kwargs: Any) -> None:
        return None

    def execute_tool(
        self,
        execution: Any,
        *,
        call: ToolCall,
        permission_level: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        return operation()

    def complete(self, execution: Any, *, final_response: str) -> None:
        return None

    def fail(
        self,
        execution: Any,
        *,
        status: AgentExecutionStatus,
        error_code: str,
    ) -> None:
        return None
