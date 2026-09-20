from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.agent.audit_django import DjangoAgentAuditRecorder
from apps.agent.models import AgentToolExecution
from apps.agent.providers import ToolCall
from apps.agent.tools import ToolExecutionContext, ToolPermission


pytestmark = pytest.mark.django_db


def start_execution(recorder, execution_id=None):
    context = ToolExecutionContext(execution_id=str(execution_id or uuid4()))
    return recorder.start(
        context=context,
        provider="FakeLLMProvider",
        model="fake-model",
        user_request="Idempotency test",
    )


def execute(recorder, execution_id, call, operation):
    return recorder.execute_tool(
        execution_id,
        call=call,
        permission_level=ToolPermission.WRITE.value,
        operation=operation,
    )


def test_same_call_id_is_scoped_to_each_agent_execution():
    recorder = DjangoAgentAuditRecorder()
    first_execution = start_execution(recorder)
    second_execution = start_execution(recorder)
    call = ToolCall(id="same-id", name="write", arguments={"value": 1})
    invocations = []

    first = execute(
        recorder,
        first_execution,
        call,
        lambda: invocations.append("first") or {"ok": True, "data": {"id": 1}},
    )
    second = execute(
        recorder,
        second_execution,
        call,
        lambda: invocations.append("second") or {"ok": True, "data": {"id": 2}},
    )

    assert first["data"]["id"] == 1
    assert second["data"]["id"] == 2
    assert invocations == ["first", "second"]
    assert AgentToolExecution.objects.count() == 2


def test_reusing_call_id_with_different_arguments_returns_conflict():
    recorder = DjangoAgentAuditRecorder()
    execution_id = start_execution(recorder)
    original_call = ToolCall(id="stable-id", name="write", arguments={"value": 1})
    conflicting_call = ToolCall(id="stable-id", name="write", arguments={"value": 2})

    execute(
        recorder,
        execution_id,
        original_call,
        lambda: {"ok": True, "data": {"created": 1}},
    )
    result = execute(
        recorder,
        execution_id,
        conflicting_call,
        lambda: pytest.fail("Conflicting retry must not execute the operation"),
    )

    event = AgentToolExecution.objects.get()
    assert result["ok"] is False
    assert result["error"]["code"] == "idempotency_conflict"
    assert event.arguments == {"value": 1}
    assert event.result["data"]["created"] == 1


def test_failure_before_result_persistence_can_be_retried():
    recorder = DjangoAgentAuditRecorder()
    execution_id = start_execution(recorder)
    call = ToolCall(id="retry-after-failure", name="write", arguments={"value": 1})

    with pytest.raises(RuntimeError, match="temporary"):
        execute(
            recorder,
            execution_id,
            call,
            lambda: (_ for _ in ()).throw(RuntimeError("temporary")),
        )

    assert AgentToolExecution.objects.count() == 0

    result = execute(
        recorder,
        execution_id,
        call,
        lambda: {"ok": True, "data": {"saved": True}},
    )

    assert result["data"]["saved"] is True
    assert AgentToolExecution.objects.get().result == result


def test_database_constraint_enforces_execution_and_call_id_uniqueness():
    recorder = DjangoAgentAuditRecorder()
    execution_id = start_execution(recorder)
    call = ToolCall(id="database-unique", name="write", arguments={})
    execute(
        recorder,
        execution_id,
        call,
        lambda: {"ok": True, "data": {}},
    )
    original = AgentToolExecution.objects.get()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AgentToolExecution.objects.create(
                execution_id=execution_id,
                tool_name="write",
                tool_call_id=original.tool_call_id,
                permission_level=ToolPermission.WRITE.value,
                arguments={},
            )
