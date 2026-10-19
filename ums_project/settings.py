
import os
import secrets
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================================
# Lightweight .env loader
# ============================================================================
# No python-dotenv dependency is required.
#
# Local development:
#   Copy .env.example -> .env
#
# Production:
#   Prefer real environment variables supplied by the hosting environment.
# ============================================================================

_env_file = BASE_DIR / ".env"

if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()

        if (
            not _line
            or _line.startswith("#")
            or "=" not in _line
        ):
            continue

        _key, _, _value = _line.partition("=")

        _key = _key.strip()
        _value = _value.strip()

        # Remove simple surrounding quotes.
        if len(_value) >= 2:
            if (
                (_value.startswith('"') and _value.endswith('"'))
                or
                (_value.startswith("'") and _value.endswith("'"))
            ):
                _value = _value[1:-1]

        # A blank value ("KEY=") means "not configured" and should fall
        # through to whatever default the setting below uses - not
        # override that default with an empty string. Without this, an
        # unfilled-in placeholder line in .env.example (which is the
        # normal, expected way to leave an optional setting unconfigured)
        # silently breaks anything that has a non-empty default, e.g.
        # CACHE_BACKEND defaulting to LocMemCache.
        if _value:
            os.environ.setdefault(_key, _value)


# ============================================================================
# Environment helpers
# ============================================================================

def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)

    if value is None or value.strip() == "":
        return default

    try:
        return int(value)
    except ValueError:
        return default


def env_list(name: str, default: str = "") -> list[str]:
    return [
        value.strip()
        for value in os.environ.get(name, default).split(",")
        if value.strip()
    ]


# ============================================================================
# Core / security
# ============================================================================

# Safe deployment default.
#
# Local .env:
#   DEBUG=1
#
# Production:
#   DEBUG=0
#
DEBUG = env_bool("DEBUG", False)


# ----------------------------------------------------------------------------
# SECRET_KEY
# ----------------------------------------------------------------------------
#
# Production MUST provide DJANGO_SECRET_KEY.
#
# Development can automatically generate and persist a local secret key.
# The generated .secret_key file must never be committed to Git.
# ----------------------------------------------------------------------------

_secret_from_env = os.environ.get("DJANGO_SECRET_KEY", "").strip()
_secret_file = BASE_DIR / ".secret_key"

if _secret_from_env:
    SECRET_KEY = _secret_from_env

elif DEBUG:
    if _secret_file.exists():
        SECRET_KEY = _secret_file.read_text(
            encoding="utf-8"
        ).strip()

    else:
        SECRET_KEY = secrets.token_urlsafe(64)

        try:
            _secret_file.write_text(
                SECRET_KEY,
                encoding="utf-8",
            )
        except OSError:
            # Some restricted environments do not allow writing files.
            pass

else:
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be configured when DEBUG=0."
    )


if len(SECRET_KEY) < 50:
    raise RuntimeError(
        "DJANGO_SECRET_KEY must be at least 50 characters long."
    )


# ----------------------------------------------------------------------------
# Allowed hosts
# ----------------------------------------------------------------------------

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)

# PaaS hosts announce their own public hostname. Trusting it automatically
# means "deploy the same code to Render/Railway" needs no hand-edited host
# list. (Only the host the platform itself assigned - never user input.)
_PLATFORM_HOSTS = [
    h.strip() for h in (
        os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""),
        os.environ.get("RAILWAY_PUBLIC_DOMAIN", ""),
    ) if h.strip()
]
for _h in _PLATFORM_HOSTS:
    if _h not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_h)


# ============================================================================
# Applications
# ============================================================================

INSTALLED_APPS = [
    # Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework.authtoken",

    # Core
    "core",
    "governance",

    # Academic / university modules
    "academics",
    "admissions",
    "registration",
    "timetable",
    "exams",
    "finance",
    "hr",
    "attendance",

    # API / AI
    "api",
    "ai_assistant",

    # University services
    "library",
    "hostel",
    "complaints",
    "scholarships",
    "onlineclass",
    "alumni",
    "parents",
    "careers",

    # Intelligence / security
    "risk_analytics",
    "biometrics",
    "transport",
    "oversight",
    "digital_id",
    "workflow",

    # Learning
    "assignments",
    "quizzes",
]


# ============================================================================
# Middleware
# ============================================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # UMS custom middleware
    "core.middleware.DynamicSessionTimeoutMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Global error handling should remain near the end.
    "core.middleware.GlobalExceptionMiddleware",
]


ROOT_URLCONF = "ums_project.urls"


# ============================================================================
# Templates
# ============================================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "core" / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",

                # UMS custom context processors
                "core.context_processors.year_processor",
                "core.context_processors.branding_processor",
                "core.context_processors.role_processor",
                "core.context_processors.notifications_processor",
                "core.context_processors.governance_nav_processor",
            ],
        },
    },
]


WSGI_APPLICATION = "ums_project.wsgi.application"


# ============================================================================
# Database
# ============================================================================
#
# Development:
#   DB_ENGINE=sqlite
#
# Production:
#   DB_ENGINE=postgresql
#
# Optional MySQL support is retained.
# ============================================================================

DB_ENGINE = os.environ.get(
    "DB_ENGINE",
    "sqlite",
).strip().lower()

# Render, Railway, Heroku and most PaaS hosts provide one DATABASE_URL
# connection string rather than separate POSTGRES_* variables. When it's
# set, it takes precedence over everything below - this is what makes
# `render.yaml` (see deployment/render.yaml) work with zero manual DB config.
_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if _DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            _DATABASE_URL,
            conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
            ssl_require=env_bool("DB_SSL_REQUIRE", not DEBUG),
        )
    }

elif DB_ENGINE in {"postgres", "postgresql"}:

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get(
                "POSTGRES_DB",
                "ums",
            ),
            "USER": os.environ.get(
                "POSTGRES_USER",
                "umsuser",
            ),
            "PASSWORD": os.environ.get(
                "POSTGRES_PASSWORD",
                "",
            ),
            "HOST": os.environ.get(
                "POSTGRES_HOST",
                "localhost",
            ),
            "PORT": os.environ.get(
                "POSTGRES_PORT",
                "5432",
            ),
            "CONN_MAX_AGE": env_int(
                "DB_CONN_MAX_AGE",
                60,
            ),
        }
    }


elif DB_ENGINE == "mysql":

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get(
                "MYSQL_DB",
                "ums",
            ),
            "USER": os.environ.get(
                "MYSQL_USER",
                "umsuser",
            ),
            "PASSWORD": os.environ.get(
                "MYSQL_PASSWORD",
                "",
            ),
            "HOST": os.environ.get(
                "MYSQL_HOST",
                "localhost",
            ),
            "PORT": os.environ.get(
                "MYSQL_PORT",
                "3306",
            ),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
            "CONN_MAX_AGE": env_int(
                "DB_CONN_MAX_AGE",
                60,
            ),
        }
    }


else:

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.environ.get(
                "SQLITE_NAME",
                "db.sqlite3",
            ),
        }
    }


# ============================================================================
# Authentication
# ============================================================================

AUTHENTICATION_BACKENDS = [
    "core.auth_backends.CNICOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


# ============================================================================
# Django REST Framework
# ============================================================================

REST_FRAMEWORK = {
    # Secure by default.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],

    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],

    "DEFAULT_PAGINATION_CLASS": (
        "rest_framework.pagination.PageNumberPagination"
    ),

    "PAGE_SIZE": 25,

    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],

    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        "user": "120/min",
    },

    "EXCEPTION_HANDLER": (
        "api.exceptions.ums_api_exception_handler"
    ),

    # Browsable API is useful during development.
    # Production exposes JSON only.
    "DEFAULT_RENDERER_CLASSES": (
        [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
        if DEBUG
        else [
            "rest_framework.renderers.JSONRenderer",
        ]
    ),
}


# ============================================================================
# Internationalization
# ============================================================================

LANGUAGE_CODE = "en-us"

TIME_ZONE = os.environ.get(
    "TIME_ZONE",
    # This project is built for a Pakistani university (CNIC-based
    # identity, JazzCash/EasyPaisa payments) - defaulting to UTC here
    # was a real bug: a teacher scheduling a class or a student's
    # "current semester" calculations use plain local wall-clock input,
    # which Django interprets in whatever TIME_ZONE is configured. With
    # UTC as the default, a class typed as "1:06 AM" (meant as Pakistan
    # local time) got stored as 1:06 AM UTC = 6:06 AM PKT - a 5-hour
    # offset from what was actually meant, which is exactly why a class
    # could show "opens in 10 min" while already well inside its actual
    # window on a teacher's clock. Override with the TIME_ZONE env var
    # for a deployment outside Pakistan.
    "Asia/Karachi",
)

USE_I18N = True
USE_TZ = True


# ============================================================================
# Static files
# ============================================================================

STATIC_URL = "/static/"

# `core/static/` is not listed here on purpose: `core` is an installed app,
# so Django's default AppDirectoriesFinder already discovers its static/
# folder automatically. Also listing it in STATICFILES_DIRS made the same
# directory get found twice (once per finder), which is harmless but made
# `collectstatic` print a "Found another file with the destination path"
# warning for every single file in the project on every deploy.
STATICFILES_DIRS = []

STATIC_ROOT = BASE_DIR / "staticfiles"


STORAGES = {
    "default": {
        # Cloud storage is entirely optional. Local disk storage (the
        # default) works fully out of the box - set CLOUD_STORAGE_PROVIDER
        # only if you actually want uploaded files (documents, photos,
        # assignment submissions) kept in S3-compatible object storage
        # instead of the local filesystem. Requires `django-storages` and
        # `boto3` (see requirements.txt) - neither is installed by default
        # since most deployments never need them.
        "BACKEND": (
            "storages.backends.s3boto3.S3Boto3Storage"
            if os.environ.get("CLOUD_STORAGE_PROVIDER", "").lower() == "s3"
            else "django.core.files.storage.FileSystemStorage"
        ),
    },
    "staticfiles": {
        "BACKEND": (
            # Manifest storage (cache-busted filenames) needs
            # `collectstatic` to have run first, so it fails on
            # `manage.py test`/`runserver` in a fresh checkout before
            # that's ever been run. Use it only outside DEBUG (i.e. real
            # deployments, where the deploy checklist always runs
            # collectstatic first); plain WhiteNoise storage in DEBUG
            # still serves and compresses static files, just without the
            # manifest requirement.
            "whitenoise.storage.CompressedStaticFilesStorage"
            if DEBUG else
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}


# ============================================================================
# Media / uploaded files
# ============================================================================

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# Behind nginx, set to "/_protected_media/" so nginx streams files after
# Django has authorised the request (see deployment/nginx.conf). Blank =
# Django streams them itself - correct for gunicorn-only hosts.
MEDIA_ACCEL_PREFIX = os.environ.get("MEDIA_ACCEL_PREFIX", "").strip()

# Redirect uploads to a throwaway temp directory while running the test
# suite, so `manage.py test` never writes real files into the project's
# actual media/ folder. Without this, every test that exercises a
# FileField/ImageField (hostel docs, admission docs, profile photos, ...)
# permanently accumulates generated test files in media/ on every run.
if 'test' in sys.argv or 'pytest' in sys.modules:
    import tempfile
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix='ums_test_media_'))

# Only read/used when CLOUD_STORAGE_PROVIDER=s3 selects S3Boto3Storage
# above. Left blank, cloud storage is simply never activated.
if os.environ.get("CLOUD_STORAGE_PROVIDER", "").lower() == "s3":
    AWS_ACCESS_KEY_ID = os.environ.get("CLOUD_STORAGE_ACCESS_KEY", "")
    AWS_SECRET_ACCESS_KEY = os.environ.get("CLOUD_STORAGE_SECRET_KEY", "")
    AWS_STORAGE_BUCKET_NAME = os.environ.get("CLOUD_STORAGE_BUCKET", "")
    AWS_S3_REGION_NAME = os.environ.get("CLOUD_STORAGE_REGION", "")
    # Works with real AWS S3 or any S3-compatible provider (Cloudflare R2,
    # Backblaze B2, DigitalOcean Spaces, MinIO for self-hosting) by
    # pointing this at that provider's endpoint instead of leaving it
    # blank for AWS's default.
    AWS_S3_ENDPOINT_URL = os.environ.get("CLOUD_STORAGE_ENDPOINT_URL") or None
    # Files are private by default - served through signed, time-limited
    # URLs (django-storages generates these automatically) rather than a
    # public bucket, so a student can't view another student's document
    # just by guessing/incrementing a URL.
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600


# ============================================================================
# Cache
# ============================================================================
#
# Development:
#   LocMemCache
#
# Production can use Redis by supplying:
#
#   CACHE_BACKEND=django.core.cache.backends.redis.RedisCache
#   CACHE_LOCATION=redis://127.0.0.1:6379/1
# ============================================================================

_cache_backend = os.environ.get("CACHE_BACKEND", "")
_cache_location = os.environ.get("CACHE_LOCATION", "")

if not _cache_backend and not DEBUG and "test" not in sys.argv:
    # In production the login lockout and rate limits must be shared by every
    # gunicorn worker. Per-process memory would multiply the allowed attempts
    # by the number of workers, so default to a file cache all workers share.
    import tempfile
    _cache_backend = "django.core.cache.backends.filebased.FileBasedCache"
    _cache_location = _cache_location or str(Path(tempfile.gettempdir()) / "ums-cache")

CACHES = {
    "default": {
        "BACKEND": _cache_backend or "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": _cache_location or "ums-default-cache",
    }
}


# ============================================================================
# Background jobs - choose ONE scheduler (see DEPLOYMENT.md)
# ============================================================================
# The recurring jobs (automation, risk scoring, data-quality scan) can be
# driven four ways. Pick with SCHEDULER_MODE; every job is DB-locked, so even
# a mistaken double setup cannot run one twice at once.
#
#   celery    Redis + Celery worker + Celery Beat.   Best for a real server.
#   builtin   `manage.py run_scheduler` next to gunicorn. No Redis. Free tiers.
#   external  An outside pinger calls /internal/cron/ (needs CRON_SECRET).
#   off       Nothing is scheduled; use the Automation Center button.
#
# Default: "celery" if CELERY_BROKER_URL is set, otherwise "builtin".
# CELERY_BROKER_URL deliberately has NO default: a hidden localhost:6379
# fallback made "Celery configured" look true on machines with no Redis.

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# A blank value (as shipped in .env.example) means "choose automatically".
SCHEDULER_MODE = (
    os.environ.get("SCHEDULER_MODE", "").strip().lower()
    or ("celery" if CELERY_BROKER_URL else "builtin")
)
if SCHEDULER_MODE not in {"celery", "builtin", "external", "off"}:
    raise RuntimeError(
        "SCHEDULER_MODE must be one of: celery, builtin, external, off "
        f"(got {SCHEDULER_MODE!r})."
    )

# Shared secret for /internal/cron/ (>= 20 chars). Empty = endpoint disabled.
CRON_SECRET = os.environ.get("CRON_SECRET", "")

# Celery Beat triggers the SAME locked jobs the built-in scheduler runs.
CELERY_BEAT_SCHEDULE = {
    "ums-scheduler-tick": {
        "task": "core.tasks.scheduler_tick_task",
        "schedule": 15 * 60,   # every 15 min; each job only runs when due
    },
}


# ============================================================================
# AI Assistant
# ============================================================================

LLM_PROVIDER = os.environ.get(
    "LLM_PROVIDER",
    "local",
)

# Groq
GROQ_API_KEY = os.environ.get(
    "GROQ_API_KEY",
    "",
)

GROQ_MODEL = os.environ.get(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)


# Hugging Face
HUGGINGFACE_API_TOKEN = os.environ.get(
    "HUGGINGFACE_API_TOKEN",
    "",
)

HUGGINGFACE_MODEL = os.environ.get(
    "HUGGINGFACE_MODEL",
    "meta-llama/Llama-3.1-8B-Instruct",
)


# Google Gemini
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "",
)

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-2.5-flash",
)


# ============================================================================
# Field-level encryption
# ============================================================================

FIELD_ENCRYPTION_KEY = os.environ.get(
    "FIELD_ENCRYPTION_KEY",
    "",
)


# ============================================================================
# Email
# ============================================================================

# Email works on localhost AND on a live server through plain SMTP, so any
# provider with an SMTP option works (Gmail app-password, Brevo, Resend,
# SendGrid, Mailgun, Amazon SES, your university's own mail server ...).
#
#   SMTP_HOST=smtp.gmail.com  SMTP_PORT=587  SMTP_USER=..  SMTP_PASSWORD=..
#   SMTP_USE_TLS=1 (port 587)   or   SMTP_USE_SSL=1 (port 465)
#   DEFAULT_FROM_EMAIL="University Management System <you@example.com>"
#
# If SMTP_HOST is set the real SMTP backend is used automatically. If it is
# not set, emails are printed to the terminal (development only) and the
# Email Center page reports that they were not delivered.
EMAIL_HOST = os.environ.get("SMTP_HOST", os.environ.get("EMAIL_HOST", ""))
EMAIL_PORT = env_int("SMTP_PORT", 587)
EMAIL_HOST_USER = os.environ.get("SMTP_USER", os.environ.get("EMAIL_HOST_USER", ""))
EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORD", os.environ.get("EMAIL_HOST_PASSWORD", ""))
EMAIL_USE_SSL = env_bool("SMTP_USE_SSL", False)
EMAIL_USE_TLS = False if EMAIL_USE_SSL else env_bool("SMTP_USE_TLS", True)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 15)
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "University Management System <no-reply@ums.local>")
SERVER_EMAIL = os.environ.get("SERVER_EMAIL", DEFAULT_FROM_EMAIL)


# ============================================================================
# Login throttling
# ============================================================================

LOGIN_THROTTLE_MAX_ATTEMPTS = env_int(
    "LOGIN_THROTTLE_MAX_ATTEMPTS",
    5,
)

LOGIN_THROTTLE_WINDOW_SECONDS = env_int(
    "LOGIN_THROTTLE_WINDOW_SECONDS",
    300,
)


# ============================================================================
# WebAuthn
# ============================================================================

# Local:
#   WEBAUTHN_RP_ID=localhost
#   WEBAUTHN_ORIGIN=http://localhost:8000
#
# Production:
#   WEBAUTHN_RP_ID=your-domain.com
#   WEBAUTHN_ORIGIN=https://your-domain.com

WEBAUTHN_RP_ID = os.environ.get(
    "WEBAUTHN_RP_ID",
    "localhost",
)

WEBAUTHN_RP_NAME = os.environ.get(
    "WEBAUTHN_RP_NAME",
    "University Management System",
)

WEBAUTHN_ORIGIN = os.environ.get(
    "WEBAUTHN_ORIGIN",
    "http://localhost:8000",
)


# ============================================================================
# Upload limits
# ============================================================================

DATA_UPLOAD_MAX_MEMORY_SIZE = env_int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE",
    10 * 1024 * 1024,
)

FILE_UPLOAD_MAX_MEMORY_SIZE = env_int(
    "FILE_UPLOAD_MAX_MEMORY_SIZE",
    10 * 1024 * 1024,
)


# ============================================================================
# CSRF trusted origins
# ============================================================================

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
)
for _h in _PLATFORM_HOSTS:
    if f"https://{_h}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(f"https://{_h}")


# ============================================================================
# Security hardening
# ============================================================================

# Always enabled.
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_HTTPONLY = True

# Must remain False because browser-side JavaScript may need to read
# the CSRF cookie to construct the X-CSRFToken header.
CSRF_COOKIE_HTTPONLY = False

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

X_FRAME_OPTIONS = "DENY"

SECURE_REFERRER_POLICY = "same-origin"

SESSION_COOKIE_AGE = env_int(
    "SESSION_COOKIE_AGE",
    60 * 60 * 8,
)


# ----------------------------------------------------------------------------
# HTTPS / secure cookies
# ----------------------------------------------------------------------------

SECURE_COOKIES = env_bool(
    "SECURE_COOKIES",
    not DEBUG,
)

SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_SECURE = SECURE_COOKIES


# ----------------------------------------------------------------------------
# SSL redirect
# ----------------------------------------------------------------------------

SECURE_SSL_REDIRECT = env_bool(
    "SECURE_SSL_REDIRECT",
    False,
)
# Platform/Docker health probes arrive over plain HTTP from inside the
# network; redirecting them to HTTPS makes a healthy app look dead.
SECURE_REDIRECT_EXEMPT = [r"^health/$", r"^ready/$"]


# ----------------------------------------------------------------------------
# Reverse proxy HTTPS detection
# ----------------------------------------------------------------------------

SECURE_PROXY_SSL_HEADER = None

if env_bool("SECURE_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )


# ----------------------------------------------------------------------------
# HSTS
# ----------------------------------------------------------------------------
#
# HSTS must NEVER be enabled casually on a local HTTP server.
#
# Production .env:
#
#   SECURE_SSL_REDIRECT=1
#   SECURE_HSTS_SECONDS=31536000
#
# Only enable this after confirming the complete production site works
# through HTTPS.
# ----------------------------------------------------------------------------

if DEBUG:

    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

else:

    _hsts_seconds = env_int(
        "SECURE_HSTS_SECONDS",
        0,
    )

    SECURE_HSTS_SECONDS = _hsts_seconds

    SECURE_HSTS_INCLUDE_SUBDOMAINS = (
        _hsts_seconds > 0
    )

    SECURE_HSTS_PRELOAD = (
        _hsts_seconds > 0
    )


# ============================================================================
# Cross-origin security
# ============================================================================

SECURE_CROSS_ORIGIN_OPENER_POLICY = os.environ.get(
    "SECURE_CROSS_ORIGIN_OPENER_POLICY",
    "same-origin",
)


# ============================================================================
# Database connection lifetime
# ============================================================================

CONN_MAX_AGE = env_int(
    "DB_CONN_MAX_AGE",
    60,
)


# ============================================================================
# Default primary key
# ============================================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ============================================================================
# Logging
# ============================================================================
#
# Warnings/errors are shown in the console and persisted to:
#
#   logs/errors.log
#
# The file rotates at 5 MB and keeps 5 backups.
# ============================================================================

LOGS_DIR = BASE_DIR / "logs"

try:
    LOGS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    _file_logging_available = True

except OSError:
    _file_logging_available = False


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": (
                "{asctime} {levelname} "
                "{name} - {message}"
            ),
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },

        **(
            {
                "error_file": {
                    "class": (
                        "logging.handlers."
                        "RotatingFileHandler"
                    ),
                    "filename": LOGS_DIR / "errors.log",
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "formatter": "verbose",
                    "level": "WARNING",
                }
            }
            if _file_logging_available
            else {}
        ),
    },

    "root": {
        "handlers": (
            ["console", "error_file"]
            if _file_logging_available
            else ["console"]
        ),
        "level": "WARNING",
    },

    "loggers": {
        "ums.errors": {
            "handlers": (
                ["console", "error_file"]
                if _file_logging_available
                else ["console"]
            ),
            "level": "ERROR",
            "propagate": False,
        },

        "django.request": {
            "handlers": (
                ["console", "error_file"]
                if _file_logging_available
                else ["console"]
            ),
            "level": "ERROR",
            "propagate": False,
        },
    },
}


# ============================================================================
# Authentication redirects
# ============================================================================

LOGIN_URL = "login"

LOGIN_REDIRECT_URL = "dashboard"

LOGOUT_REDIRECT_URL = "index"

# Safepay credentials (server-side only; never expose to templates).
SAFEPAY_API_KEY = os.environ.get('SAFEPAY_API_KEY', '')
SAFEPAY_V1_SECRET = os.environ.get('SAFEPAY_V1_SECRET', '') or os.environ.get('SAFEPAY_SECRET_KEY', '')
SAFEPAY_SECRET_KEY = os.environ.get('SAFEPAY_SECRET_KEY', '')
SAFEPAY_WEBHOOK_SECRET = os.environ.get('SAFEPAY_WEBHOOK_SECRET', '')
SAFEPAY_ENVIRONMENT = os.environ.get('SAFEPAY_ENVIRONMENT', 'sandbox')
