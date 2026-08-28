"""Laurio backend 설정.

환경별 차이는 전부 환경변수로 주입한다. dev/staging/prod compose 분리는 티켓 22에서 다룬다.
"""

import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 호스트에서 돌릴 때 backend/.env 를 읽는다. override=False 라서 compose·CI 가 주입한
# 실제 환경변수가 항상 파일을 이긴다.
load_dotenv(BASE_DIR / ".env", override=False)


def _env(name: str, default: str) -> str:
    """빈 문자열도 '미설정'으로 본다.

    os.environ.get(name, default) 은 `FOO=` 일 때 기본값이 아니라 '' 를 돌려준다.
    .env 템플릿의 빈 항목이 그대로 설정으로 들어오면 부팅이 깨지므로 여기서 걸러낸다.
    """
    return os.environ.get(name) or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = _env_bool("DJANGO_DEBUG", True)

_secret_key = os.environ.get("DJANGO_SECRET_KEY") or ""
if not _secret_key:
    if not DEBUG:
        # 저장소에 공개된 개발용 키로 프로덕션이 조용히 뜨는 것보다 못 뜨는 편이 낫다.
        raise ImproperlyConfigured(
            "DJANGO_DEBUG=false 인데 DJANGO_SECRET_KEY 가 비어 있다. "
            "배포 환경에서는 반드시 주입해야 한다."
        )
    _secret_key = "dev-only-insecure-key"
SECRET_KEY = _secret_key

ALLOWED_HOSTS = [h for h in _env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "verification",
    "contests",
    "ledger",
]

MIDDLEWARE = [
    # 가장 바깥쪽에 둔다 — CommonMiddleware의 APPEND_SLASH 301, CsrfViewMiddleware의
    # 403 등 체인 중간에서 반환되는 응답도 이 미들웨어를 반드시 한 번 더 거쳐 나가므로
    # CSP 헤더가 모든 응답에 실제로 붙는다(ADR-0012 — 세 보완책 중 하나라도 빠지면
    # 무효).
    "accounts.middleware.ContentSecurityPolicyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "accounts.middleware.JWTAuthenticationMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
ASGI_APPLICATION = "config.asgi.application"

# 컨테이너 안에서는 compose 가 POSTGRES_* 를 전부 주입한다(HOST=db, PORT=5432).
# 아래 기본값은 호스트에서 `uv run pytest` 를 돌릴 때만 쓰이므로, dev compose 가
# 실제로 공개한 포트(LAURIO_DB_PORT)를 그대로 따라간다. 다른 프로젝트의 5432 에
# 잘못 붙는 사고를 막기 위함이다.
_DEV_DB_PORT = _env("LAURIO_DB_PORT", "55432")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _env("POSTGRES_DB", "laurio"),
        "USER": _env("POSTGRES_USER", "laurio"),
        "PASSWORD": _env("POSTGRES_PASSWORD", "laurio"),
        "HOST": _env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": _env("POSTGRES_PORT", _DEV_DB_PORT),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication (ADR-0012, ADR-0013) ---------------------------------
# 액세스 토큰은 짧게, 리프레시 토큰은 회전시킨다. 서명 키는 SECRET_KEY와 분리해 둔다 —
# 세션 쿠키 서명과 JWT 서명이 같은 키를 공유하지 않게 하기 위함이다.
JWT_SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY") or (
    "dev-only-insecure-jwt-signing-key-not-for-prod" if DEBUG else ""
)
if not JWT_SIGNING_KEY and not DEBUG:
    raise ImproperlyConfigured(
        "DJANGO_DEBUG=false 인데 JWT_SIGNING_KEY 가 비어 있다. 배포 환경에서는 반드시 주입해야 한다."
    )
ACCESS_TOKEN_TTL = timedelta(minutes=int(_env("ACCESS_TOKEN_TTL_MINUTES", "5")))
REFRESH_TOKEN_TTL = timedelta(days=int(_env("REFRESH_TOKEN_TTL_DAYS", "14")))

# 소셜 로그인 어댑터 (ADR-0007). dev/test는 fake — 실제 카카오·GitHub·구글 API를
# 부르지 않고 결정적으로 동작한다. prod는 SOCIAL_AUTH_MODE=real 로 실제 어댑터를 쓴다.
SOCIAL_AUTH_MODE = _env("SOCIAL_AUTH_MODE", "fake" if DEBUG else "real")

# --- Verification (ADR-0011, ADR-0007) ------------------------------------
# 본인확인 어댑터도 같은 원칙: dev/test는 fake로 바인딩된다.
VERIFICATION_ADAPTER_MODE = _env("VERIFICATION_ADAPTER_MODE", "fake" if DEBUG else "real")

# 실명·생년월일·CI/DI를 저장 시 암호화하는 대칭키(Fernet). SECRET_KEY와 마찬가지로
# 배포 환경에서는 반드시 주입해야 하고, dev는 저장소에 공개된 고정 키로 대체한다.
_verification_key = os.environ.get("VERIFICATION_ENCRYPTION_KEY") or ""
if not _verification_key:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_DEBUG=false 인데 VERIFICATION_ENCRYPTION_KEY 가 비어 있다. "
            "배포 환경에서는 반드시 주입해야 한다."
        )
    _verification_key = "A0crfksMrBmbSY37jIyOwcPRFpK9rc_eIaNnL89lIfo="
VERIFICATION_ENCRYPTION_KEY = _verification_key
