from django.http import HttpRequest


def direct_peer_ip(request: HttpRequest) -> str | None:
    """Use the network peer address without trusting forwarded client headers."""
    return request.META.get("REMOTE_ADDR")
