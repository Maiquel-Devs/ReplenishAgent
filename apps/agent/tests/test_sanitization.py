from __future__ import annotations

import pytest

from apps.agent.sanitization import (
    MAX_DEPTH,
    MAX_ITEMS,
    MAX_STRING_LENGTH,
    REDACTED,
    sanitize_audit_data,
)


def test_sensitive_keys_are_redacted_recursively_in_objects_and_lists():
    payload = {
        "api_key": "key-secret",
        "TOKEN": "token-secret",
        "access_token": "access-secret",
        "session-id": "session-secret",
        "nested": {
            "authorization": "Bearer secret",
            "password": "password-secret",
            "cookie": "cookie-secret",
            "credentials": {"value": "credential-secret"},
            "headers": {"X-Api-Key": "header-secret"},
        },
        "items": [{"secret": "list-secret", "visible": "ok"}],
    }

    sanitized = sanitize_audit_data(payload)

    assert sanitized["api_key"] == REDACTED
    assert sanitized["TOKEN"] == REDACTED
    assert sanitized["nested"] == {
        "authorization": REDACTED,
        "password": REDACTED,
        "cookie": REDACTED,
        "credentials": REDACTED,
        "headers": REDACTED,
    }
    assert sanitized["items"] == [{"secret": REDACTED, "visible": "ok"}]
    assert "key-secret" not in repr(sanitized)
    assert "access-secret" not in repr(sanitized)
    assert "session-secret" not in repr(sanitized)
    assert "list-secret" not in repr(sanitized)


def test_large_strings_collections_and_depth_are_bounded():
    payload = {
        "large": "x" * (MAX_STRING_LENGTH + 50),
        "items": list(range(MAX_ITEMS + 10)),
        "mapping": {str(index): index for index in range(MAX_ITEMS + 10)},
    }
    nested = payload
    for _ in range(MAX_DEPTH + 2):
        nested = {"child": nested}

    sanitized = sanitize_audit_data(nested)

    current = sanitized
    for _ in range(MAX_DEPTH):
        current = current["child"]
    assert current == "[TRUNCATED]"

    bounded = sanitize_audit_data(payload)
    assert len(bounded["large"]) == MAX_STRING_LENGTH
    assert len(bounded["items"]) == MAX_ITEMS
    assert len(bounded["mapping"]) == MAX_ITEMS + 1
    assert bounded["mapping"]["_truncated"] is True


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer authorization-secret",
        "token=token-secret",
        'api_key: "api-secret"',
        "Cookie: sessionid=cookie-secret",
        "Bearer standalone-secret",
    ],
)
def test_sensitive_values_embedded_in_text_are_redacted(value):
    sanitized = sanitize_audit_data(value)

    assert "secret" not in sanitized
    assert REDACTED in sanitized
