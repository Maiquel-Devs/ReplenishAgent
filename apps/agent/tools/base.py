from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

from apps.agent.providers import ToolDefinition


class ToolPermission(str, Enum):
    READ = "READ"
    COMPUTE = "COMPUTE"
    WRITE = "WRITE"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Provider- and framework-independent identity used by authorization."""

    user_id: int | None = None
    is_authenticated: bool = False
    permissions: frozenset[str] = frozenset()
    execution_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.user_id is not None and (
            isinstance(self.user_id, bool) or not isinstance(self.user_id, int)
        ):
            raise TypeError("user_id must be an integer or None.")
        if self.is_authenticated and self.user_id is None:
            raise ValueError("Authenticated contexts require a user_id.")
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    def has_permission(self, permission: str) -> bool:
        return self.is_authenticated and permission in self.permissions


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    allow_write: bool = False
    write_permission: str = "agent.execute_agent_write"

    def allows(
        self,
        permission: ToolPermission,
        context: ToolExecutionContext,
    ) -> bool:
        if permission in (ToolPermission.READ, ToolPermission.COMPUTE):
            return True
        if permission is ToolPermission.WRITE:
            return (
                self.allow_write
                and context.has_permission(self.write_permission)
            )
        return False


class ToolError(Exception):
    code = "tool_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ToolNotFoundError(ToolError):
    code = "tool_not_found"


class ToolArgumentsError(ToolError):
    code = "invalid_arguments"


class ToolResourceNotFoundError(ToolError):
    code = "resource_not_found"


class ToolAuthorizationError(ToolError):
    code = "not_authorized"


class ToolDomainError(ToolError):
    code = "domain_error"


ToolHandler = Callable[[Mapping[str, Any], ToolExecutionContext], Any]


@dataclass(frozen=True, slots=True)
class ExecutableTool:
    name: str
    description: str
    parameters: Mapping[str, Any]
    permission: ToolPermission
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string.")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("Tool description must be a non-empty string.")
        if not isinstance(self.permission, ToolPermission):
            raise TypeError("Tool permission must be a ToolPermission.")
        if not callable(self.handler):
            raise TypeError("Tool handler must be callable.")
        definition = ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
        object.__setattr__(self, "parameters", definition.parameters)

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return validate_object(arguments, self.parameters)


def validate_object(
    arguments: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(arguments, Mapping):
        raise ToolArgumentsError("Tool arguments must be an object.")
    if schema.get("type") != "object":
        raise ValueError("Executable Tool schemas must use object at the root.")

    properties = schema.get("properties", {})
    required = set(schema.get("required", ()))
    if not isinstance(properties, Mapping):
        raise ValueError("Tool schema properties must be an object.")

    unexpected = set(arguments) - set(properties)
    if unexpected and schema.get("additionalProperties", True) is False:
        names = ", ".join(sorted(str(name) for name in unexpected))
        raise ToolArgumentsError(f"Unexpected arguments: {names}.")

    missing = required - set(arguments)
    if missing:
        names = ", ".join(sorted(str(name) for name in missing))
        raise ToolArgumentsError(f"Missing required arguments: {names}.")

    validated = {}
    for name, property_schema in properties.items():
        if name in arguments:
            validated[name] = _validate_value(name, arguments[name], property_schema)
        elif isinstance(property_schema, Mapping) and "default" in property_schema:
            validated[name] = property_schema["default"]
    return validated


def _validate_value(name: str, value: Any, schema: Mapping[str, Any]) -> Any:
    expected = schema.get("type")
    valid = True
    if expected == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid = (
            isinstance(value, (int, float, Decimal))
            and not isinstance(value, bool)
        )
    elif expected == "string":
        valid = isinstance(value, str)
    elif expected == "boolean":
        valid = isinstance(value, bool)
    elif expected == "object":
        return validate_object(value, schema)
    elif expected is not None:
        raise ValueError(f"Unsupported schema type: {expected}.")
    if not valid:
        raise ToolArgumentsError(f"Argument {name!r} must be {expected}.")

    if "minimum" in schema and value < schema["minimum"]:
        raise ToolArgumentsError(
            f"Argument {name!r} must be at least {schema['minimum']}."
        )
    if "maximum" in schema and value > schema["maximum"]:
        raise ToolArgumentsError(
            f"Argument {name!r} must be at most {schema['maximum']}."
        )
    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentsError(f"Argument {name!r} has an invalid value.")
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    raise TypeError(f"Tool returned unsupported type: {type(value).__name__}.")
