from __future__ import annotations

import pytest

from apps.agent.providers import ToolCall
from apps.agent.tools import (
    ExecutableTool,
    ToolExecutionContext,
    ToolExecutionPolicy,
    ToolPermission,
    ToolRegistry,
)


def schema_tool(handler):
    return ExecutableTool(
        name="schema_tool",
        description="Validate an adversarial schema.",
        parameters={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                },
                "mode": {
                    "type": "string",
                    "enum": ["safe", "strict"],
                    "default": "safe",
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                    },
                    "required": ["enabled"],
                    "additionalProperties": False,
                },
            },
            "required": ["count", "options"],
            "additionalProperties": False,
        },
        permission=ToolPermission.COMPUTE,
        handler=handler,
    )


def execute(tool, arguments):
    return ToolRegistry([tool]).execute(
        ToolCall(id="schema-call", name=tool.name, arguments=arguments),
        policy=ToolExecutionPolicy(),
        context=ToolExecutionContext(),
    )


def test_nested_schema_applies_defaults_and_validates_types():
    captured = []
    result = execute(
        schema_tool(lambda arguments, context: captured.append(arguments) or arguments),
        {"count": 2, "options": {"enabled": True}},
    )

    assert result["ok"] is True
    assert captured == [
        {"count": 2, "mode": "safe", "options": {"enabled": True}}
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        {"count": {"value": 1}, "options": {"enabled": True}},
        {"count": -1, "options": {"enabled": True}},
        {"count": 11, "options": {"enabled": True}},
        {"count": 1, "mode": "unsafe", "options": {"enabled": True}},
        {"count": 1, "options": {"enabled": "yes"}},
        {"count": 1, "options": {"enabled": True, "unexpected": 1}},
    ],
)
def test_adversarial_arguments_are_rejected_before_handler(arguments):
    result = execute(schema_tool(pytest.fail), arguments)

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("permission", [ToolPermission.READ, ToolPermission.COMPUTE])
def test_read_and_compute_are_available_to_anonymous_context(permission):
    policy = ToolExecutionPolicy(allow_write=False)

    assert policy.allows(permission, ToolExecutionContext()) is True


def test_internal_schema_error_is_sanitized():
    tool = ExecutableTool(
        name="unsupported",
        description="Unsupported executable schema.",
        parameters={
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        },
        permission=ToolPermission.READ,
        handler=pytest.fail,
    )

    result = execute(tool, {"items": []})

    assert result == {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": "The tool could not be executed.",
        },
    }
