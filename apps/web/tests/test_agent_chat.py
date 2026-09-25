import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.agent.models import AIConfiguration, AgentExecution, AgentToolExecution
from apps.agent.providers import (
    FakeLLMProvider,
    LLMProviderError,
    LLMResponse,
    MistralProvider,
    OllamaProvider,
    ToolCall,
)
from apps.web.agent_service import run_agent


pytestmark = pytest.mark.django_db


@pytest.fixture
def agent_user():
    return get_user_model().objects.create_user(username="agent-chat-user")


def configured_ollama(*, active=True):
    return AIConfiguration.objects.create(
        type="LOCAL",
        integration="ollama",
        local_endpoint="http://host.docker.internal:11434",
        model="llama3.2:3b",
        is_active=active,
    )


def configured_mistral(*, active=True):
    return AIConfiguration.objects.create(
        type="CLOUD",
        integration="mistral",
        local_endpoint="",
        model="ministral-3b-2512",
        is_active=active,
    )


def test_anonymous_user_cannot_access_agent(client):
    response = client.get(reverse("web:agent_chat"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_authenticated_user_sees_agent_interface_and_navigation(client, agent_user):
    client.force_login(agent_user)
    response = client.get(reverse("web:agent_chat"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Assistente para análise e planejamento de reposição" in content
    assert "Digite sua mensagem" in content
    assert ">Agent<" in content
    assert "Configuração da IA" not in content
    assert "Modo de demonstração" not in content


def test_web_chat_uses_saved_ollama_provider_and_records_audit(
    client, agent_user, monkeypatch
):
    configured_ollama()
    seen = []

    def generate(self, messages, tools):
        seen.append((self.base_url, self.model, messages, tools))
        return LLMResponse(content="Resposta do modelo configurado")

    monkeypatch.setattr(OllamaProvider, "generate", generate)
    client.force_login(agent_user)
    response = client.post(reverse("web:agent_chat"), {"message": "Olá"}, follow=True)
    assert response.status_code == 200
    assert "Resposta do modelo configurado" in response.content.decode()
    assert "Olá" in response.content.decode()
    assert len(seen) == 1
    endpoint, model, messages, tools = seen[0]
    assert endpoint == "http://host.docker.internal:11434"
    assert model == "llama3.2:3b"
    assert messages[1].content == "Olá"
    assert any(tool.name == "consultar_estoque" for tool in tools)
    execution = AgentExecution.objects.get()
    assert execution.user == agent_user
    assert execution.provider == "OllamaProvider"
    assert execution.model == "llama3.2:3b"
    assert execution.user_request == "Olá"
    assert execution.status == "COMPLETED"
    assert execution.duration_ms is not None


def test_web_chat_uses_saved_mistral_provider_and_records_audit(
    client, agent_user, monkeypatch
):
    configured_mistral()
    monkeypatch.setenv("MISTRAL_API_KEY", "offline-test-credential")
    seen = []

    def generate(self, messages, tools):
        seen.append((self.model, messages, tools))
        return LLMResponse(content="Resposta Cloud")

    monkeypatch.setattr(MistralProvider, "generate", generate)
    client.force_login(agent_user)
    response = client.post(reverse("web:agent_chat"), {"message": "Olá"}, follow=True)

    assert response.status_code == 200
    assert "Resposta Cloud" in response.content.decode()
    assert len(seen) == 1
    assert seen[0][0] == "ministral-3b-2512"
    execution = AgentExecution.objects.get()
    assert execution.provider == "MistralProvider"
    assert execution.model == "ministral-3b-2512"
    assert execution.status == "COMPLETED"


def test_explicit_fake_injection_keeps_agent_offline_and_tools_authorized(agent_user):
    call = ToolCall(
        id="blocked-write",
        name="criar_proposta_compra",
        arguments={
            "product_supplier_id": 1,
            "consumption_days": 30,
            "planning_days": 30,
        },
    )
    fake = FakeLLMProvider(
        [LLMResponse(tool_calls=(call,)), LLMResponse(content="Concluído")]
    )
    assert run_agent(user=agent_user, message="Teste", provider=fake) == "Concluído"
    assert (
        json.loads(fake.calls[1].messages[-1].content)["error"]["code"]
        == "not_authorized"
    )
    tool_audit = AgentToolExecution.objects.get()
    assert tool_audit.permission_level == "WRITE"
    assert tool_audit.status == "BLOCKED"
    assert AgentExecution.objects.get().provider == "FakeLLMProvider"


@pytest.mark.parametrize(
    "configuration_state", ["missing", "inactive", "endpoint", "model"]
)
def test_incomplete_configuration_is_friendly_and_never_uses_fake(
    client, agent_user, monkeypatch, configuration_state
):
    if configuration_state != "missing":
        configured_ollama(active=configuration_state != "inactive")
    if configuration_state == "endpoint":
        AIConfiguration.objects.update(local_endpoint="")
    if configuration_state == "model":
        AIConfiguration.objects.update(model="")
    monkeypatch.setattr(
        FakeLLMProvider,
        "generate",
        lambda *args: pytest.fail("Fake must never be an implicit fallback"),
    )
    client.force_login(agent_user)
    response = client.post(reverse("web:agent_chat"), {"message": "Olá"})
    html = response.content.decode()
    assert response.status_code == 200
    assert "configuração da IA está ausente, inativa ou incompleta" in html
    assert "Traceback" not in html
    assert AgentExecution.objects.count() == 0
    assert client.session.get("agent_conversation", []) == []


def test_missing_mistral_credential_is_friendly_without_local_fallback(
    client, agent_user, monkeypatch
):
    configured_mistral()
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        lambda *args: pytest.fail("Cloud must not fall back to Ollama"),
    )
    client.force_login(agent_user)

    response = client.post(reverse("web:agent_chat"), {"message": "Olá"})
    html = response.content.decode()

    assert response.status_code == 200
    assert "configuração da IA está ausente, inativa ou incompleta" in html
    assert "MISTRAL_API_KEY" not in html
    assert AgentExecution.objects.count() == 0


@pytest.mark.parametrize(
    "provider_error",
    [
        "Ollama is unavailable.",
        "Ollama request timed out.",
        "Ollama returned invalid JSON.",
        "Ollama returned an unexpected payload.",
    ],
)
def test_provider_failure_is_friendly_and_audited(
    client, agent_user, monkeypatch, provider_error
):
    configured_ollama()

    def fail(self, messages, tools):
        raise LLMProviderError(provider_error)

    monkeypatch.setattr(OllamaProvider, "generate", fail)
    client.force_login(agent_user)
    response = client.post(reverse("web:agent_chat"), {"message": "Olá"})
    html = response.content.decode()
    assert response.status_code == 200
    assert "IA configurada está indisponível" in html
    assert provider_error not in html
    assert "Traceback" not in html
    assert AgentExecution.objects.get().status == "FAILED"
    assert AgentExecution.objects.get().error_code == "agent_error"
    assert client.session.get("agent_conversation", []) == []


def test_agent_conversation_escapes_user_content(client, agent_user, monkeypatch):
    configured_ollama()
    monkeypatch.setattr(
        OllamaProvider,
        "generate",
        lambda *args: LLMResponse(content="Resposta"),
    )
    client.force_login(agent_user)
    response = client.post(
        reverse("web:agent_chat"),
        {"message": "<script>alert('xss')</script>"},
        follow=True,
    )
    content = response.content.decode()
    assert "&lt;script&gt;alert" in content
    assert "<script>alert" not in content


def test_agent_post_enforces_csrf(agent_user):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(agent_user)
    response = csrf_client.post(reverse("web:agent_chat"), {"message": "Sem token"})
    assert response.status_code == 403
    assert AgentExecution.objects.count() == 0


def test_display_history_is_not_sent_to_provider(
    client,
    agent_user,
    monkeypatch,
):
    configured_ollama()
    captured = []

    def generate(self, messages, tools):
        captured.append(messages)
        return LLMResponse(content="Resposta nova")

    monkeypatch.setattr(OllamaProvider, "generate", generate)
    client.force_login(agent_user)
    session = client.session
    session["agent_conversation"] = [
        {"role": "user", "content": "Produto antigo da sessão"},
        {"role": "assistant", "content": "Resposta antiga da sessão"},
    ]
    session.save()

    response = client.post(
        reverse("web:agent_chat"),
        {"message": "Pergunta genérica nova"},
    )

    assert response.status_code == 302
    assert len(captured) == 1
    user_messages = [
        message.content for message in captured[0] if message.role.value == "user"
    ]
    assert user_messages == ["Pergunta genérica nova"]
    assert all(
        "Produto antigo da sessão" not in message.content
        and "Resposta antiga da sessão" not in message.content
        for message in captured[0]
    )
