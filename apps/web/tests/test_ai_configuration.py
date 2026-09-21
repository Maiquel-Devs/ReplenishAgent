import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.agent.models import AIConfiguration, AIConfigurationChange


pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator():
    user = get_user_model().objects.create_user(username="ai-settings-admin")
    user.user_permissions.add(
        Permission.objects.get(codename="configure_ai", content_type__app_label="agent")
    )
    return user


@pytest.fixture
def operator():
    return get_user_model().objects.create_user(username="ai-settings-operator")


def payload(**changes):
    values = {
        "type": "LOCAL",
        "integration": "ollama",
        "model": "qwen:test",
        "local_endpoint": "http://host.docker.internal:11434",
        "is_active": "on",
    }
    values.update(changes)
    if values["type"] == "CLOUD" and "local_endpoint" not in changes:
        values["local_endpoint"] = ""
    return values


def test_admin_can_view_empty_configuration(client, administrator):
    client.force_login(administrator)
    response = client.get(reverse("web:ai_configuration"))
    assert response.status_code == 200
    assert "Nenhuma configuração salva" in response.content.decode()
    assert "Ollama" in response.content.decode()
    assert "Mistral" in response.content.decode()
    assert AIConfiguration.objects.count() == 0


def test_admin_can_save_and_reopen_both_types(client, administrator):
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    first = client.post(url, payload())
    second = client.post(
        url,
        payload(type="CLOUD", integration="mistral", model="mistral-configured"),
    )
    reopened = client.get(url)
    selected = AIConfiguration.objects.get()

    assert first.status_code == 302
    assert second.status_code == 302
    assert selected.type == "CLOUD"
    assert selected.integration == "mistral"
    assert selected.model == "mistral-configured"
    assert selected.local_endpoint == ""
    assert AIConfiguration.objects.count() == 1
    assert AIConfigurationChange.objects.count() == 2
    assert 'value="mistral-configured"' in reopened.content.decode()


def test_operator_cannot_get_or_post(client, operator):
    client.force_login(operator)
    url = reverse("web:ai_configuration")
    assert client.get(url).status_code == 403
    assert client.post(url, payload()).status_code == 403
    assert AIConfiguration.objects.count() == 0


def test_get_and_non_post_methods_do_not_mutate(client, administrator):
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    assert client.get(url).status_code == 200
    assert client.put(url, data=payload()).status_code == 405
    assert AIConfiguration.objects.count() == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "LOCAL", "integration": "mistral"},
        {"type": "CLOUD", "integration": "ollama"},
        {"model": ""},
        {"model": "x" * 256},
    ],
)
def test_invalid_post_displays_errors_without_mutation(client, administrator, changes):
    client.force_login(administrator)
    response = client.post(reverse("web:ai_configuration"), payload(**changes))
    assert response.status_code == 200
    assert response.context["form"].errors
    assert AIConfiguration.objects.count() == 0
    assert AIConfigurationChange.objects.count() == 0


def test_post_enforces_csrf(administrator):
    client = Client(enforce_csrf_checks=True)
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    assert client.post(url, payload()).status_code == 403

    response = client.get(url)
    token = response.cookies["csrftoken"].value
    assert client.post(url, payload(), HTTP_X_CSRFTOKEN=token).status_code == 302
    assert AIConfiguration.objects.count() == 1


def test_credential_value_never_appears_in_html_or_change_record(
    client, administrator, monkeypatch
):
    monkeypatch.setenv("MISTRAL_API_KEY", "synthetic-test-value")
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    client.post(
        url,
        payload(
            type="CLOUD",
            integration="mistral",
            model="mistral-configured",
            api_key="synthetic-test-value",
        ),
    )
    html = client.get(url).content.decode()
    event = AIConfigurationChange.objects.get()

    assert "configurada pelo ambiente" in html
    assert "synthetic-test-value" not in html
    assert "synthetic-test-value" not in repr(event)
    assert 'name="api_key"' not in html


def test_cloud_page_reports_missing_credential_without_external_check(
    client, administrator, monkeypatch
):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    AIConfiguration.objects.create(
        type="CLOUD", integration="mistral", model="mistral-configured"
    )
    client.force_login(administrator)

    html = client.get(reverse("web:ai_configuration")).content.decode()

    assert "Credencial Mistral não configurada" in html
    assert "não configurada" in html


def test_test_connection_discovers_models_without_saving(
    client, administrator, monkeypatch
):
    seen = []

    def discover(endpoint):
        seen.append(endpoint)
        return ("llama3.2:3b", "qwen:7b")

    monkeypatch.setattr("apps.web.admin_views.discover_ollama_models", discover)
    client.force_login(administrator)
    response = client.post(
        reverse("web:ai_configuration"),
        payload(
            action="test",
            model="",
            local_endpoint=" HTTP://HOST.DOCKER.INTERNAL:11434/ ",
        ),
    )
    html = response.content.decode()

    assert response.status_code == 200
    assert seen == ["http://host.docker.internal:11434"]
    assert "Ollama conectado" in html
    assert "2 modelos disponíveis" in html
    assert 'value="llama3.2:3b"' in html
    assert AIConfiguration.objects.count() == 0
    assert AIConfigurationChange.objects.count() == 0


def test_connection_failure_is_friendly_and_does_not_save(
    client, administrator, monkeypatch
):
    from apps.agent.providers.base import LLMProviderError

    def fail(endpoint):
        raise LLMProviderError("internal-network-detail")

    monkeypatch.setattr("apps.web.admin_views.discover_ollama_models", fail)
    client.force_login(administrator)
    response = client.post(reverse("web:ai_configuration"), payload(action="test"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Não foi possível conectar" in html
    assert "internal-network-detail" not in html
    assert "Traceback" not in html
    assert AIConfiguration.objects.count() == 0
    assert AIConfigurationChange.objects.count() == 0


def test_invalid_test_endpoint_never_reaches_network(
    client, administrator, monkeypatch
):
    def fail(endpoint):
        raise AssertionError("network should not be called")

    monkeypatch.setattr("apps.web.admin_views.discover_ollama_models", fail)
    client.force_login(administrator)
    response = client.post(
        reverse("web:ai_configuration"),
        payload(action="test", local_endpoint="http://169.254.169.254:11434"),
    )
    assert response.status_code == 200
    assert "rede local ou privada" in response.content.decode()
    assert AIConfiguration.objects.count() == 0


def test_operator_cannot_test_connection(client, operator):
    client.force_login(operator)
    response = client.post(reverse("web:ai_configuration"), payload(action="test"))
    assert response.status_code == 403


def test_connection_test_requires_post_and_csrf(administrator, monkeypatch):
    monkeypatch.setattr(
        "apps.web.admin_views.discover_ollama_models", lambda endpoint: ()
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    assert client.get(url + "?action=test").status_code == 200
    assert client.post(url, payload(action="test")).status_code == 403

    token = client.get(url).cookies["csrftoken"].value
    assert (
        client.post(url, payload(action="test"), HTTP_X_CSRFTOKEN=token).status_code
        == 200
    )
    assert AIConfigurationChange.objects.count() == 0


def test_get_does_not_discover_models(client, administrator, monkeypatch):
    def fail(endpoint):
        raise AssertionError("GET should not call Ollama")

    monkeypatch.setattr("apps.web.admin_views.discover_ollama_models", fail)
    client.force_login(administrator)
    assert client.get(reverse("web:ai_configuration")).status_code == 200


def test_discovery_preserves_saved_model_and_endpoint(
    client, administrator, monkeypatch
):
    AIConfiguration.objects.create(
        type="LOCAL",
        integration="ollama",
        model="older-model",
        local_endpoint="http://127.0.0.1:11434",
    )
    monkeypatch.setattr(
        "apps.web.admin_views.discover_ollama_models",
        lambda endpoint: ("llama3.2:3b",),
    )
    client.force_login(administrator)
    response = client.post(
        reverse("web:ai_configuration"),
        payload(
            action="test",
            model="older-model",
            local_endpoint="http://host.docker.internal:11434",
        ),
    )
    saved = AIConfiguration.objects.get()

    assert 'value="older-model"' in response.content.decode()
    assert 'value="llama3.2:3b"' in response.content.decode()
    assert saved.model == "older-model"
    assert saved.local_endpoint == "http://127.0.0.1:11434"
    assert AIConfigurationChange.objects.count() == 0


def test_cloud_cannot_trigger_ollama_test(client, administrator, monkeypatch):
    def fail(endpoint):
        raise AssertionError("cloud must not call Ollama")

    monkeypatch.setattr("apps.web.admin_views.discover_ollama_models", fail)
    client.force_login(administrator)
    response = client.post(
        reverse("web:ai_configuration"),
        payload(action="test", type="CLOUD", integration="mistral"),
    )
    assert response.status_code == 200
    assert "Local / Ollama" in response.content.decode()
    assert AIConfiguration.objects.count() == 0


def test_admin_saves_and_reopens_local_endpoint(client, administrator):
    client.force_login(administrator)
    url = reverse("web:ai_configuration")
    response = client.post(
        url,
        payload(local_endpoint=" HTTP://HOST.DOCKER.INTERNAL:11434/ "),
    )
    selected = AIConfiguration.objects.get()
    reopened = client.get(url).content.decode()

    assert response.status_code == 302
    assert selected.local_endpoint == "http://host.docker.internal:11434"
    assert 'value="http://host.docker.internal:11434"' in reopened
    assert AIConfigurationChange.objects.count() == 1


def test_connection_success_with_no_models_keeps_form_usable(
    client, administrator, monkeypatch
):
    monkeypatch.setattr(
        "apps.web.admin_views.discover_ollama_models", lambda endpoint: ()
    )
    client.force_login(administrator)
    response = client.post(
        reverse("web:ai_configuration"), payload(action="test", model="")
    )
    html = response.content.decode()

    assert response.status_code == 200
    assert "Ollama conectado" in html
    assert "Nenhum modelo instalado" in html
    assert "Salvar configuração" in html
    assert AIConfiguration.objects.count() == 0
