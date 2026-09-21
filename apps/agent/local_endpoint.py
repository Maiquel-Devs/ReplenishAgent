"""Validation policy for administrator-configured local runtime endpoints."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError


_ALLOWED_NAMES = frozenset({"localhost", "host.docker.internal"})
_ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
    )
)


def normalize_local_endpoint(value: str) -> str:
    """Accept a local/private origin only; never perform a DNS precheck."""
    if not isinstance(value, str):
        raise ValidationError("Informe um endpoint válido para o Ollama.")
    raw = value.strip(" ")
    if not raw or any(character.isspace() or ord(character) < 32 for character in raw):
        raise ValidationError("Informe um endpoint válido para o Ollama.")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Hostname ou porta inválida.") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValidationError("Use somente http ou https.")
    if (
        not host
        or not port
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or "\\" in parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or "?" in raw
        or "#" in raw
    ):
        raise ValidationError(
            "Use apenas a origem do Ollama, sem credenciais, caminho ou parâmetros."
        )
    if port < 1024 and not (parsed.scheme.lower() == "https" and port == 443):
        raise ValidationError("Use uma porta não privilegiada ou HTTPS na porta 443.")

    host = host.lower()
    if host not in _ALLOWED_NAMES:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValidationError(
                "Use localhost, host.docker.internal ou um IP privado."
            ) from exc
        if not any(address in network for network in _ALLOWED_NETWORKS):
            raise ValidationError("O endpoint deve estar em uma rede local ou privada.")
        host = address.compressed
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}:{port}"
