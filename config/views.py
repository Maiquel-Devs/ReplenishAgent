"""Project-level views."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    """Return the application liveness status."""
    return JsonResponse({"status": "ok"})
