"""Django settings for the ReplenishAgent project."""

import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be a boolean value.")


def _env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]


def _env_non_negative_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc
    if value < 0:
        raise ImproperlyConfigured(f"{name} cannot be negative.")
    return value


def _env_positive_int(name: str, default: int) -> int:
    value = _env_non_negative_int(name, default)
    if value == 0:
        raise ImproperlyConfigured(f"{name} must be greater than zero.")
    return value


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = _env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


HTTPS_ENABLED = _env_bool("DJANGO_HTTPS_ENABLED", False)
SESSION_COOKIE_SECURE = _env_bool(
    "DJANGO_SESSION_COOKIE_SECURE",
    HTTPS_ENABLED,
)
CSRF_COOKIE_SECURE = _env_bool(
    "DJANGO_CSRF_COOKIE_SECURE",
    HTTPS_ENABLED,
)
SECURE_SSL_REDIRECT = _env_bool(
    "DJANGO_SECURE_SSL_REDIRECT",
    HTTPS_ENABLED,
)
SECURE_HSTS_SECONDS = _env_non_negative_int(
    "DJANGO_SECURE_HSTS_SECONDS",
    3600 if HTTPS_ENABLED else 0,
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    False,
)
SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if _env_bool("DJANGO_TRUST_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "apps.products",
    "apps.suppliers",
    "apps.inventory",
    "apps.replenishment",
    "apps.purchasing",
    "apps.web",
    "apps.agent",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = _env_positive_int("DJANGO_LOGIN_FAILURE_LIMIT", 5)
AXES_COOLOFF_TIME = timedelta(
    minutes=_env_positive_int("DJANGO_LOGIN_COOLOFF_MINUTES", 15)
)
AXES_USE_ATTEMPT_EXPIRATION = True
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_CLIENT_IP_CALLABLE = "apps.web.security.direct_peer_ip"
AXES_LOCKOUT_CALLABLE = "apps.web.auth_views.login_lockout"
AXES_HTTP_RESPONSE_CODE = 429
AXES_ENABLE_RETRY_AFTER_HEADER = True
AXES_SENSITIVE_PARAMETERS = ["username", "ip_address", "password"]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "web:agent_chat"
LOGOUT_REDIRECT_URL = "login"
