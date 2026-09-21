import httpx
import pytest
from django.core.exceptions import ValidationError

from apps.agent.configuration import discover_ollama_models
from apps.agent.local_endpoint import normalize_local_endpoint
from apps.agent.providers.base import LLMProviderError


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        (" HTTP://HOST.DOCKER.INTERNAL:11434/ ", "http://host.docker.internal:11434"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://10.1.2.3:11434", "http://10.1.2.3:11434"),
        ("http://172.16.1.2:11434", "http://172.16.1.2:11434"),
        ("http://192.168.1.2:11434", "http://192.168.1.2:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
        ("http://[fd00::1]:11434", "http://[fd00::1]:11434"),
        ("https://host.docker.internal:443", "https://host.docker.internal:443"),
    ],
)
def test_valid_local_endpoints_are_normalized(value, normalized):
    assert normalize_local_endpoint(value) == normalized


@pytest.mark.parametrize(
    "value",
    [
        "",
        "file:///etc/passwd",
        "ftp://localhost:11434",
        "http://user:pass@localhost:11434",
        "http://localhost:11434/api/tags",
        "http://localhost:11434/?x=1",
        "http://localhost:11434/#fragment",
        "http://localhost",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:abc",
        "http://localhost:80",
        "http://host.docker.internal.evil.example:11434",
        "http://ollama.internal:11434",
        "http://8.8.8.8:11434",
        "http://169.254.169.254:11434",
        "http://[fe80::1]:11434",
        "http://0.0.0.0:11434",
        "http://2130706433:11434",
        "http://0177.0.0.1:11434",
        "http://[::ffff:169.254.169.254]:11434",
        "http://localhost:11434\\@evil.example",
        "http://localhost:11434\n",
    ],
)
def test_unsafe_endpoints_are_rejected(value):
    with pytest.raises(ValidationError):
        normalize_local_endpoint(value)


def test_endpoint_policy_does_not_resolve_user_supplied_dns(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("DNS lookup should not occur during validation")

    monkeypatch.setattr("socket.getaddrinfo", fail)
    assert normalize_local_endpoint("http://host.docker.internal:11434") == (
        "http://host.docker.internal:11434"
    )
    with pytest.raises(ValidationError):
        normalize_local_endpoint("http://attacker.example:11434")


def _client(response_factory):
    return httpx.Client(
        transport=httpx.MockTransport(response_factory), trust_env=False
    )


def test_discovery_uses_only_get_tags_and_returns_installed_models():
    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200, json={"models": [{"name": "llama3.2:3b"}, {"name": "qwen:7b"}]}
        )

    with _client(respond) as client:
        assert discover_ollama_models(
            "http://host.docker.internal:11434", client=client
        ) == ("llama3.2:3b", "qwen:7b")


def test_discovery_accepts_empty_list():
    with _client(lambda request: httpx.Response(200, json={"models": []})) as client:
        assert discover_ollama_models("http://localhost:11434", client=client) == ()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"other": []}),
        httpx.Response(200, json={"models": [{}]}),
        httpx.Response(503),
    ],
)
def test_discovery_rejects_invalid_responses(response):
    with _client(lambda request: response) as client:
        with pytest.raises(LLMProviderError):
            discover_ollama_models("http://localhost:11434", client=client)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_discovery_handles_connection_errors_and_timeout(error):
    def fail(request):
        raise error("offline", request=request)

    with _client(fail) as client:
        with pytest.raises(LLMProviderError):
            discover_ollama_models("http://localhost:11434", client=client)


def test_discovery_does_not_follow_redirects_to_public_host():
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(
            302, headers={"Location": "http://169.254.169.254/latest/meta-data"}
        )

    with _client(respond) as client:
        with pytest.raises(LLMProviderError):
            discover_ollama_models("http://localhost:11434", client=client)
    assert len(calls) == 1
