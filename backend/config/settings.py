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

# DEBUG는 Django 자체의 동작(에러 페이지, 정적 파일 서빙)만 결정한다. "이것이 진짜
# 운영 배포인가"라는 별개의 질문에는 답하지 않는다 — CI가 그 증거다: DEBUG=false로
# manage.py check 가 실제 배포와 같은 코드 경로를 타는지 확인하고 싶지만, 실제
# 운영 배포는 아니라서 Fake 어댑터로 돌아야 한다. 이 둘을 같은 스위치(DEBUG)로
# 묶으면 "DEBUG=false인데 fake는 위험하다"는 안전장치가 CI에서도 그대로 터진다.
# 그래서 "정말 운영 배포인가"는 별도 값으로 뗀다 — 미설정(dev·CI 포함)은 항상
# False이고, staging/prod compose(#23)만 명시적으로 production을 준다.
LAURIO_DEPLOYMENT_TARGET = _env("LAURIO_DEPLOYMENT_TARGET", "development")
IS_PRODUCTION_DEPLOYMENT = LAURIO_DEPLOYMENT_TARGET == "production"

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
    "payments",
    "core",
    "notifications",
    # 모델은 없다(#8/#10이 붙을 때까지). STORAGE_BACKEND/STORAGE_TARGET_RESOLVER
    # 오탈자를 요청 시점 500 대신 `manage.py check`/부팅 시점에 잡기 위해서만 등록한다.
    "storage",
    "submissions",
    "scoring",
    "awards",
    "handovers",
    "payouts",
    "distributions",
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

# 스토리지 어댑터 (ADR-0005, ADR-0007): "fake"가 기본값이라 아무것도 설정하지 않아도
# 테스트·CI는 MinIO 없이 돈다. dev compose가 backend 컨테이너에만 STORAGE_BACKEND=s3
# 를 주입해 MinIO로 바인딩한다(docker/compose.dev.yaml). staging/prod는 같은 "s3"
# 백엔드가 실제 S3·OCI 엔드포인트를 가리키도록 환경변수만 바꾼다.
STORAGE_BACKEND = _env("STORAGE_BACKEND", "fake")

# DJANGO_SECRET_KEY 가드(위)와 같은 이유다. STORAGE_BACKEND 를 잊고 배포하면
# FakeStorageAdapter가 200과 함께 https://fake-storage.test/... 를 돌려주고, 업로드도
# 다운로드도 겉보기엔 성공한 채 파일만 소리 없이 사라진다. 실제 운영 배포에서는 아예
# 못 뜨게 막는다 — DEBUG가 아니라 LAURIO_DEPLOYMENT_TARGET을 본다. CI는 DEBUG=false로
# 돌면서도 실제 배포가 아니므로(위 설명) 이 가드에 걸리지 않고 fake로 테스트를 돌릴 수
# 있어야 한다.
if IS_PRODUCTION_DEPLOYMENT and STORAGE_BACKEND == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 STORAGE_BACKEND 가 fake 다. presigned "
        "URL이 200으로 발급되면서 파일이 소리 없이 유실된다. 운영 배포에서는 "
        "STORAGE_BACKEND=s3 를 반드시 설정해야 한다."
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
# #10이 Submission의 소스·데모 가시성 판정을 여기 꽂았다(ADR-0005, ADR-0014).
# 비어 있으면 storage.policy.DenyUnknownTargetResolver 로 fail-closed 한다 — 테스트가
# 이 기본값을 override_settings 로 fake 리졸버로 바꿔치기할 수 있는 이유가 이것이다.
STORAGE_TARGET_RESOLVER = _env(
    "STORAGE_TARGET_RESOLVER", "submissions.resolvers.SubmissionTargetStateResolver"
)

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

# 소셜 로그인 어댑터 (ADR-0007). STORAGE_BACKEND와 같은 원칙: 기본값은 DEBUG와
# 무관하게 항상 fake다 — "어떤 구현체를 쓸지"와 "이게 진짜 운영 배포인지"는 다른
# 질문이기 때문이다(위 LAURIO_DEPLOYMENT_TARGET 설명 참고). 실제 카카오·GitHub·구글
# API를 부르려면 SOCIAL_AUTH_MODE=real 을 명시해야 한다 — 운영 배포(#23)가 그렇게 한다.
SOCIAL_AUTH_MODE = _env("SOCIAL_AUTH_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and SOCIAL_AUTH_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 SOCIAL_AUTH_MODE 가 fake 다. "
        "운영 배포에서는 SOCIAL_AUTH_MODE=real 을 반드시 설정해야 한다."
    )

# --- Verification (ADR-0011, ADR-0007) ------------------------------------
# 본인확인 어댑터도 같은 원칙: 기본값은 항상 fake이고, 운영 배포만 real을 명시한다.
VERIFICATION_ADAPTER_MODE = _env("VERIFICATION_ADAPTER_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and VERIFICATION_ADAPTER_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 VERIFICATION_ADAPTER_MODE 가 fake 다. "
        "운영 배포에서는 VERIFICATION_ADAPTER_MODE=real 을 반드시 설정해야 한다."
    )

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

# --- 결제 · Escrow 예치 (#9, ADR-0007) --------------------------------------
# PG 어댑터도 같은 원칙: 기본값은 항상 Fake PG다 — 웹훅 재전송·타임아웃·순서 뒤바뀜을
# 네트워크 없이 결정적으로 주입할 수 있다. 운영 배포만 PAYMENT_ADAPTER_MODE=real 로
# 실제 토스 연동을 명시한다(#23의 범위).
PAYMENT_ADAPTER_MODE = _env("PAYMENT_ADAPTER_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and PAYMENT_ADAPTER_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 PAYMENT_ADAPTER_MODE 가 fake 다. 운영 "
        "배포에서는 PAYMENT_ADAPTER_MODE=real 을 반드시 설정해야 한다."
    )

# Sponsor가 Contest를 개최할 때 Prize와 별도로 결제하는 개최 등록비(원 단위 정수,
# ADR-0004). 배포 없이 조정할 수 있는 DeliverableType.minimum_prize와 달리 이건
# 아직 DB 조정 대상이 아니다 — 이 티켓 범위에서는 전역 고정값이면 충분하다.
CONTEST_LISTING_FEE = int(_env("CONTEST_LISTING_FEE", "50000"))

# --- 심사기간 · Award · 유료 연장 (#13, ADR-0003) --------------------------------
# 마감 후 기본 심사기간. CLOSED 전이가 일어나는 조건부 UPDATE 안에서
# deadline_at + 이 값으로 judging_ends_at을 채운다.
JUDGING_PERIOD_DAYS = int(_env("JUDGING_PERIOD_DAYS", "7"))
# 유료 연장 1회가 심사기간을 늘리는 길이. judging_ends_at 컬럼에만 더해진다 —
# 예약된 스케줄러 규칙은 건드리지 않는다(ADR-0003).
JUDGING_EXTENSION_DAYS = int(_env("JUDGING_EXTENSION_DAYS", "7"))
# 연장 1회당 결제 금액(원 단위 정수, ADR-0004). CONTEST_LISTING_FEE와 같은 성격의
# 전역 고정값이다 — 아직 DB 조정 대상이 아니다.
CONTEST_EXTENSION_FEE = int(_env("CONTEST_EXTENSION_FEE", "30000"))

# 웹훅 서명 검증 비밀키 (#9 리뷰 지적 2). `/api/payments/webhook`은 인증 없는
# 내부 엔드포인트지만, 서명이 없으면 누구든 자신의 order_id로 "paid"를 위조해
# 돈이 오가지 않은 결제를 원장에 예치 분개로 남기고 Contest를 공개시킬 수 있다.
# dev는 저장소에 공개된 고정 키로 Fake PG와 검증 양쪽을 동작시킨다.
_payment_webhook_secret = os.environ.get("PAYMENT_WEBHOOK_SECRET") or ""
if not _payment_webhook_secret:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_DEBUG=false 인데 PAYMENT_WEBHOOK_SECRET 이 비어 있다. "
            "배포 환경에서는 반드시 주입해야 한다."
        )
    _payment_webhook_secret = "dev-only-insecure-fake-pg-webhook-secret"
PAYMENT_WEBHOOK_SECRET = _payment_webhook_secret

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
# FAILING 과 달리 이건 어댑터가 실패 "응답"이 아니라 예외로 죽는(타임아웃/5xx) 상황을
# 흉내낸다 — 실제 벤더 장애에서 더 흔한 경우이고, 이걸 잡아 다음 채널로 넘어가는지가
# 이 티켓의 핵심 방어선이다.
NOTIFICATION_FAKE_RAISING_CHANNELS = [
    c for c in _env("NOTIFICATION_FAKE_RAISING_CHANNELS", "").split(",") if c
]

# --- AI 채점 어댑터 (#12, ADR-0006, ADR-0007, ADR-0014) -----------------------------
#
# PAYMENT_ADAPTER_MODE·STORAGE_BACKEND와 같은 원칙: 기본값은 항상 fake다. dev/CI는
# 네트워크 없이 결정적으로 채점 플로우 전체를 돈다. 운영 배포만 LLM_ADAPTER_MODE에
# 실제 어댑터의 dotted path(또는 향후 등록될 별칭)를 명시한다.
LLM_ADAPTER_MODE = _env("LLM_ADAPTER_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and LLM_ADAPTER_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 LLM_ADAPTER_MODE 가 fake 다. Score가 "
        "실제 채점 없이 만들어지면 Distribution 대상 판정이 통째로 무효가 된다. 운영 "
        "배포에서는 실제 LLM 어댑터를 반드시 설정해야 한다."
    )

# 테스트가 override_settings로 특정 submission_id의 채점 실패를 흉내낼 때 쓴다
# (NOTIFICATION_FAKE_RAISING_CHANNELS와 같은 원칙 — 어댑터가 예외로 죽는 경로를
# 재현해 재시도 로직을 검증한다).
LLM_FAKE_RAISING_SUBMISSION_IDS = [
    int(x) for x in _env("LLM_FAKE_RAISING_SUBMISSION_IDS", "").split(",") if x
]

# --- AI grill — Sponsor Requirement 체크리스트 대화형 생성 어댑터 (#20, ADR-0007) ---
#
# LLM_ADAPTER_MODE와 같은 원칙(기본값은 항상 fake)을 별개의 설정 키로 둔다 —
# NOTIFICATION_ALIMTALK_ADAPTER/NOTIFICATION_SMS_ADAPTER/NOTIFICATION_LMS_ADAPTER가
# "통지"라는 한 개념 아래 채널별로 갈아끼우는 것과 같은 구조로, "LLM"이라는 한
# 개념 아래 용도별(채점/대화)로 갈아끼운다. 두 번째 벤더 SDK·HTTP 클라이언트를
# 새로 만들지 않는다 — `core.adapters.resolve_adapter`로 선택 로직 자체를
# `scoring.adapters.get_adapter`와 공유한다.
LLM_REQUIREMENT_CHAT_ADAPTER_MODE = _env("LLM_REQUIREMENT_CHAT_ADAPTER_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and LLM_REQUIREMENT_CHAT_ADAPTER_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 LLM_REQUIREMENT_CHAT_ADAPTER_MODE 가 "
        "fake 다. 운영 배포에서는 실제 LLM 어댑터를 반드시 설정해야 한다."
    )

# 테스트가 override_settings로 특정 contest_id의 대화 응답 실패를 흉내낼 때 쓴다
# (LLM_FAKE_RAISING_SUBMISSION_IDS와 같은 원칙).
LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS = [
    int(x) for x in _env("LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS", "").split(",") if x
]

# --- Handover · Escrow 해제 (#14, ADR-0003/0004/0005/0014) --------------------------
#
# Award 후 Sponsor가 인수를 확인하지 않아도 이 기간이 지나면 스케줄러(내부 스캔
# 엔드포인트)가 Escrow를 해제한다 — Sponsor의 침묵이 Developer를 인질로 잡지 못한다.
HANDOVER_ACCEPTANCE_PERIOD_DAYS = int(_env("HANDOVER_ACCEPTANCE_PERIOD_DAYS", "14"))

# --- Payout 실행 (#15, ADR-0004/0008) -------------------------------------------------
#
# 토스 지급대행 어댑터도 PAYMENT_ADAPTER_MODE와 같은 원칙: 기본값은 항상 Fake다.
PAYOUT_ADAPTER_MODE = _env("PAYOUT_ADAPTER_MODE", "fake")
if IS_PRODUCTION_DEPLOYMENT and PAYOUT_ADAPTER_MODE == "fake":
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 PAYOUT_ADAPTER_MODE 가 fake 다. 운영 "
        "배포에서는 PAYOUT_ADAPTER_MODE=real 을 반드시 설정해야 한다."
    )

# payout.changed 웹훅 서명 비밀키. payments.webhook_security의 서명 스킴을 그대로
# 재사용한다(HMAC-SHA256) — 벤더가 다를 뿐 "서명 없는 웹훅으로 원장이 위조될 수
# 있다"는 위협은 동일하다(#9 리뷰 지적 2와 같은 이유).
_payout_webhook_secret = os.environ.get("PAYOUT_WEBHOOK_SECRET") or ""
if not _payout_webhook_secret:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_DEBUG=false 인데 PAYOUT_WEBHOOK_SECRET 이 비어 있다. "
            "배포 환경에서는 반드시 주입해야 한다."
        )
    _payout_webhook_secret = "dev-only-insecure-fake-toss-payout-webhook-secret"
PAYOUT_WEBHOOK_SECRET = _payout_webhook_secret

# 플랫폼 수수료·원천징수 공제율. 1/10000(bp) 단위 정수로 다뤄 float 오차 없이
# 원 단위 정수 금액을 계산한다(ADR-0004: "금액은 원 단위 정수로 다룬다"). 원천징수는
# 기타소득 원천징수의 상식적인 근사치(3.3%)를 기본값으로 둔다 — 실제 세율은 세무
# 정책(#15 범위 밖)이 정한다.
PAYOUT_PLATFORM_FEE_BPS = int(_env("PAYOUT_PLATFORM_FEE_BPS", "1000"))
PAYOUT_WITHHOLDING_TAX_BPS = int(_env("PAYOUT_WITHHOLDING_TAX_BPS", "330"))

# --- Distribution (#16, ADR-0003/0004/0006) -------------------------------------------
#
# 심사기간 종료(JUDGING_ENDED, judging_ends_at) 후 이 기간 동안 아무도 Award하지
# 않으면 스케줄러(내부 스캔 엔드포인트)가 Score 컷라인을 통과한 Submission들에게
# Prize를 1/N로 배분한다 — HANDOVER_ACCEPTANCE_PERIOD_DAYS와 같은 "Sponsor의
# 침묵이 Developer를 인질로 잡지 못한다" 원칙의 무응답 버전이다(REQUEST.md).
DISTRIBUTION_WAIT_DAYS = int(_env("DISTRIBUTION_WAIT_DAYS", "14"))
