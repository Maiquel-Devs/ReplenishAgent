from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from apps.agent.providers import ToolCall, ToolDefinition

from .base import (
    ExecutableTool,
    ToolArgumentsError,
    ToolAuthorizationError,
    ToolError,
    ToolExecutionContext,
    ToolExecutionPolicy,
    ToolNotFoundError,
    ToolPermission,
    json_safe,
)


class ToolRegistry:
    def __init__(self, tools: Iterable[ExecutableTool] = ()) -> None:
        self._tools: dict[str, ExecutableTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ExecutableTool) -> None:
        if not isinstance(tool, ExecutableTool):
            raise TypeError("Only ExecutableTool instances can be registered.")
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition() for tool in self._tools.values())

    def get(self, name: str) -> ExecutableTool:
        try:
            return self._tools[name]
        except (KeyError, TypeError) as exc:
            raise ToolNotFoundError(f"Tool {name!r} is not registered.") from exc

    def permission_for(self, name: str) -> ToolPermission | None:
        try:
            return self.get(name).permission
        except ToolNotFoundError:
            return None

    def execute(
        self,
        call: ToolCall,
        *,
        policy: ToolExecutionPolicy,
        context: ToolExecutionContext,
    ) -> dict[str, Any]:
        try:
            if not isinstance(call, ToolCall):
                raise ToolArgumentsError("A valid ToolCall is required.")
            tool = self.get(call.name)
            arguments = tool.validate_arguments(call.arguments)
            self._authorize(tool, policy, context)
            data = tool.handler(arguments, context)
            return {"ok": True, "data": json_safe(data)}
        except ToolError as exc:
            return {
                "ok": False,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception:
            return {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "The tool could not be executed.",
                },
            }

    @staticmethod
    def _authorize(
        tool: ExecutableTool,
        policy: ToolExecutionPolicy,
        context: ToolExecutionContext,
    ) -> None:
        if tool.permission is ToolPermission.CRITICAL:
            raise ToolAuthorizationError(
                "Critical actions require explicit human approval."
            )
        if not policy.allows(tool.permission, context):
            raise ToolAuthorizationError(
                f"Execution of {tool.permission.value} tools is not allowed."
            )
