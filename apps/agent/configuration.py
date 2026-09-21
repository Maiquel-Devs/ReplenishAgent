"""Persistent AI selection and administrative change recording."""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError
from django.db import transaction

from .local_endpoint import normalize_local_endpoint
from .models import AIConfiguration, AIConfigurationChange
from .providers.ollama import OllamaProvider


class AIConfigurationError(ValueError):
    """The selected integration cannot be constructed from current configuration."""


def current_ai_configuration() -> AIConfiguration | None:
    return AIConfiguration.objects.filter(pk=1).first()


def save_ai_configuration(configuration: AIConfiguration, *, user) -> AIConfiguration:
    configuration.full_clean()
    with transaction.atomic():
        saved, _ = AIConfiguration.objects.update_or_create(
            pk=1,
            defaults={
                "type": configuration.type,
                "integration": configuration.integration,
                "model": configuration.model,
                "local_endpoint": configuration.local_endpoint,
                "is_active": configuration.is_active,
            },
        )
        AIConfigurationChange.objects.create(
            user=user,
            type=saved.type,
            integration=saved.integration,
            is_active=saved.is_active,
        )
    return saved


def configuration_status(configuration: AIConfiguration | None) -> str:
    if configuration is None:
        return "Nenhuma configuração salva."
    if not configuration.is_active:
        return "Configuração inativa."
    if (
        configuration.type == AIConfiguration.Type.LOCAL
        and not configuration.local_endpoint
    ):
        return "Informe o endpoint do Ollama para concluir a configuração."
    try:
        configuration.full_clean()
    except ValidationError:
        return "Configuração incompleta ou inválida."
    if configuration.type == AIConfiguration.Type.LOCAL:
        return "Configuração salva. Disponibilidade do Ollama ainda não verificada."
    if not os.environ.get("MISTRAL_API_KEY", "").strip():
        return "Credencial Mistral não configurada no ambiente."
    return (
        "Configuração salva. Credencial presente no ambiente; conexão não verificada."
    )


def discover_ollama_models(endpoint: str, *, client=None) -> tuple[str, ...]:
    normalized_endpoint = normalize_local_endpoint(endpoint)
    return OllamaProvider.list_models(base_url=normalized_endpoint, client=client)
