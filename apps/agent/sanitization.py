from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .tools.base import json_safe


SENSITIVE_KEY_MARKERS = frozenset(
    (
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "headers",
        "password",
        "passwd",
        "secret",
        "sessionid",
        "token",
    )
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"""(?ix)
    \b(api[_-]?key|authorization|cookie|credentials?|password|passwd|
       secret|sessionid|token)\b
    (["']?)
    (\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|(?:Bearer\s+)?[^\s,;&]+)
    |
    \bBearer\s+[^\s,;&]+
    """
)
MAX_DEPTH = 6
MAX_ITEMS = 100
MAX_STRING_LENGTH = 2000
REDACTED = "[REDACTED]"


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(marker in normalized for marker in SENSITIVE_KEY_MARKERS)


def _redact_sensitive_text(value: str) -> str:
    def replace(match: re.Match) -> str:
        if match.group(1) is None:
            return f"Bearer {REDACTED}"
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}"

    return SENSITIVE_VALUE_PATTERN.sub(replace, value)


def sanitize_audit_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_DEPTH:
        return "[TRUNCATED]"
    normalized = json_safe(value)
    if isinstance(normalized, str):
        return _redact_sensitive_text(normalized)[:MAX_STRING_LENGTH]
    if isinstance(normalized, Mapping):
        sanitized = {}
        for index, (key, item) in enumerate(normalized.items()):
            if index >= MAX_ITEMS:
                sanitized["_truncated"] = True
                break
            normalized_key = str(key)
            if _is_sensitive_key(normalized_key):
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
