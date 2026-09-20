from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.agent.providers import ToolCall

from .audit import (
    AgentAuditRecorder,
    AgentExecutionStatus,
    ToolExecutionStatus,
)
from .models import AgentExecution, AgentToolExecution
from .sanitization import sanitize_audit_data
from .tools import ToolExecutionContext


class DjangoAgentAuditRecorder(AgentAuditRecorder):
    def start(
        self,
        *,
        context: ToolExecutionContext,
        provider: str,
        model: str,
        user_request: str,
    ) -> UUID:
        execution_id = UUID(context.execution_id) if context.execution_id else None
        defaults = {
            "user_id": context.user_id if context.is_authenticated else None,
            "provider": provider[:100],
            "model": model[:255],
            "status": AgentExecutionStatus.RUNNING.value,
            "user_request": sanitize_audit_data(user_request),
        }
        if execution_id is None:
            execution = AgentExecution.objects.create(**defaults)
            return execution.pk

        execution, created = AgentExecution.objects.get_or_create(
            pk=execution_id,
            defaults=defaults,
        )
        expected_user_id = defaults["user_id"]
        if not created and execution.user_id != expected_user_id:
            raise ValueError("Execution identity does not match its owner.")
        if not created:
            execution.status = AgentExecutionStatus.RUNNING.value
            execution.finished_at = None
            execution.duration_ms = None
            execution.error_code = ""
            execution.save(
                update_fields=(
                    "status",
                    "finished_at",
                    "duration_ms",
                    "error_code",
                )
            )
        return execution.pk

    def execute_tool(
        self,
        execution: UUID,
        *,
        call: ToolCall,
        permission_level: str,
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        with transaction.atomic():
            locked_execution = AgentExecution.objects.select_for_update().get(
                pk=execution
            )
            event, _ = AgentToolExecution.objects.get_or_create(
                execution=locked_execution,
                tool_call_id=call.id,
                defaults={
                    "tool_name": call.name,
                    "permission_level": permission_level,
                    "arguments": sanitize_audit_data(call.arguments),
                },
            )
            sanitized_arguments = sanitize_audit_data(call.arguments)
            if not _matches_recorded_call(event, call.name, sanitized_arguments):
                return {
                    "ok": False,
                    "error": {
                        "code": "idempotency_conflict",
                        "message": "Tool call ID was already used with different data.",
                    },
                }

            if event.finished_at is not None and event.result is not None:
                return event.result

            result = operation()
            sanitized_result = sanitize_audit_data(result)
            event.tool_name = call.name
            event.permission_level = permission_level
            event.arguments = sanitized_arguments
            event.result = sanitized_result
            event.status = self._tool_status(result).value
            event.error_code = self._error_code(result)
            event.finished_at = timezone.now()
            event.save(
                update_fields=(
                    "tool_name",
                    "permission_level",
                    "arguments",
                    "result",
                    "status",
                    "error_code",
                    "finished_at",
                )
            )
            return sanitized_result

    def complete(self, execution: UUID, *, final_response: str) -> None:
        self._finish(
            execution,
            status=AgentExecutionStatus.COMPLETED,
            final_response=final_response,
        )

    def fail(
        self,
        execution: UUID,
        *,
        status: AgentExecutionStatus,
        error_code: str,
    ) -> None:
        self._finish(
            execution,
            status=status,
            error_code=error_code,
        )

    @staticmethod
    def _finish(
        execution_id: UUID,
        *,
        status: AgentExecutionStatus,
        final_response: str = "",
        error_code: str = "",
    ) -> None:
        with transaction.atomic():
            execution = AgentExecution.objects.select_for_update().get(
                pk=execution_id
            )
            finished_at = timezone.now()
            duration = finished_at - execution.started_at
            execution.status = status.value
            execution.finished_at = finished_at
            execution.duration_ms = max(0, int(duration.total_seconds() * 1000))
            execution.final_response = sanitize_audit_data(final_response)
            execution.error_code = error_code
            execution.save(
                update_fields=(
                    "status",
                    "finished_at",
                    "duration_ms",
                    "final_response",
                    "error_code",
                )
            )

    @staticmethod
    def _tool_status(result: dict[str, Any]) -> ToolExecutionStatus:
        if result.get("ok") is True:
            return ToolExecutionStatus.EXECUTED
        error_code = result.get("error", {}).get("code")
        if error_code == "not_authorized":
            return ToolExecutionStatus.BLOCKED
        return ToolExecutionStatus.FAILED

    @staticmethod
    def _error_code(result: dict[str, Any]) -> str:
        if result.get("ok") is True:
            return ""
        return str(result.get("error", {}).get("code", "internal_error"))[:100]


def _matches_recorded_call(
    event: AgentToolExecution,
    tool_name: str,
    arguments: Any,
) -> bool:
    return event.tool_name == tool_name and event.arguments == arguments
