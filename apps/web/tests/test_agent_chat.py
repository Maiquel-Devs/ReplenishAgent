import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.agent.models import AgentExecution


pytestmark = pytest.mark.django_db


@pytest.fixture
def agent_user():
    return get_user_model().objects.create_user(username="agent-chat-user")


def test_anonymous_user_cannot_access_agent(client):
    response = client.get(reverse("web:agent_chat"))

    assert response.status_code == 302
    assert reverse("login") in response.url


def test_authenticated_user_sees_agent_interface_and_navigation(
    client,
    agent_user,
):
    client.force_login(agent_user)

    response = client.get(reverse("web:agent_chat"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Assistente para análise e planejamento de reposição" in content
    assert "Digite sua mensagem" in content
    assert ">Agent<" in content
    assert "Configuração da IA" not in content


def test_agent_message_uses_fake_provider_and_records_audit(client, agent_user):
    client.force_login(agent_user)

    response = client.post(
        reverse("web:agent_chat"),
        {"message": "Analise o estoque"},
        follow=True,
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Analise o estoque" in content
    assert "A conexão com o provider será habilitada" in content

    execution = AgentExecution.objects.get()
    assert execution.user == agent_user
    assert execution.provider == "FakeLLMProvider"
    assert execution.user_request == "Analise o estoque"
    assert execution.status == "COMPLETED"


def test_agent_conversation_escapes_user_content(client, agent_user):
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

    response = csrf_client.post(
        reverse("web:agent_chat"),
        {"message": "Sem token"},
    )

    assert response.status_code == 403
    assert AgentExecution.objects.count() == 0
