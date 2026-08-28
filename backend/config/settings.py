"""Laurio backend 설정.

환경별 차이는 전부 환경변수로 주입한다. dev/staging/prod compose 분리는 티켓 22에서 다룬다.
"""

import os
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
    "core",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

# --- 내부 인증 (티켓 02, ADR-0003) --------------------------------------------------
#
# Celery beat 와 (사용자 인증이 아직 없는) 내부 전용 엔드포인트가 쓰는 고정 토큰이다.
# 소셜 로그인(Authentication)과는 무관하다. DEBUG 에서만 개발용 기본값을 준다 — prod
# 에서 비어 있으면 부팅을 거부해 "토큰 없이도 열려 있는 내부 엔드포인트"를 막는다.
INTERNAL_API_TOKEN = _env("INTERNAL_API_TOKEN", "dev-only-internal-token" if DEBUG else "")
if not DEBUG and not INTERNAL_API_TOKEN:
    raise ImproperlyConfigured(
        "DJANGO_DEBUG=false 인데 INTERNAL_API_TOKEN 이 비어 있다. "
        "내부 엔드포인트가 토큰 없이 열리는 사고를 막기 위해 배포 환경에서는 반드시 주입해야 한다."
    )

# Celery 태스크가 스케줄러 틱 엔드포인트를 호출할 때 쓰는 베이스 URL. 컨테이너 안에서는
# backend 서비스 자기 자신을 가리키면 된다.
INTERNAL_API_BASE_URL = _env("INTERNAL_API_BASE_URL", "http://127.0.0.1:8000")

# --- Celery (티켓 02, ADR-0003) -----------------------------------------------------
#
# 브로커는 아직 dev compose 에 없다. 설정만 여기 있고, 실제로 워커·beat 를 띄우는 것은
# 이 티켓 범위 밖이다(공유 인프라에 새 컨테이너/포트를 추가하지 않는다).
CELERY_BROKER_URL = _env("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = _env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", False)

# --- Notification 어댑터 (티켓 17, ADR-0007 / ADR-0009) ------------------------------
#
# dev/test 는 전부 Fake 구현체에 바인딩된다. 실제 카카오·SMS 벤더 연동은 이 티켓
# 범위 밖이다. 콤마로 나열한 채널은 Fake 어댑터가 "실패"를 흉내내도록 만든다 — 테스트가
# 알림톡 실패 → SMS/LMS 대체발송 경로를 override_settings 로 재현할 때 쓴다.
NOTIFICATION_ALIMTALK_ADAPTER = _env(
    "NOTIFICATION_ALIMTALK_ADAPTER", "notifications.adapters.FakeAlimtalkAdapter"
)
NOTIFICATION_SMS_ADAPTER = _env("NOTIFICATION_SMS_ADAPTER", "notifications.adapters.FakeSmsAdapter")
NOTIFICATION_LMS_ADAPTER = _env("NOTIFICATION_LMS_ADAPTER", "notifications.adapters.FakeLmsAdapter")
NOTIFICATION_FAKE_FAILING_CHANNELS = [
    c for c in _env("NOTIFICATION_FAKE_FAILING_CHANNELS", "").split(",") if c
]
