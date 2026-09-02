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


def _is_fake_adapter_binding(value: str) -> bool:
    """"fake" 별칭이거나, dotted path가 가리키는 클래스명이 Fake로 시작하면 True.

    코디네이터 리뷰 지적: 이 가드는 원래 `value == "fake"`만 봤다. 그런데
    STORAGE_BACKEND는 "fake"가 별칭 dict(storage.adapters._BACKENDS)를 거쳐 실제
    dotted path로 풀리고, LLM_ADAPTER_MODE/LLM_REQUIREMENT_CHAT_ADAPTER_MODE는
    "fake"가 아니면 뭐든 dotted path로 그대로 import한다
    (core.adapters.resolve_adapter) — 즉 운영 배포에서
    `STORAGE_BACKEND=storage.adapters.fake.FakeStorageAdapter`처럼 "fake"라는
    별칭 문자열만 피해 가면 실제로는 여전히 Fake 어댑터가 조용히 바인딩된다.
    그래서 별칭 문자열이 아니라 "가리키는 클래스가 Fake인가"를 직접 판정한다.
    """

    if value == "fake":
        return True
    class_name = value.rsplit(".", 1)[-1]
    return class_name.startswith("Fake")


DEBUG = _env_bool("DJANGO_DEBUG", True)

# DEBUG는 Django 자체의 동작(에러 페이지, 정적 파일 서빙)만 결정한다. "이것이 진짜
# 운영 배포인가"라는 별개의 질문에는 답하지 않는다 — CI가 그 증거다: DEBUG=false로
# manage.py check 가 실제 배포와 같은 코드 경로를 타는지 확인하고 싶지만, 실제
# 운영 배포는 아니라서 Fake 어댑터로 돌아야 한다. 이 둘을 같은 스위치(DEBUG)로
# 묶으면 "DEBUG=false인데 fake는 위험하다"는 안전장치가 CI에서도 그대로 터진다.
# 그래서 "정말 운영 배포인가"는 별도 값으로 뗀다 — 미설정(dev·CI 포함)은 항상
# False이고, staging/prod compose(#23)만 명시적으로 production을 준다.
#
# staging은 "production"이 아니지만(TLS 종단·시크릿 강도 요구사항이 다르다) "fake
# 어댑터가 섞이면 안 된다"는 요구사항은 production과 동일하다 — ADR-0007이 그리는
# 3단계 바인딩(dev=Fake, staging=토스 샌드박스, prod=토스 실물)에서 staging도 이미
# 실제 연동 규약을 검증하는 자리이기 때문이다. 그래서 어댑터 fake 가드는
# IS_PRODUCTION_DEPLOYMENT가 아니라 이 둘을 합친 IS_DEPLOYED_ENVIRONMENT를 본다 —
# "TLS·시크릿 강도처럼 production에만 해당하는 하드닝"과 "fake 금지처럼 배포된 모든
# 환경에 해당하는 안전장치"는 서로 다른 질문이라 별도 플래그로 뗀다.
_VALID_DEPLOYMENT_TARGETS = {"development", "staging", "production"}
LAURIO_DEPLOYMENT_TARGET = _env("LAURIO_DEPLOYMENT_TARGET", "development")
# 코디네이터 리뷰 지적: 이 값이 검증되지 않으면 "prod", "Production", 오타 하나가
# 조용히 "development"로도, "staging"/"production" 어느 쪽으로도 매치하지 않는
# 상태로 흘러 아래 모든 가드(fake 어댑터 거부·SECRET_KEY 강도·DEBUG 거부·TLS
# 하드닝)를 통째로 무력화한다 — 이 티켓의 목적 자체가 "조용히 통과하는 대신 크게
# 실패한다"이므로, 허용된 세 값이 아니면 그 자리에서 바로 죽는다.
if LAURIO_DEPLOYMENT_TARGET not in _VALID_DEPLOYMENT_TARGETS:
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 는 유효하지 않다. "
        f"{sorted(_VALID_DEPLOYMENT_TARGETS)} 중 하나여야 한다 — 오타 하나가 이 값 아래의 "
        "모든 배포 가드(fake 어댑터 거부, SECRET_KEY 강도, DEBUG 거부, TLS 하드닝)를 "
        "전부 무력화하므로 미설정 기본값(development)으로 조용히 흘려보내지 않는다."
    )
IS_PRODUCTION_DEPLOYMENT = LAURIO_DEPLOYMENT_TARGET == "production"
IS_DEPLOYED_ENVIRONMENT = LAURIO_DEPLOYMENT_TARGET in {"staging", "production"}

# production인데 DEBUG=true로 뜨면 에러 페이지가 스택 트레이스·환경변수·SQL을 그대로
# 노출한다(Django check --deploy의 security.W018과 같은 위협). DEBUG는 개별
# 환경변수라 LAURIO_DEPLOYMENT_TARGET=production과 따로 놀 수 있으므로 여기서
# 조합을 직접 막는다.
if IS_PRODUCTION_DEPLOYMENT and DEBUG:
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 DJANGO_DEBUG 가 true 다. 운영 배포에서는 "
        "반드시 DJANGO_DEBUG=false 로 띄워야 한다 — DEBUG=true는 에러 페이지에 스택 "
        "트레이스와 설정값을 그대로 노출한다."
    )

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

# manage.py check --deploy의 security.W009: 50자 미만·고유 문자 5종 미만·
# "django-insecure-" 접두(Django가 `startproject`로 자동 생성한 키의 표식)는 전부
# "누구나 추측 가능한 키"의 신호다. staging은 아직 실제 세션·CSRF 서명 신뢰 경계가
# production만큼 엄격하지 않아도 되므로(하드닝은 아래 IS_PRODUCTION_DEPLOYMENT
# 블록 참고) 이 강도 검사는 production에만 건다 — CI의 비-production 잡이 쓰는
# 짧은 더미 키(ci-only-insecure-key)까지 걸리면 안 되기 때문이다.
if IS_PRODUCTION_DEPLOYMENT and (
    len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-")
):
    raise ImproperlyConfigured(
        "LAURIO_DEPLOYMENT_TARGET=production 인데 DJANGO_SECRET_KEY 가 약하다(50자 미만, "
        "고유 문자 5종 미만, 또는 django-insecure- 접두사). `python -c \"import secrets; "
        "print(secrets.token_urlsafe(64))\"` 등으로 새로 생성한 무작위 키를 주입해야 한다."
    )

ALLOWED_HOSTS = [h for h in _env("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]

INSTALLED_APPS = [
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
    "policies",
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
    "appeals",
]

MIDDLEWARE = [
    # 가장 바깥쪽에 둔다 — CommonMiddleware의 APPEND_SLASH 301, CsrfViewMiddleware의
    # 403 등 체인 중간에서 반환되는 응답도 이 미들웨어를 반드시 한 번 더 거쳐 나가므로
    # CSP 헤더가 모든 응답에 실제로 붙는다(ADR-0012 — 세 보완책 중 하나라도 빠지면
    # 무효).
    "accounts.middleware.ContentSecurityPolicyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # SecurityMiddleware 바로 다음(whitenoise 공식 권장 위치). 원래는 admin 의
    # CSS/JS 를 서빙하려고 넣었는데 admin 을 내렸으므로(#46, ADR-0019) 지금 이
    # 백엔드에는 서빙할 정적 파일이 사실상 없다. 그래도 남겨둔다 — DEBUG=False 인
    # staging/prod 에서 Django 는 정적 파일을 스스로 서빙하지 않고, 이 저장소에는
    # 아직 리버스 프록시가 없다. STATIC_ROOT 에 산출물이 없으면 그냥 통과시킬
    # 뿐이라 아무 비용도 들지 않는다.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # 운영자 경로의 변경 요청에 Origin 검증을 건다(#43, ADR-0016 의 성립 조건).
    # 세션 미들웨어 뒤에 두어 request.scheme·get_host() 가 준비된 상태에서 본다.
    "core.operator_auth.OperatorOriginMiddleware",
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
        # 테스트 DB 이름을 환경에서 바꿀 수 있게 한다.
        #
        # 기본값은 Django 관례 그대로 `test_<NAME>` 이라 아무것도 안 바뀐다.
        # 필요한 것은 **동시에 도는 두 pytest 가 서로를 밟지 않는 것**이다 —
        # 병렬 워크트리에서 체인 둘이 각자 pytest 를 돌리면 같은 `test_laurio`
        # 를 두고 싸워 `DROP DATABASE ... is being accessed by other users` 로
        # 서로를 떨어뜨린다. 실제로 겪었고, 그때 나오는 실패는 코드 회귀와
        # 구분되지 않아 사람이 시간을 버린다.
        #
        # 체인마다 `LAURIO_TEST_DB_NAME` 을 달리 주면 격리된다.
        "TEST": {"NAME": _env("LAURIO_TEST_DB_NAME", "") or None},
    }
}

# Operator 세션 (#43, ADR-0018). 세션 레코드를 지우는 것이 곧 즉시 무효화이므로
# 별도의 토큰 블랙리스트를 두지 않는다 — 돈을 움직이는 권한은 즉시 빼앗을 수 있어야
# 한다. 아래 기본값은 호스트에서 `uv run pytest` 를 돌릴 때만 쓰이고, 컨테이너
# 안에서는 compose 가 SESSION_REDIS_URL 을 직접 주입한다(DB 와 같은 구조).
#
# DB 인덱스를 1 로 둔다 — Celery 브로커가 0 을 쓰므로(compose 의 CELERY_BROKER_URL)
# 같은 인스턴스를 공유하면서도 키가 섞이지 않는다.
_DEV_REDIS_PORT = _env("LAURIO_REDIS_PORT", "16379")
SESSION_REDIS_URL = _env("SESSION_REDIS_URL", f"redis://127.0.0.1:{_DEV_REDIS_PORT}/1")

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "sessions": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": SESSION_REDIS_URL,
        # 세션 키에 접두어를 붙일 수 있게 한다.
        #
        # Operator 세션은 실제 Redis 에 산다(ADR-0018) — 그래서 **동시에 도는 두
        # pytest 가 서로의 세션을 밟는다.** 한쪽이 캐시를 비우거나 같은 키를 쓰면
        # 다른 쪽 Operator 가 로그인한 적 없는 것이 되어, 원인과 무관한 401 무더기로
        # 무너진다. 실제로 겪었고, 그 실패는 코드 회귀와 구분되지 않는다.
        #
        # `LAURIO_TEST_DB_NAME` 과 같은 처방이다 — 병렬 워크트리에서 체인마다
        # `LAURIO_SESSION_KEY_PREFIX` 를 달리 주면 격리된다. 기본값은 빈 문자열이라
        # 단독 실행과 배포는 아무것도 바뀌지 않는다.
        "KEY_PREFIX": _env("LAURIO_SESSION_KEY_PREFIX", ""),
    },
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"
# Operator 세션 전용 이름 — 참가자 세션이라는 개념 자체가 없으므로(참가자는 JWT 를
# 쿠키에 담아 BFF 가 들고 있다, ADR-0016) 이 쿠키는 언제나 Operator 의 것이다.
SESSION_COOKIE_NAME = "laurio_operator_session"
# Django 기본값과 같지만 명시한다 — 이 쿠키가 돈을 움직이는 권한을 들고 있어서,
# 기본값이 조용히 바뀌는 것에 기대면 안 된다.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# 운영자 앱의 오리진. 배포 환경에서는 명시적으로 준다 — Host 헤더 유도보다 강하고
# 리버스 프록시 구성에 흔들리지 않는다. 비어 있으면 요청이 실제로 도착한 주소로
# 조립한다(dev·테스트).
OPERATOR_WEB_ORIGIN = _env("LAURIO_OPERATOR_ORIGIN", "")

if IS_DEPLOYED_ENVIRONMENT and not OPERATOR_WEB_ORIGIN:
    # 비어 있으면 Host 헤더 유도로 떨어지는데, `SECURE_PROXY_SSL_HEADER` 는
    # production 에만 걸린다 — TLS 종단 프록시 뒤의 staging 에서는 scheme 이 http 로
    # 잡혀 브라우저가 보낸 https 오리진과 어긋나고, **로그인을 포함한 모든 변경
    # 요청이 403** 이 된다. fail-closed 라 보안 구멍은 아니지만 운영이 통째로 죽는다.
    #
    # 프론트엔드가 LAURIO_WEB_ORIGIN 에 대해 이미 같은 실패를 겪고 같은 방식으로
    # 막았다(frontend/instrumentation.ts) — 여기서 그 결을 맞춘다.
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET} 인데 "
        "LAURIO_OPERATOR_ORIGIN 이 비어 있다. 배포 환경에서는 운영자 앱의 오리진을 "
        "명시해야 한다 — Host 헤더 유도는 리버스 프록시 구성에 따라 어긋나고, "
        "그러면 운영자의 모든 변경 요청이 403 이 된다."
    )

# 스토리지 어댑터 (ADR-0005, ADR-0007): "fake"가 기본값이라 아무것도 설정하지 않아도
# 테스트·CI는 MinIO 없이 돈다. dev compose가 backend 컨테이너에만 STORAGE_BACKEND=s3
# 를 주입해 MinIO로 바인딩한다(docker/compose.dev.yaml). staging/prod는 같은 "s3"
# 백엔드가 실제 S3·OCI 엔드포인트를 가리키도록 환경변수만 바꾼다.
STORAGE_BACKEND = _env("STORAGE_BACKEND", "fake")

# DJANGO_SECRET_KEY 가드(위)와 같은 이유다. STORAGE_BACKEND 를 잊고 배포하면
# FakeStorageAdapter가 200과 함께 https://fake-storage.test/... 를 돌려주고, 업로드도
# 다운로드도 겉보기엔 성공한 채 파일만 소리 없이 사라진다. 실제 운영 배포에서는 아예
# 못 뜨게 막는다 — DEBUG가 아니라 LAURIO_DEPLOYMENT_TARGET을 본다. staging도 대상이다
# (ADR-0007: staging은 S3/OCI에 실제로 붙어 연동 규약을 검증하는 자리다). CI는
# DEBUG=false로 돌면서도 배포된 환경이 아니므로(위 설명) 이 가드에 걸리지 않고
# fake로 테스트를 돌릴 수 있어야 한다.
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(STORAGE_BACKEND):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 STORAGE_BACKEND 가 "
        "fake 다. presigned URL이 200으로 발급되면서 파일이 소리 없이 유실된다. "
        "staging/production 배포에서는 STORAGE_BACKEND=s3 를 반드시 설정해야 한다."
    )

STORAGE_BUCKET = _env("STORAGE_BUCKET", "laurio-dev")
# 기본값은 호스트에서 직접 돌릴 때를 가정한다(LAURIO_MINIO_PORT). 컨테이너 안에서는
# compose가 STORAGE_ENDPOINT_URL=http://minio:9000 을 직접 주입한다.
STORAGE_ENDPOINT_URL = _env("STORAGE_ENDPOINT_URL", "http://127.0.0.1:19000")
# presigned URL은 브라우저가 직접 여는 주소라 STORAGE_ENDPOINT_URL과 다를 수 있다
# (FE-09, #34). dev compose는 backend 컨테이너 안에서 STORAGE_ENDPOINT_URL=
# http://minio:9000(컨테이너 내부 DNS)을 쓰는데, 이 이름은 브라우저(호스트)가
# 해석할 수 없다 — presign_upload/presign_download가 만드는 URL의 호스트가
# 곧바로 브라우저 접속 실패로 이어지는 것을 직접 재현해 확인했다. 브라우저가
# 실제로 열 수 있는 주소(호스트에 매핑된 포트)를 이 값으로 별도로 준다.
# STORAGE_ENDPOINT_URL은 서버 프로세스 자신이 붙는 주소(read_object 등)로 계속
# 쓴다 — presign은 네트워크를 타지 않는 순수 로컬 서명이라(storage/adapters/s3.py)
# 두 값이 갈라져도 서버 쪽 동작에는 영향이 없다. staging/prod는 실제 S3/OCI
# 엔드포인트 자체가 이미 공개 주소라 보통 값이 같으므로, 기본값은
# STORAGE_ENDPOINT_URL을 그대로 물려받는다.
STORAGE_PUBLIC_ENDPOINT_URL = _env("STORAGE_PUBLIC_ENDPOINT_URL", STORAGE_ENDPOINT_URL)
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
# whitenoise가 collectstatic 산출물을 직접 서빙한다(위 MIDDLEWARE 참고). Manifest
# 변형(WhiteNoiseStorage/CompressedManifestStaticFilesStorage)은 collectstatic이
# 돌지 않은 dev에서 매니페스트 조회 실패로 {% static %}이 예외를 던질 수 있어
# 피한다 — 매니페스트가 필요 없는 압축 전용 스토리지를 쓴다.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

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
# API를 부르려면 SOCIAL_AUTH_MODE=real 을 명시해야 한다 — staging/production 배포(#23)가
# 그렇게 한다.
SOCIAL_AUTH_MODE = _env("SOCIAL_AUTH_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(SOCIAL_AUTH_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 SOCIAL_AUTH_MODE 가 "
        "fake 다. staging/production 배포에서는 SOCIAL_AUTH_MODE=real 을 반드시 설정해야 한다."
    )

# --- Verification (ADR-0011, ADR-0007) ------------------------------------
# 본인확인 어댑터도 같은 원칙: 기본값은 항상 fake이고, staging/production 배포만
# real을 명시한다.
VERIFICATION_ADAPTER_MODE = _env("VERIFICATION_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(VERIFICATION_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 "
        "VERIFICATION_ADAPTER_MODE 가 fake 다. staging/production 배포에서는 실제 "
        "본인확인 어댑터의 dotted path를 반드시 설정해야 한다."
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
# 네트워크 없이 결정적으로 주입할 수 있다. staging은 토스 "샌드박스"(연동 규약만
# 검증, 실제 돈은 안 움직인다), production은 토스 "실물"에 PAYMENT_ADAPTER_MODE=real로
# 명시한다(ADR-0008, #23의 범위). 샌드박스냐 실물이냐는 이 모드 값이 아니라 함께
# 주입하는 토스 자격증명·엔드포인트가 어디를 가리키는지로 갈린다.
PAYMENT_ADAPTER_MODE = _env("PAYMENT_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(PAYMENT_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 PAYMENT_ADAPTER_MODE 가 "
        "fake 다. staging/production 배포에서는 실제 PG 어댑터의 dotted path를 반드시 "
        "설정해야 한다."
    )

# 개최비·심사기간·심사기간 연장 단위·연장비는 더 이상 여기 없다(#78,
# ADR-0023) — `policies.models.PlatformPolicy`(DB 단일 행)의
# contest_listing_fee·judging_period_days·judging_extension_days·
# judging_extension_fee로 옮겼다. 아래 두 줄이 있던 자리(#13, ADR-0003)다.

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

# 다른 어댑터들(STORAGE_BACKEND·PAYMENT_ADAPTER_MODE 등)은 "fake"라는 별도 별칭
# 문자열로 fake를 고르지만, 알림 채널은 처음부터 dotted path만 쓴다 — 기본값 자체가
# `notifications.adapters.Fake*Adapter`다. 그래서 같은 "배포에 fake가 섞이면 안
# 된다"는 안전장치를 여기서는 "dotted path가 notifications.adapters.Fake로
# 시작하는가"로 판정한다.
for _notification_setting_name, _notification_adapter_path in (
    ("NOTIFICATION_ALIMTALK_ADAPTER", NOTIFICATION_ALIMTALK_ADAPTER),
    ("NOTIFICATION_SMS_ADAPTER", NOTIFICATION_SMS_ADAPTER),
    ("NOTIFICATION_LMS_ADAPTER", NOTIFICATION_LMS_ADAPTER),
):
    if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(_notification_adapter_path):
        raise ImproperlyConfigured(
            f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 "
            f"{_notification_setting_name}={_notification_adapter_path!r} 가 Fake 구현체다. "
            "staging/production 배포에서는 실제 벤더 어댑터의 dotted path를 반드시 "
            "설정해야 한다."
        )
del _notification_setting_name, _notification_adapter_path

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
# 네트워크 없이 결정적으로 채점 플로우 전체를 돈다. staging/production 배포만
# LLM_ADAPTER_MODE에 실제 어댑터의 dotted path(또는 향후 등록될 별칭)를 명시한다.
LLM_ADAPTER_MODE = _env("LLM_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(LLM_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 LLM_ADAPTER_MODE 가 "
        "fake 다. Score가 실제 채점 없이 만들어지면 Distribution 대상 판정이 통째로 "
        "무효가 된다. staging/production 배포에서는 실제 LLM 어댑터를 반드시 설정해야 한다."
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
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(LLM_REQUIREMENT_CHAT_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 "
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE 가 fake 다. staging/production 배포에서는 "
        "실제 LLM 어댑터를 반드시 설정해야 한다."
    )

# 테스트가 override_settings로 특정 contest_id의 대화 응답 실패를 흉내낼 때 쓴다
# (LLM_FAKE_RAISING_SUBMISSION_IDS와 같은 원칙).
LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS = [
    int(x) for x in _env("LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS", "").split(",") if x
]

# --- Handover · Escrow 해제 (#14, ADR-0003/0004/0005/0014) --------------------------
#
# 인도 승인 기간은 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.handover_acceptance_period_days`로 옮겼다.

# --- Payout 실행 (#15, ADR-0004/0008) -------------------------------------------------
#
# 토스 지급대행 어댑터도 PAYMENT_ADAPTER_MODE와 같은 원칙: 기본값은 항상 Fake다.
# staging은 토스 지급대행 샌드박스, production은 실물에 real로 바인딩한다(ADR-0008).
PAYOUT_ADAPTER_MODE = _env("PAYOUT_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(PAYOUT_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 PAYOUT_ADAPTER_MODE 가 "
        "fake 다. staging/production 배포에서는 실제 지급대행 어댑터의 dotted path를 "
        "반드시 설정해야 한다."
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

# 플랫폼 수수료·원천징수 공제율은 더 이상 여기 없다(#75, ADR-0023). settings.py가
# 환경변수로 읽었지만 staging·prod 어디에도 그 값을 준 적이 없어 실질적으로 코드
# 상수였고, 요율은 환경의 성질이 아니라 사업 정책이다 — staging과 production에서
# 달라지면 그것은 설정이 아니라 버그다. `policies.models.PlatformPolicy`(DB 단일
# 행)가 대신하고, `policies.services.get_current_policy()`로 읽는다. 두 경로를
# 남기지 않는다 — CSRF 방어를 두 기계로 두었다가 한쪽 발급처가 사라져 영구 403이
# 된 사고가 이 저장소에 있다.

# --- Seller(지급대행사 수취인) 등록 어댑터 (#50, ADR-0007, ADR-0020) -------------------
#
# PAYOUT_ADAPTER_MODE와 같은 원칙: 기본값은 항상 fake다. 실제 토스 지급대행 셀러
# 등록은 이 티켓 범위 밖이다(#57) — staging/production에서만 real dotted path를
# 요구한다.
SELLER_ADAPTER_MODE = _env("SELLER_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(SELLER_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"LAURIO_DEPLOYMENT_TARGET={LAURIO_DEPLOYMENT_TARGET!r} 인데 SELLER_ADAPTER_MODE "
        "가 fake 다. staging/production 배포에서는 실제 Seller 등록 어댑터의 dotted "
        "path를 반드시 설정해야 한다."
    )

# 지급대행 주간 한도는 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.seller_weekly_limit_amount`로 옮겼다. **이
# 값은 우리 정책이 아니라 토스가 정한 사실**이다(ADR-0020) — 같은 행에 있어도
# 우리 판단으로 올릴 수 있는 값이 아니다.

# --- Distribution (#16, ADR-0003/0004/0006) -------------------------------------------
#
# 배분 대기 기간은 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.distribution_wait_days`로 옮겼다.

# --- Notification 연결: Contest 라이프사이클 (#19, ADR-0009/0010) ----------------------
#
# 마감·심사기간 종료·Distribution이 다가올 때 Sponsor·Developer에게 미리 알린다.
# 실제 발송(즉시/야간 연기/대체발송)은 notifications.services(#18)가 그대로
# 담당한다 — 여기서는 "언제 그 알림을 만들 것인가"만 정한다(notifications.lifecycle).
# 세 리드타임(마감 임박·심사 종료 임박·Distribution 최종 경고) 모두 더 이상
# 여기 없다(#78, ADR-0023) — `policies.models.PlatformPolicy`의
# deadline_reminder_lead_hours·judging_end_reminder_lead_hours·
# distribution_final_warning_lead_days로 옮겼다.

# 08:00~21:00(quiet hours 밖) 중 임의로 고른 낮 시각. 이 값을 바꾸려면 반드시
# 08~20 사이로 유지해야 한다 — 그 밖으로 나가면 "낮 시각 구성" 자체가 깨진다.
# (사업 정책이 아니라 알림 스케줄링의 기술적 상수라 이 티켓의 이전 대상이
# 아니다 — CONTEST_LISTING_FEE 등과 달리 여기 그대로 남는다.)
NOTIFICATION_DAYTIME_HOUR = int(_env("NOTIFICATION_DAYTIME_HOUR", "10"))

# --- 운영 배포 하드닝 (#23, 티켓 01(#1)이 미룬 `manage.py check --deploy`) --------------
#
# 이 검사를 처음 켰을 때 다섯 경고가 났다: HSTS 미설정(W004), SSL 리다이렉트 꺼짐
# (W008), 약한 SECRET_KEY(W009, 위에서 해소), 세션 쿠키가 secure가 아님(W012), CSRF
# 쿠키가 secure가 아님(W016). 침묵시키는 대신(`SILENCED_SYSTEM_CHECKS`) 실제 설정을
# 고친다 — dev/staging은 TLS 종단 구성이 서로 다르거나(staging은 검증용 서브호스트라
# 아직 리버스 프록시가 없을 수 있다) 아예 HTTP로도 돌아야 하므로, 이 하드닝은
# IS_PRODUCTION_DEPLOYMENT에만 켠다. staging에서도 fake 어댑터가 섞이지 않게 막는
# 것(위 IS_DEPLOYED_ENVIRONMENT 가드들)과는 다른 질문이라는 걸 여기서도 반복한다.
SECURE_SSL_REDIRECT = IS_PRODUCTION_DEPLOYMENT
SECURE_HSTS_SECONDS = int(_env("SECURE_HSTS_SECONDS", "31536000")) if IS_PRODUCTION_DEPLOYMENT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION_DEPLOYMENT
SECURE_HSTS_PRELOAD = IS_PRODUCTION_DEPLOYMENT
SESSION_COOKIE_SECURE = IS_PRODUCTION_DEPLOYMENT
CSRF_COOKIE_SECURE = IS_PRODUCTION_DEPLOYMENT
if IS_PRODUCTION_DEPLOYMENT:
    # AWS/OCI 배포는 로드밸런서가 TLS를 종단하고 백엔드까지는 평문 HTTP로 붙는다 —
    # 그 앞단이 원본 스킴을 이 헤더로 넘겨준다는 전제다. 이 헤더를 신뢰하는 로드밸런서를
    # 거치지 않고 백엔드가 직접 인터넷에 노출되면 누구나 이 헤더를 위조해
    # SECURE_SSL_REDIRECT를 우회할 수 있으므로, 실제 배포에서는 backend를 호스트의
    # 127.0.0.1에만 publish해 그 프록시 없이는 아예 도달할 수 없게 한다
    # (docker/compose.prod.yaml 참고).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # 코디네이터 리뷰 지적: Celery beat(core/tasks.py)는 컨테이너 내부 네트워크에서
    # `http://backend:8000/api/internal/...`를 직접 호출한다 — 로드밸런서를 거치지
    # 않으므로 X-Forwarded-Proto가 없고, request.is_secure()는 False다.
    # SECURE_SSL_REDIRECT=True와 만나면 이 내부 호출이 매번 301(https로)을 받고,
    # 평문 gunicorn은 TLS 핸드셰이크를 할 수 없으니 SSLError로 죽는다 — beat가 있어도
    # 틱이 통과하지 못하는 상태다. 내부 전용 경로(전부 core.auth.InternalAuth로
    # 보호된다 — accounts.tokens.py 등 브라우저가 부르는 공개 API와는 다른 신뢰
    # 경계다)는 SSL 리다이렉트 대상에서 뺀다.
    SECURE_REDIRECT_EXEMPT = [r"^api/internal/"]
