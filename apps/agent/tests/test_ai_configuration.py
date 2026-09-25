from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.agent.configuration import (
    AIConfigurationError,
    configuration_status,
    discover_mistral_models,
    save_ai_configuration,
)
from apps.agent.models import AIConfiguration, AIConfigurationChange
from apps.agent.providers import MistralProvider, OllamaProvider, create_llm_provider


pytestmark = pytest.mark.django_db


def config(
    type="LOCAL", integration="ollama", model="qwen:test", active=True, endpoint=None
):
    if endpoint is None:
        endpoint = "http://host.docker.internal:11434" if type == "LOCAL" else ""
    return AIConfiguration.objects.create(
        type=type,
        integration=integration,
        model=model,
        is_active=active,
        local_endpoint=endpoint,
    )


@pytest.mark.parametrize(
    ("type", "integration"),
    [("LOCAL", "ollama"), ("CLOUD", "mistral")],
)
def test_supported_configuration_pairs_are_persisted(type, integration):
    selected = config(type=type, integration=integration, model="  selected-model  ")
    selected.refresh_from_db()

    assert selected.model == "selected-model"
    assert selected.pk == 1
    assert selected.updated_at is not None


@pytest.mark.parametrize(
    ("type", "integration"),
    [("LOCAL", "mistral"), ("CLOUD", "ollama")],
)
def test_invalid_pair_is_rejected(type, integration):
    with pytest.raises(ValidationError):
        config(type=type, integration=integration)


@pytest.mark.parametrize("model", ["", "  ", "contains space", "x" * 256])
def test_invalid_model_is_rejected(model):
    with pytest.raises(ValidationError):
        config(model=model)


def test_database_enforces_single_global_row():
    config()
    with pytest.raises(IntegrityError), transaction.atomic():
        AIConfiguration.objects.bulk_create(
            [AIConfiguration(pk=2, type="LOCAL", integration="ollama", model="other")]
        )
    assert AIConfiguration.objects.count() == 1


def test_factory_uses_persisted_ollama_endpoint_instead_of_environment(monkeypatch):
    config(model="qwen:configured")
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    monkeypatch.setenv("OLLAMA_MODEL", "ignored")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    client = Mock()

    provider = create_llm_provider(client=client)

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen:configured"
    assert provider.base_url == "http://host.docker.internal:11434"
    client.post.assert_not_called()


def test_factory_uses_persisted_mistral_selection_without_network(monkeypatch):
    config(type="CLOUD", integration="mistral", model="mistral-configured")
    monkeypatch.setenv("MISTRAL_API_KEY", "synthetic-test-value")
    monkeypatch.setenv("MISTRAL_MODEL", "ignored")
    client = Mock()

    provider = create_llm_provider(client=client)

    assert isinstance(provider, MistralProvider)
    assert provider.model == "mistral-configured"
    client.chat.complete.assert_not_called()


def test_factory_fails_closed_for_missing_inactive_and_incomplete_configuration(
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "legacy")
    with pytest.raises(AIConfigurationError, match="No AI configuration"):
        create_llm_provider(client=Mock())

    selected = config(active=False)
    with pytest.raises(AIConfigurationError, match="inactive"):
        create_llm_provider(client=Mock())

    selected.is_active = True
    selected.save()
    AIConfiguration.objects.filter(pk=1).update(model="")
    with pytest.raises(AIConfigurationError, match="invalid"):
        create_llm_provider(client=Mock())


def test_factory_reports_missing_credential_and_invalid_endpoint(monkeypatch):
    config()
    AIConfiguration.objects.filter(pk=1).update(local_endpoint="")
    with pytest.raises(AIConfigurationError, match="invalid"):
        create_llm_provider(client=Mock())

    AIConfiguration.objects.filter(pk=1).update(
        type="CLOUD",
        integration="mistral",
        model="mistral-configured",
        local_endpoint="",
    )
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(AIConfigurationError, match="MISTRAL_API_KEY"):
        create_llm_provider(client=Mock())


def test_factory_never_falls_back_between_cloud_and_local(monkeypatch):
    config(type="CLOUD", integration="mistral", model="mistral-configured")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    ollama = Mock()
    monkeypatch.setattr("apps.agent.providers.factory.OllamaProvider", ollama)

    with pytest.raises(AIConfigurationError, match="MISTRAL_API_KEY"):
        create_llm_provider(client=Mock())

    ollama.assert_not_called()

    AIConfiguration.objects.update(
        type="LOCAL",
        integration="ollama",
        model="llama3.2:3b",
        local_endpoint="",
    )
    mistral = Mock()
    monkeypatch.setattr("apps.agent.providers.factory.MistralProvider", mistral)

    with pytest.raises(AIConfigurationError, match="invalid"):
        create_llm_provider(client=Mock())

    mistral.assert_not_called()


def test_factory_rejects_invalid_mistral_timeout(monkeypatch):
    config(type="CLOUD", integration="mistral", model="mistral-configured")
    monkeypatch.setenv("MISTRAL_API_KEY", "offline-test-credential")
    monkeypatch.setenv("MISTRAL_TIMEOUT", "not-a-number")

    with pytest.raises(AIConfigurationError, match="MISTRAL_TIMEOUT"):
        create_llm_provider(client=Mock())


def test_mistral_discovery_uses_environment_credential_without_inference(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "offline-test-credential")
    client = Mock()
    client.models.list.return_value = SimpleNamespace(
        data=[SimpleNamespace(id="ministral-3b-2512", aliases=[])]
    )

    assert discover_mistral_models(client=client) == ("ministral-3b-2512",)
    client.models.list.assert_called_once_with()
    client.chat.complete.assert_not_called()


def test_mistral_discovery_requires_environment_credential(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    client = Mock()

    with pytest.raises(AIConfigurationError, match="MISTRAL_API_KEY"):
        discover_mistral_models(client=client)

    client.models.list.assert_not_called()


def test_local_requires_endpoint_and_cloud_rejects_it():
    with pytest.raises(ValidationError):
        config(endpoint="")
    with pytest.raises(ValidationError):
        config(type="CLOUD", integration="mistral", endpoint="http://127.0.0.1:11434")


def test_explicit_factory_injection_still_works_without_persisted_row(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://trusted-ollama:11434")
    provider = create_llm_provider(provider="ollama", model="test-model", client=Mock())
    assert provider.model == "test-model"


def test_configuration_change_audit_excludes_model_and_secret(monkeypatch, caplog):
    monkeypatch.setenv("MISTRAL_API_KEY", "synthetic-test-value")
    user = get_user_model().objects.create_user(username="config-admin")
    selected = AIConfiguration(
        type="CLOUD", integration="mistral", model="mistral-configured"
    )

    saved = save_ai_configuration(selected, user=user)
    event = AIConfigurationChange.objects.get()

    assert event.user == user
    assert event.type == "CLOUD"
    assert event.integration == "mistral"
    assert event.is_active is True
    assert event.changed_at is not None
    assert "synthetic-test-value" not in repr(saved)
    assert "synthetic-test-value" not in repr(
        AIConfiguration(
            type="CLOUD", integration="mistral", model="synthetic-test-value"
        )
    )
    assert "synthetic-test-value" not in repr(event)
    assert not hasattr(event, "model")
    assert "synthetic-test-value" not in caplog.text
    assert "Credencial presente" in configuration_status(saved)


@pytest.mark.parametrize(
    ("type", "integration", "active", "env_name", "expected"),
    [
        ("LOCAL", "ollama", False, "OLLAMA_BASE_URL", "inativa"),
        ("CLOUD", "mistral", True, "MISTRAL_API_KEY", "não configurada"),
    ],
)
def test_configuration_status_explains_incomplete_selection(
    monkeypatch, type, integration, active, env_name, expected
):
    selected = config(type=type, integration=integration, active=active)
    monkeypatch.delenv(env_name, raising=False)
    assert expected in configuration_status(selected)


def test_configuration_status_does_not_check_runtime_availability(monkeypatch):
    selected = config()
    assert "ainda não verificada" in configuration_status(selected)


def test_status_reports_missing_stored_local_endpoint():
    selected = config()
    AIConfiguration.objects.filter(pk=selected.pk).update(local_endpoint="")
    selected.refresh_from_db()
    assert "Informe o endpoint" in configuration_status(selected)


def test_persisted_endpoint_is_normalized_and_cloud_needs_no_ollama_env(monkeypatch):
    selected = config(endpoint=" HTTP://HOST.DOCKER.INTERNAL:11434/ ")
    selected.refresh_from_db()
    assert selected.local_endpoint == "http://host.docker.internal:11434"

    selected.type = "CLOUD"
    selected.integration = "mistral"
    selected.model = "mistral-configured"
    selected.local_endpoint = ""
    selected.save()
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("MISTRAL_API_KEY", "synthetic-test-value")
    provider = create_llm_provider(client=Mock())
    assert isinstance(provider, MistralProvider)


def test_configuration_audit_does_not_store_endpoint():
    user = get_user_model().objects.create_user(username="endpoint-auditor")
    saved = save_ai_configuration(
        AIConfiguration(
            type="LOCAL",
            integration="ollama",
            model="llama3.2:3b",
            local_endpoint="http://host.docker.internal:11434",
        ),
        user=user,
    )
    event = AIConfigurationChange.objects.get()
    assert saved.local_endpoint == "http://host.docker.internal:11434"
    assert not hasattr(event, "local_endpoint")
    assert "host.docker.internal" not in repr(event)
