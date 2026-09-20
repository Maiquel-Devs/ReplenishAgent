from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator

from .auth_forms import ReplenishAuthenticationForm
from .demo import DEMO_ACCOUNTS


@method_decorator(login_not_required, name="dispatch")
class ReplenishLoginView(LoginView):
    authentication_form = ReplenishAuthenticationForm
    redirect_authenticated_user = True
    template_name = "registration/login.html"

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        context["demo_credentials"] = _visible_demo_credentials()
        return context


def _visible_demo_credentials() -> tuple[dict[str, str], ...]:
    return DEMO_ACCOUNTS if settings.DEBUG else ()


def login_lockout(
    request: HttpRequest,
    response: HttpResponse | None = None,
    credentials: dict | None = None,
    *args,
    **kwargs,
) -> HttpResponse:
    del response, credentials, args, kwargs
    form = ReplenishAuthenticationForm(request=request)
    lockout_response = render(
        request,
        "registration/login.html",
        {
            "form": form,
            "login_blocked": True,
            "demo_credentials": _visible_demo_credentials(),
        },
        status=429,
    )
    cooloff = settings.AXES_COOLOFF_TIME
    if isinstance(cooloff, timedelta):
        lockout_response["Retry-After"] = max(1, int(cooloff.total_seconds()))
    return lockout_response
