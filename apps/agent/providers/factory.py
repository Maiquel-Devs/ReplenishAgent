from __future__ import annotations

import os
from typing import Any

from .base import LLMProvider
from .mistral import MistralProvider
from .ollama import OllamaProvider


def create_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    **overrides: Any,
) -> LLMProvider:
    """Build the configured adapter while keeping provider and model separate."""
    provider_name = (
        provider or os.environ.get("LLM_PROVIDER", "ollama")
    ).strip().lower()

    if provider_name == "ollama":
        configured_model = model or os.environ.get("OLLAMA_MODEL", "")
        raw_timeout = overrides.pop(
            "timeout", os.environ.get("OLLAMA_TIMEOUT", "30")
        )
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("OLLAMA_TIMEOUT must be a number.") from exc
        return OllamaProvider(
            base_url=overrides.pop(
                "base_url", os.environ.get("OLLAMA_BASE_URL", "")
            ),
            model=configured_model,
            timeout=timeout,
            **overrides,
        )

    if provider_name == "mistral":
        configured_model = model or os.environ.get("MISTRAL_MODEL", "")
        return MistralProvider(
            api_key=overrides.pop(
                "api_key", os.environ.get("MISTRAL_API_KEY", "")
            ),
            model=configured_model,
            **overrides,
        )

    raise ValueError(f"Unknown LLM provider: {provider_name!r}.")
