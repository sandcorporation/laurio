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
    # 모델은 없다(#8/#10이 붙을 때까지). STORAGE_BACKEND/STORAGE_TARGET_RESOLVER
    # 오탈자를 요청 시점 500 대신 `manage.py check`/부팅 시점에 잡기 위해서만 등록한다.
    "storage",
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

# 스토리지 어댑터 (ADR-0005, ADR-0007): "fake"가 기본값이라 아무것도 설정하지 않아도
# 테스트·CI는 MinIO 없이 돈다. dev compose가 backend 컨테이너에만 STORAGE_BACKEND=s3
# 를 주입해 MinIO로 바인딩한다(docker/compose.dev.yaml). staging/prod는 같은 "s3"
# 백엔드가 실제 S3·OCI 엔드포인트를 가리키도록 환경변수만 바꾼다.
STORAGE_BACKEND = _env("STORAGE_BACKEND", "fake")

# DJANGO_SECRET_KEY 가드(위)와 같은 이유다. STORAGE_BACKEND 를 잊고 배포하면
# FakeStorageAdapter가 200과 함께 https://fake-storage.test/... 를 돌려주고, 업로드도
# 다운로드도 겉보기엔 성공한 채 파일만 소리 없이 사라진다. 배포에서는 아예 못 뜨게 막는다.
if not DEBUG and STORAGE_BACKEND == "fake":
    raise ImproperlyConfigured(
        "DJANGO_DEBUG=false 인데 STORAGE_BACKEND 가 fake 다. presigned URL이 200으로 "
        "발급되면서 파일이 소리 없이 유실된다. 배포 환경에서는 STORAGE_BACKEND=s3 를 "
        "반드시 설정해야 한다."
    )

STORAGE_BUCKET = _env("STORAGE_BUCKET", "laurio-dev")
# 기본값은 호스트에서 직접 돌릴 때를 가정한다(LAURIO_MINIO_PORT). 컨테이너 안에서는
# compose가 STORAGE_ENDPOINT_URL=http://minio:9000 을 직접 주입한다.
STORAGE_ENDPOINT_URL = _env("STORAGE_ENDPOINT_URL", "http://127.0.0.1:19000")
# 비워두면 boto3 기본 자격증명 체인(IAM role·instance profile 등)을 그대로 쓴다.
# dev(MinIO)는 정적 키가 필수라 compose·.env.example이 명시적으로 채워 넣는다.
# 절대 기본값을 두지 않는다 — 기본값이 있으면 S3StorageAdapter가 항상 그것부터
# boto3에 넘겨버려서 운영 환경의 자격증명 체인이 쓰일 일이 없어진다.
STORAGE_ACCESS_KEY = _env("STORAGE_ACCESS_KEY", "")
STORAGE_SECRET_KEY = _env("STORAGE_SECRET_KEY", "")
STORAGE_REGION = _env("STORAGE_REGION", "us-east-1")

# 업로드는 수백 MB 파일을 올릴 시간을 준다. 다운로드는 짧게 끊어 재사용을 막는다.
STORAGE_UPLOAD_URL_TTL_SECONDS = int(_env("STORAGE_UPLOAD_URL_TTL_SECONDS", "900"))
STORAGE_DOWNLOAD_URL_TTL_SECONDS = int(_env("STORAGE_DOWNLOAD_URL_TTL_SECONDS", "300"))

# target_ref -> 소유자·공개상태 판정 훅(storage.policy.TargetStateResolver).
# 비어 있으면 storage.policy.DenyUnknownTargetResolver 로 fail-closed 한다.
# #8(Submission)·#10(Contest)·#14(Handover)가 실제 구현으로 갈아끼운다.
STORAGE_TARGET_RESOLVER = _env("STORAGE_TARGET_RESOLVER", "")

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
