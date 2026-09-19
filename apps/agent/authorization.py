from __future__ import annotations

from typing import Any

from .tools import ToolExecutionContext


AGENT_WRITE_PERMISSION = "agent.execute_agent_write"


def tool_context_for_user(
    user: Any,
    *,
    execution_id: str | None = None,
) -> ToolExecutionContext:
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    user_id = getattr(user, "pk", None) if is_authenticated else None
    permissions = (
        frozenset({AGENT_WRITE_PERMISSION})
        if is_authenticated and user.has_perm(AGENT_WRITE_PERMISSION)
        else frozenset()
    )
    return ToolExecutionContext(
        user_id=user_id,
        is_authenticated=is_authenticated,
        permissions=permissions,
        execution_id=execution_id,
    )
