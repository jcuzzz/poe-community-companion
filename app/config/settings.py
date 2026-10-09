"""Django settings for the PoE Community Companion PoE league tracker."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)

if not DEBUG and SECRET_KEY == "dev-insecure-key-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is unset in production. Set a real key in .env "
        "(python -c \"import secrets; print(secrets.token_urlsafe(50))\")."
    )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker",
    "strategies",
]

# --- Feature modules -------------------------------------------------------
# PoE Community Companion is one companion app made of toggleable modules. Operators
# disable a module per instance (e.g. a gauntlet event that doesn't want the
# strategy library): disabled = no nav entry, its URLs 404. See
# docs/design/farming-strategies.md.
FEATURES = {
    "strategies": env_bool("FEATURE_STRATEGIES", True),
}

# Let anonymous visitors browse read-only pages (dashboard, leaderboard,
# strategies, ...). Writes always need a login. Off = whole site behind login.
PUBLIC_READ = env_bool("PUBLIC_READ", False)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

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
                "tracker.context_processors.league",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
MEDIA_ROOT_DIR = Path(os.environ.get("MEDIA_DIR", BASE_DIR / "media"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            "transaction_mode": "IMMEDIATE",
        },
    }
}

AUTH_USER_MODEL = "tracker.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "dashboard"

LANGUAGE_CODE = "en-au"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Australia/Sydney")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = MEDIA_ROOT_DIR

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # The manifest backend requires collectstatic, which dev runs and tests skip.
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Uploads -------------------------------------------------------------
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_PROOFS_PER_SUBMISSION = 3
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + (1024 * 1024)
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# --- Branding ------------------------------------------------------------
# User-facing site name. Configurable so self-hosted forks can brand their own.
SITE_NAME = os.environ.get("SITE_NAME", "PoE Community Companion")

# --- Notifications -------------------------------------------------------
# Optional Discord webhook. Left blank = feature off (no calls made).
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DISCORD_TIMEOUT = float(os.environ.get("DISCORD_TIMEOUT", "5"))
# Absolute base URL used to build links in notifications.
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "http://localhost:8000").rstrip("/")

# --- League --------------------------------------------------------------
# Leagues are DB-backed (tracker.models.League). LEAGUE_NAME only seeds the name of
# the FIRST league on a fresh install / initial migration; manage the rest in the
# admin. LEAGUE_START/END are legacy (each league carries its own dates). See
# docs/specs/leagues.md.
LEAGUE_NAME = os.environ.get("LEAGUE_NAME", "Current League")
LEAGUE_START = os.environ.get("LEAGUE_START", "")  # legacy, unused
LEAGUE_END = os.environ.get("LEAGUE_END", "")  # legacy, unused

# --- Roster / character lookup -------------------------------------------
# The primary roster path is Path of Building code paste (reliable, both games).
# Anonymous server-side auto-lookup via GGG's legacy character-window API is
# DISABLED by default: GGG's Cloudflare 403s non-browser TLS clients regardless of
# headers/IP (verified 2026), so it doesn't work from a server. Flip this on only if
# you have a working path (e.g. a future OAuth build). See
# docs/research/character-lookup-poe2.md and docs/specs/roster.md.
POE_AUTO_LOOKUP_ENABLED = env_bool("POE_AUTO_LOOKUP_ENABLED", False)
POE_API_BASE = os.environ.get("POE_API_BASE", "https://www.pathofexile.com")
# Public leagues endpoints (reachable server-side, no auth) for the "create a season
# from a dropdown" admin flow.
POE_LEAGUES_API = os.environ.get("POE_LEAGUES_API", "https://api.pathofexile.com/leagues")
POE2_LEAGUES_API = os.environ.get(
    "POE2_LEAGUES_API", "https://www.pathofexile.com/api/trade2/data/leagues"
)
POE_API_TIMEOUT = float(os.environ.get("POE_API_TIMEOUT", "8"))
POE_SNAPSHOT_TTL_SECONDS = int(os.environ.get("POE_SNAPSHOT_TTL_SECONDS", "600"))
# Contact (email/URL) GGG can reach you at; sent in the User-Agent.
POE_API_CONTACT = os.environ.get("POE_API_CONTACT", "self-hosted")
POE_USER_AGENT = os.environ.get(
    "POE_USER_AGENT", f"poe-community-companion/1.0 (contact: {POE_API_CONTACT})"
)

# --- Official GGG OAuth 2.0 (live character data) -------------------------
# Dormant until GGG issues an OAuth client. When POE_OAUTH_CLIENT_ID is set the
# "Connect PoE account" flow lights up and syncs pull live gear/skills/tree via
# the account:characters scope. Confidential (server-side) client + PKCE.
POE_OAUTH_CLIENT_ID = os.environ.get("POE_OAUTH_CLIENT_ID", "").strip()
POE_OAUTH_CLIENT_SECRET = os.environ.get("POE_OAUTH_CLIENT_SECRET", "").strip()
POE_OAUTH_REDIRECT_URI = os.environ.get(
    "POE_OAUTH_REDIRECT_URI", f"{SITE_BASE_URL}/account/poe/callback"
).strip()
POE_OAUTH_SCOPES = os.environ.get("POE_OAUTH_SCOPES", "account:profile account:characters").strip()
POE_OAUTH_AUTHORIZE_URL = os.environ.get(
    "POE_OAUTH_AUTHORIZE_URL", "https://www.pathofexile.com/oauth/authorize"
)
POE_OAUTH_TOKEN_URL = os.environ.get(
    "POE_OAUTH_TOKEN_URL", "https://www.pathofexile.com/oauth/token"
)
POE_OAUTH_API_BASE = os.environ.get("POE_OAUTH_API_BASE", "https://api.pathofexile.com")

# --- Security ------------------------------------------------------------
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

if not DEBUG:
    # Caddy terminates TLS and forwards X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", 0))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
