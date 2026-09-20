"""Project-level views."""
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@login_not_required
@require_GET
def health(request):
    """Return the application liveness status."""
    return JsonResponse({"status": "ok"})
