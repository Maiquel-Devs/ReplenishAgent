from __future__ import annotations

import os
from typing import Any

from django.core.exceptions import ValidationError

from .base import LLMProvider
from .mistral import MistralProvider
from .ollama import OllamaProvider


def create_llm_provider(
    provider: str | None = None,
    model: str | None = None,
    **overrides: Any,
) -> LLMProvider:
    """Build the persisted selection or an explicit test/development override."""
    from apps.agent.configuration import AIConfigurationError, current_ai_configuration

    using_persisted = provider is None and model is None
    if using_persisted:
        configuration = current_ai_configuration()
        if configuration is None:
            raise AIConfigurationError("No AI configuration has been saved.")
        if not configuration.is_active:
            raise AIConfigurationError("The AI configuration is inactive.")
        try:
            configuration.full_clean()
        except ValidationError as exc:
            raise AIConfigurationError("The AI configuration is invalid.") from exc
        provider, model = configuration.integration, configuration.model
    elif not provider or not model:
        raise AIConfigurationError("Provider and model must be specified together.")

    provider_name = provider.strip().lower()
    if provider_name == "ollama":
        raw_timeout = overrides.pop("timeout", os.environ.get("OLLAMA_TIMEOUT", "30"))
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError("OLLAMA_TIMEOUT must be a number.") from exc
        if using_persisted:
            if "base_url" in overrides:
                raise AIConfigurationError(
                    "Endpoint override requires explicit provider and model."
                )
            base_url = configuration.local_endpoint
        else:
            base_url = overrides.pop("base_url", os.environ.get("OLLAMA_BASE_URL", ""))
        if not base_url.strip():
            raise AIConfigurationError("OLLAMA_BASE_URL is not configured.")
        return OllamaProvider(
            base_url=base_url, model=model, timeout=timeout, **overrides
        )

    if provider_name == "mistral":
        api_key = overrides.pop("api_key", os.environ.get("MISTRAL_API_KEY", ""))
        if not api_key.strip():
            raise AIConfigurationError("MISTRAL_API_KEY is not configured.")
        raw_timeout = overrides.pop("timeout", os.environ.get("MISTRAL_TIMEOUT", "30"))
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise AIConfigurationError("MISTRAL_TIMEOUT must be a number.") from exc
        return MistralProvider(
            api_key=api_key,
            model=model,
            timeout=timeout,
            **overrides,
        )

    raise AIConfigurationError(f"Unknown LLM provider: {provider_name!r}.")
