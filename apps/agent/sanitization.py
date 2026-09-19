from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .tools.base import json_safe


SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credentials",
        "headers",
        "password",
        "secret",
        "token",
    }
)
MAX_DEPTH = 6
MAX_ITEMS = 100
MAX_STRING_LENGTH = 2000
REDACTED = "[REDACTED]"


def sanitize_audit_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return "[TRUNCATED]"
    normalized = json_safe(value)
    if isinstance(normalized, str):
        return normalized[:MAX_STRING_LENGTH]
    if isinstance(normalized, Mapping):
        sanitized = {}
        for index, (key, item) in enumerate(normalized.items()):
            if index >= MAX_ITEMS:
                sanitized["_truncated"] = True
                break
            normalized_key = str(key)
            if normalized_key.lower() in SENSITIVE_KEYS:
                sanitized[normalized_key] = REDACTED
            else:
                sanitized[normalized_key] = sanitize_audit_data(
                    item,
                    depth=depth + 1,
                )
        return sanitized
    if isinstance(normalized, list):
        return [
            sanitize_audit_data(item, depth=depth + 1)
            for item in normalized[:MAX_ITEMS]
        ]
    return normalized
