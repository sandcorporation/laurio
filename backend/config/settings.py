"""Codemit backend 설정.

환경별 차이는 전부 환경변수로 주입한다. 배포는 `docker/compose.prod.yaml` 하나다.
"""

import hashlib
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Fernet 은 VERIFICATION_ENCRYPTION_KEY 가 **쓸 수 있는 키인지**를 부팅 시점에
# 확인하는 데만 쓴다(아래 Verification 절). Django 앱 레지스트리를 건드리지
# 않으므로 settings.py 실행 도중 임포트해도 안전하다.
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# core.adapters는 Django 모델·앱 레지스트리가 필요한 것을 아무것도 임포트하지
# 않으므로(core/adapters.py 모듈 docstring) settings.py 모듈 실행 도중(=아직 앱
# 레지스트리가 준비되지 않은 시점)에 import해도 안전하다. 배포 부팅 가드(아래
# IS_DEPLOYED_ENVIRONMENT 블록들)와 verification.api.verify의
# identityVerificationId 소유권 확인이 반드시 같은 fake 판정을 써야 하므로
# (#85 코드리뷰 지적 5), 그 판정 함수를 여기서 임포트해 별칭(`_is_fake_adapter_binding`)
# 으로 그대로 쓴다.
from core.adapters import is_fake_adapter_binding as _is_fake_adapter_binding

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
# False이고, prod compose(`docker/compose.prod.yaml`)만 명시적으로 production을 준다.
#
# 배포 대상은 production 하나다. staging 은 2026-10-30(#836, ADR-0068)에 없앴고, 그
# 값은 이제 아래 검증에서 다른 오타와 똑같이 부팅을 거부당한다 — 옛 staging 용
# `.env` 가 어디서 되살아나도 조용히 development 로 흘러 가드가 꺼지는 일은 없다.
# 아래 두 플래그는 지금 같은 값이다. 둘을 남기는 것은 읽는 자리가 묻는 질문이
# 달라서다: IS_DEPLOYED_ENVIRONMENT 는 「fake 어댑터·시드·진단 표면이 섞이면 안
# 되는 자리인가」, IS_PRODUCTION_DEPLOYMENT 는 「TLS·시크릿 강도 하드닝을 거는
# 자리인가」를 묻는다.
_VALID_DEPLOYMENT_TARGETS = {"development", "production"}
CODEMIT_DEPLOYMENT_TARGET = _env("CODEMIT_DEPLOYMENT_TARGET", "development")
# 코디네이터 리뷰 지적: 이 값이 검증되지 않으면 "prod", "Production", 오타 하나가
# 조용히 "development"로도, "production"으로도 매치하지 않는
# 상태로 흘러 아래 모든 가드(fake 어댑터 거부·SECRET_KEY 강도·DEBUG 거부·TLS
# 하드닝)를 통째로 무력화한다 — 이 티켓의 목적 자체가 "조용히 통과하는 대신 크게
# 실패한다"이므로, 허용된 두 값이 아니면 그 자리에서 바로 죽는다.
if CODEMIT_DEPLOYMENT_TARGET not in _VALID_DEPLOYMENT_TARGETS:
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 는 유효하지 않다. "
        f"{sorted(_VALID_DEPLOYMENT_TARGETS)} 중 하나여야 한다 — 오타 하나가 이 값 아래의 "
        "모든 배포 가드(fake 어댑터 거부, SECRET_KEY 강도, DEBUG 거부, TLS 하드닝)를 "
        "전부 무력화하므로 미설정 기본값(development)으로 조용히 흘려보내지 않는다."
    )
IS_PRODUCTION_DEPLOYMENT = CODEMIT_DEPLOYMENT_TARGET == "production"
IS_DEPLOYED_ENVIRONMENT = IS_PRODUCTION_DEPLOYMENT

# 공모전 제품 스위치(#271/#413) — 방향이 바뀌어 공모전은 나중을 위한 기능이
# 됐다가(ADR-0037), 돈을 다루지 않는 무료 공모전로 다시 열렸다(ADR-0048). 코드도
# 데이터도 그대로 두고 표면만 닫는다. **기본값은 켜짐**이고, 이 값은
# `CODEMIT_DEPLOYMENT_TARGET`과 무관한 독립 값이다 — "배포 환경이면 끈다"로 묶으면
# 나중에 prod에서 다시 켤 때 그 판단 규칙 자체를 고쳐야 한다. dev·CI는 이 값을
# 건드리지 않으므로 여전히 켜진 채다. 꺼졌을 때 무엇이 닫히고 무엇이 열려 있어야
# 하는지의 전체 목록은 `core.contest_switch` 모듈 docstring 하나에 모아 둔다 —
# 다시 켜는 날 읽을 자리다.
CONTEST_PRODUCT_ENABLED = _env_bool("CODEMIT_CONTEST_PRODUCT_ENABLED", True)

# 유료 공모전 스위치(#413, ADR-0048) — 위 공모전 스위치가 표면 전체를 가르는
# 스위치라면, 이 값은 그 안에서 돈이 실제로 오가는 경로(견적·결제·본인확인이
# 필요한 유료 개최·유료 심사기간 연장·환불·배분·지급·인수인계 스캔)만 가른다.
# `core.contest_switch.paid_contest_product_enabled()`가 위 CONTEST_PRODUCT_ENABLED
# 와 AND로 묶는다 — 공모전 스위치가 꺼지면 이 값과 무관하게 유료도 함께 꺼진다.
# **기본값은 켜짐**이고, `docker/compose.prod.yaml`
# 만 이 환경변수의 기본값을 false로 겹쳐 쓴다(dev·CI는 건드리지 않으므로 여전히
# 켜진 채다 — 기존 유료 공모전 테스트가 계속 초록이어야 한다).
PAID_CONTEST_PRODUCT_ENABLED = _env_bool("CODEMIT_PAID_CONTEST_PRODUCT_ENABLED", True)

# 개인정보처리방침의 시행일(#803) — **한국 시간 0시부터** 시행한다. 이 값이 하나다: 방침 화면
# (`frontend/app/privacy/page.tsx` 의 EFFECTIVE_DATE — `tests/test_privacy_policy_effective_date.py`
# 가 두 값이 같은지 지킨다), 시행일 전 Claude(Anthropic) 키 저장 잠금(`core.privacy_policy`)이 모두
# 이 값을 본다. 방침을 고칠 때는 시행일 7일 전부터 공지해야 하므로(12항) 병합일 +7일 이상으로 옮긴다.
PRIVACY_POLICY_EFFECTIVE_DATE = date(2026, 11, 6)

# production인데 DEBUG=true로 뜨면 에러 페이지가 스택 트레이스·환경변수·SQL을 그대로
# 노출한다(Django check --deploy의 security.W018과 같은 위협). DEBUG는 개별
# 환경변수라 CODEMIT_DEPLOYMENT_TARGET=production과 따로 놀 수 있으므로 여기서
# 조합을 직접 막는다.
if IS_PRODUCTION_DEPLOYMENT and DEBUG:
    raise ImproperlyConfigured(
        "CODEMIT_DEPLOYMENT_TARGET=production 인데 DJANGO_DEBUG 가 true 다. 운영 배포에서는 "
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
# "누구나 추측 가능한 키"의 신호다. 이 강도 검사는 production에만 건다 — CI의
# 비-production 잡이 쓰는 짧은 더미 키(ci-only-insecure-key)까지 걸리면 안 되기
# 때문이다.
if IS_PRODUCTION_DEPLOYMENT and (
    len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-")
):
    raise ImproperlyConfigured(
        "CODEMIT_DEPLOYMENT_TARGET=production 인데 DJANGO_SECRET_KEY 가 약하다(50자 미만, "
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
    "repositories",
    "awards",
    "handovers",
    "payouts",
    "distributions",
    "appeals",
    # 강의실(ADR-0037). 첫 삽 — 모델은 아직 없다(#275). 경계는 이 앱이 서는
    # 순간부터 물게 하려고 `tests/test_app_boundaries.py` 의 분류표에 먼저
    # 이름을 적어 뒀다.
    "classroom",
    "ops_metrics",
]

MIDDLEWARE = [
    # 요청 id(2026-09-21, core/request_id.py) — 가장 바깥이어야 체인 중간에서 나간 응답에도
    # 헤더가 붙고, 그 사이의 모든 로그가 같은 id 를 갖는다.
    "core.request_id.RequestIdMiddleware",
    # 요청량·지연·상태코드(core/metrics.py) — 바깥쪽에 두어야 체인 전체가 걸린 시간과
    # 체인 중간에서 결정된 최종 상태코드를 잰다.
    "core.metrics.MetricsMiddleware",
    # 요청 안의 SQL 문에 statement_timeout·lock_timeout 을 건다(#745, core/db_timeouts.py) —
    # gthread 는 걸린 요청을 죽이지 않는다. 세션 미들웨어의 쿼리도 덮도록 앞쪽에 둔다.
    "core.db_timeouts.RequestDbTimeoutMiddleware",
    # 가장 바깥쪽에 둔다 — CommonMiddleware의 APPEND_SLASH 301, CsrfViewMiddleware의
    # 403 등 체인 중간에서 반환되는 응답도 이 미들웨어를 반드시 한 번 더 거쳐 나가므로
    # CSP 헤더가 모든 응답에 실제로 붙는다(ADR-0012 — 세 보완책 중 하나라도 빠지면
    # 무효).
    "accounts.middleware.ContentSecurityPolicyMiddleware",
    # compose 내부 서비스 이름(backend·events)으로 들어온 BFF·스트림 중계 요청을 TLS 프록시를 거친
    # 요청처럼 다룬다 — 없으면 prod 의 SSL 리다이렉트가 그 요청마다 301 을 내 카카오 로그인이
    # 막혔다(core/internal_hosts.py). SecurityMiddleware 보다 앞이어야 한다.
    "core.internal_hosts.InternalServiceHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # SecurityMiddleware 바로 다음(whitenoise 공식 권장 위치). 원래는 admin 의
    # CSS/JS 를 서빙하려고 넣었는데 admin 을 내렸으므로(#46, ADR-0019) 지금 이
    # 백엔드에는 서빙할 정적 파일이 사실상 없다. 그래도 남겨둔다 — DEBUG=False 인
    # prod 에서 Django 는 정적 파일을 스스로 서빙하지 않고, 이 저장소에는
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
    # 요청 하나 = PlatformPolicy 스코프 하나(#145, ADR-0023) — 그 안에서 `policies.scope.
    # current_policy()` 는 첫 호출에 한 번만 SELECT 한다.
    "policies.middleware.PolicyScopeMiddleware",
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
# 실제로 공개한 포트(CODEMIT_DB_PORT)를 그대로 따라간다. 다른 프로젝트의 5432 에
# 잘못 붙는 사고를 막기 위함이다.
_DEV_DB_PORT = _env("CODEMIT_DB_PORT", "55432")

# --- 병렬 격리 (#104, 테스트 격리 개편) -------------------------------------------
#
# 같은 머신에서 두 체크아웃(워크트리)이 각자 테스트를 돌리는 것이 이 저장소의 일상이다.
# 그때 **공유되는 것이 무엇인가**가 조용한 실패의 원천이었다 — 같은 이름의 테스트 DB 를
# 두고 싸워 `DROP DATABASE ... is being accessed by other users` 로 서로를 떨어뜨렸고,
# 그 실패는 코드 회귀와 구분되지 않는다.
#
# 손으로 환경변수를 갈라 주는 규약이 있었지만 잊으면 그만이다. 이제 **경로에서 파생**한다.
_CHECKOUT_TOKEN = hashlib.sha256(str(BASE_DIR.resolve()).encode("utf-8")).hexdigest()[:8]


def _default_test_db_name() -> str:
    """이 체크아웃 전용 테스트 DB 이름. pytest-django 가 워커별로 `_gwN` 을 덧붙이고, 워커들이
    복제해 쓰는 템플릿은 `_tpl` 이다(`tests/db_template.py`, #755)."""

    return f"test_codemit_{_CHECKOUT_TOKEN}"


# **테스트에서는 세션 캐시가 프로세스 안에 산다.**
#
# 운영에서 세션이 Redis 에 사는 것은 ADR-0018 의 결정이고 그대로다 — 세션을 지우는 것이
# 곧 즉시 무효화이고, 돈을 움직이는 권한은 즉시 빼앗을 수 있어야 한다. 그 결정은 **운영**에
# 대한 것이지 「테스트도 실물 Redis 를 써야 한다」가 아니다.
#
# 테스트가 실물 Redis 를 쓰면 두 가지가 따라온다.
#
# 1. `tests/conftest.py` 가 매 테스트 캐시를 비우는데 Django 의 RedisCache 는 그것을
#    **FLUSHDB** 로 구현한다 — 키 접두어로는 막을 수 없다. 그래서 워커마다, 체인마다
#    인덱스를 갈라 줘야 했고(Redis 기본 범위가 0~15 이라 금방 바닥난다) 잊으면 서로의
#    세션을 지웠다.
# 2. 호스트에서 돌리는 pytest 의 기본 세션 URL 이 dev compose 가 노출한 **바로 그 Redis
#    의 같은 인덱스**였다. 즉 `uv run pytest` 한 번이 떠 있는 dev 환경의 운영자 세션과
#    조회 카운터를 통째로 지웠다.
#
# LocMem 은 프로세스별로 갈리므로 워커 격리도 체인 격리도 공짜이고, 위 둘이 함께 사라진다.
# 실물 Redis 위의 세션 동작은 운영자 로그인 e2e 가 실물 스택으로 계속 덮는다.
_RUNNING_TESTS = "pytest" in sys.modules or _env("CODEMIT_TEST_CACHE", "") == "locmem"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _env("POSTGRES_DB", "codemit"),
        "USER": _env("POSTGRES_USER", "codemit"),
        "PASSWORD": _env("POSTGRES_PASSWORD", "codemit"),
        "HOST": _env("POSTGRES_HOST", "127.0.0.1"),
        "PORT": _env("POSTGRES_PORT", _DEV_DB_PORT),
        # 테스트 DB 이름을 환경에서 바꿀 수 있게 한다.
        #
        # 기본값은 Django 관례 그대로 `test_<NAME>` 이라 아무것도 안 바뀐다.
        # 필요한 것은 **동시에 도는 두 pytest 가 서로를 밟지 않는 것**이다 —
        # 병렬 워크트리에서 체인 둘이 각자 pytest 를 돌리면 같은 `test_codemit`
        # 를 두고 싸워 `DROP DATABASE ... is being accessed by other users` 로
        # 서로를 떨어뜨린다. 실제로 겪었고, 그때 나오는 실패는 코드 회귀와
        # 구분되지 않아 사람이 시간을 버린다.
        #
        # **체크아웃 경로에서 자동으로 갈린다.** 손으로 주는 것을 잊으면 조용히 서로를
        # 떨어뜨리므로(위 설명) 기본값 자체를 경로에서 만든다. 명시적으로 주면 그 값이
        # 이긴다 — CI 처럼 경로가 매번 달라지는 곳에서 이름을 고정하고 싶을 때가 있다.
        "TEST": {"NAME": _env("CODEMIT_TEST_DB_NAME", "") or _default_test_db_name()},
        # 연결 풀러(pgbouncer)를 트랜잭션 모드로 앞에 두면 서버측(named) 커서가
        # 깨진다 — dev pgbouncer 프로필로 직접 재현해 확인했다(#457):
        # `QuerySet.iterator()`(WITH HOLD 커서를 연다)를 이 값 없이 풀러 뒤에서
        # 돌리면 `ProgrammingError: portal "_django_curs_..." does not exist`
        # 로 죽는다 — 커서를 연 트랜잭션이 끝나는 순간 그 물리 연결이 다른
        # 클라이언트에게 넘어가 버려서다. 이 값을 True 로 켜면 같은 코드가
        # 그대로 통과한다(같은 재현으로 확인). dev 기본은 풀러 없이 직접 DB 에
        # 붙으므로 그대로 False(Django 기본값)다 — 풀러 프로필
        # (`--profile pgbouncer`)이나 prod compose 가
        # `CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS=true`로 켠다. 준비된 문장
        # (prepared statement)은 이미 Django 가 psycopg3 백엔드에서 기본으로
        # 끈다(django/db/backends/postgresql/base.py 의 `prepare_threshold=None`
        # 주석 "Disable prepared statements by default to keep connection
        # poolers working") — 여기서 따로 손댈 것이 없다.
        "DISABLE_SERVER_SIDE_CURSORS": _env_bool(
            "CODEMIT_DB_DISABLE_SERVER_SIDE_CURSORS", False
        ),
    }
}

# 요청 경로의 DB 한도(#745, core/db_timeouts.py) — 밀리초, 0 이면 끔. statement 는 gunicorn 요청
# 예산(30초) 안, lock 은 그보다 짧게. celery·관리 명령에는 걸리지 않는다.
CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS = int(_env("CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS", "25000"))
CODEMIT_REQUEST_LOCK_TIMEOUT_MS = int(_env("CODEMIT_REQUEST_LOCK_TIMEOUT_MS", "5000"))

# **연결 사용률을 재는 전용 별칭**(#455/#458) — 「상한에 얼마나 가까운가」는 DB
# 자신에게 물어야 한다. 배포에서는 앱의 "default" 연결이 연결 풀러를 거치므로
# 그 길로 물으면 풀러가 흡수한 뒤의 수가 나온다(2026-09-18 장애를 일으킨 숫자는
# 풀러 뒤의 서버 연결 수였다). 그래서 이 별칭만 풀러를 건너뛴다 — 접속 주소
# 둘(`DB_MONITOR_HOST`/`DB_MONITOR_PORT`)만 다르고 나머지는 "default"와 같다.
# 주지 않으면 "default"와 같은 곳을 보므로 dev·CI 는 지금과 똑같이 돈다.
#
# **테스트 DB 를 하나 더 만들지 않는다** — 같은 DB 를 다른 길로 볼 뿐이라
# `TEST["MIRROR"]`로 "default"의 거울임을 선언한다(Django 테스트 러너가 이
# 별칭에 대해 DB 를 따로 만들지 않고 "default"를 그대로 쓴다).
DATABASES["monitor"] = {
    **DATABASES["default"],
    "HOST": _env("DB_MONITOR_HOST", DATABASES["default"]["HOST"]),
    "PORT": _env("DB_MONITOR_PORT", str(DATABASES["default"]["PORT"])),
    "TEST": {**DATABASES["default"]["TEST"], "MIRROR": "default"},
}

# Operator 세션 (#43, ADR-0018). 세션 레코드를 지우는 것이 곧 즉시 무효화이므로
# 별도의 토큰 블랙리스트를 두지 않는다 — 돈을 움직이는 권한은 즉시 빼앗을 수 있어야
# 한다. 아래 기본값은 호스트에서 `uv run pytest` 를 돌릴 때만 쓰이고, 컨테이너
# 안에서는 compose 가 SESSION_REDIS_URL 을 직접 주입한다(DB 와 같은 구조).
#
# DB 인덱스를 1 로 둔다 — Celery 브로커가 0 을 쓰므로(compose 의 CELERY_BROKER_URL)
# 같은 인스턴스를 공유하면서도 키가 섞이지 않는다.
_DEV_REDIS_PORT = _env("CODEMIT_REDIS_PORT", "16379")
# **동시에 두 pytest 를 돌린다면 이 값의 DB 인덱스를 서로 다르게 줘라.**
#
# `tests/conftest.py` 가 테스트마다 `caches["sessions"].clear()` 를 부르는데,
# Django 의 RedisCache 는 그것을 **FLUSHDB** 로 구현한다 — 즉 키 접두어가 있든
# 없든 **그 DB 전체**를 날린다. 그래서 두 체인이 같은 인덱스를 쓰면 한쪽의
# 테스트 정리가 다른 쪽의 로그인 세션을 통째로 지우고, 피해자는 원인과 무관한
# 401 무더기를 본다 — 코드 회귀와 구분되지 않는다. 접두어로는 막을 수 없고
# 인덱스를 갈라야 한다(처음에 접두어로 고치려다 이 사실을 확인했다).
SESSION_REDIS_URL = _env("SESSION_REDIS_URL", f"redis://127.0.0.1:{_DEV_REDIS_PORT}/1")

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "sessions": (
        # 위 `_RUNNING_TESTS` 설명 참고. 별칭 이름과 사용법은 같으므로 호출부는 모른다.
        {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"codemit-sessions-{_CHECKOUT_TOKEN}",
        }
        if _RUNNING_TESTS
        else {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": SESSION_REDIS_URL,
        }
    ),
    # 연결된 앱의 호출 상한(ADR-0052, #512) — 강사당 분당 횟수를 센다. gunicorn 워커가
    # 넷이라 프로세스마다 갈리는 LocMem 으로는 상한이 네 배가 되므로 배포에서는 세션과
    # 같은 Redis 를 접두어만 갈라 쓴다. 테스트는 세션과 같은 이유로 LocMem 이다.
    "rate_limits": (
        {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": f"codemit-rate-limits-{_CHECKOUT_TOKEN}",
        }
        if _RUNNING_TESTS
        else {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": SESSION_REDIS_URL,
            "KEY_PREFIX": "rate",
        }
    ),
}

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "sessions"
# Operator 세션 전용 이름 — 참가자 세션이라는 개념 자체가 없으므로(참가자는 JWT 를
# 쿠키에 담아 BFF 가 들고 있다, ADR-0016) 이 쿠키는 언제나 Operator 의 것이다.
SESSION_COOKIE_NAME = "codemit_operator_session"
# Django 기본값과 같지만 명시한다 — 이 쿠키가 돈을 움직이는 권한을 들고 있어서,
# 기본값이 조용히 바뀌는 것에 기대면 안 된다.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# 운영자 앱의 오리진. 배포 환경에서는 명시적으로 준다 — Host 헤더 유도보다 강하고
# 리버스 프록시 구성에 흔들리지 않는다. 비어 있으면 요청이 실제로 도착한 주소로
# 조립한다(dev·테스트).
OPERATOR_WEB_ORIGIN = _env("CODEMIT_OPERATOR_ORIGIN", "")

# 강의실 앱의 공개 오리진(ADR-0052, #512) — 연결된 앱의 OAuth·MCP 메타데이터가 issuer·
# resource 로 내보내는 주소다. backend 는 배포에서 호스트 포트가 없어 바깥에서는 강의실
# 도메인으로만 닿는다. 비어 있으면(dev·테스트) 강의실 BFF 가 실어 보낸 자기 오리진을,
# 그것도 없으면 요청이 도착한 주소를 쓴다(`core.oauth.OAuthResource.public_origin`).
CLASSROOM_WEB_ORIGIN = _env("CODEMIT_CLASSROOM_ORIGIN", "").rstrip("/")

# 공개 앱의 공개 오리진(#870) — 공모전 MCP 의 OAuth·MCP 메타데이터가 issuer·resource 로 내보내는
# 주소다. 비어 있으면(dev·테스트) 공개 앱 BFF 가 실어 보낸 자기 오리진을, 그것도 없으면 요청이
# 도착한 주소를 쓴다(`core.oauth.OAuthResource.public_origin`).
PUBLIC_WEB_ORIGIN = _env("CODEMIT_WEB_ORIGIN", "").rstrip("/")

# 공모전 MCP(#870) — 계정 한 명당 1분에 부를 수 있는 요청 수.
CONTESTS_MCP_CALLS_PER_MINUTE = int(_env("CODEMIT_CONTESTS_MCP_CALLS_PER_MINUTE", "120"))

# 연결된 앱이 강사 한 명당 1분에 부를 수 있는 MCP 요청 수(ADR-0052).
CLASSROOM_MCP_CALLS_PER_MINUTE = int(_env("CODEMIT_CLASSROOM_MCP_CALLS_PER_MINUTE", "120"))
# 그 위에 「제출 소스 열기」 도구 하나가 따로 받는 분당 상한(#518) — 응답 하나가 소스를
# 통째로 싣는 무거운 도구라 전체 상한보다 낮게 둔다(`classroom.mcp_report_tools`).
CLASSROOM_MCP_SOURCE_CALLS_PER_MINUTE = int(_env("CODEMIT_CLASSROOM_MCP_SOURCE_CALLS_PER_MINUTE", "20"))

if IS_DEPLOYED_ENVIRONMENT and not OPERATOR_WEB_ORIGIN:
    # 비어 있으면 Host 헤더 유도로 떨어지는데, 프록시 뒤에서 유도한 오리진은
    # 브라우저가 보낸 https 오리진과 어긋날 수 있고(옛 staging 에서 scheme 이 http 로
    # 잡혀 실제로 그랬다), 그러면 **로그인을 포함한 모든 변경 요청이 403** 이 된다.
    # fail-closed 라 보안 구멍은 아니지만 운영이 통째로 죽는다.
    #
    # 프론트엔드가 CODEMIT_WEB_ORIGIN 에 대해 이미 같은 실패를 겪고 같은 방식으로
    # 막았다(frontend/instrumentation.ts) — 여기서 그 결을 맞춘다.
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET} 인데 "
        "CODEMIT_OPERATOR_ORIGIN 이 비어 있다. 배포 환경에서는 운영자 앱의 오리진을 "
        "명시해야 한다 — Host 헤더 유도는 리버스 프록시 구성에 따라 어긋나고, "
        "그러면 운영자의 모든 변경 요청이 403 이 된다."
    )

# 스토리지 어댑터 (ADR-0005, ADR-0007): "fake"가 기본값이라 아무것도 설정하지 않아도
# 테스트·CI는 MinIO 없이 돈다. dev compose가 backend 컨테이너에만 STORAGE_BACKEND=s3
# 를 주입해 MinIO로 바인딩한다(docker/compose.dev.yaml). prod는 같은 "s3"
# 백엔드가 실제 S3·OCI 엔드포인트를 가리키도록 환경변수만 바꾼다.
STORAGE_BACKEND = _env("STORAGE_BACKEND", "fake")

# DJANGO_SECRET_KEY 가드(위)와 같은 이유다. STORAGE_BACKEND 를 잊고 배포하면
# FakeStorageAdapter가 200과 함께 https://fake-storage.test/... 를 돌려주고, 업로드도
# 다운로드도 겉보기엔 성공한 채 파일만 소리 없이 사라진다. 실제 운영 배포에서는 아예
# 못 뜨게 막는다 — DEBUG가 아니라 CODEMIT_DEPLOYMENT_TARGET을 본다. CI는
# DEBUG=false로 돌면서도 배포된 환경이 아니므로(위 설명) 이 가드에 걸리지 않고
# fake로 테스트를 돌릴 수 있어야 한다.
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(STORAGE_BACKEND):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 STORAGE_BACKEND 가 "
        "fake 다. presigned URL이 200으로 발급되면서 파일이 소리 없이 유실된다. "
        "운영 배포에서는 STORAGE_BACKEND=s3 를 반드시 설정해야 한다."
    )

STORAGE_BUCKET = _env("STORAGE_BUCKET", "codemit-dev")
# 기본값은 호스트에서 직접 돌릴 때를 가정한다(CODEMIT_MINIO_PORT). 컨테이너 안에서는
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
# 두 값이 갈라져도 서버 쪽 동작에는 영향이 없다. prod는 실제 S3/OCI
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

# 공개 이미지 버킷 (#233, ADR-0032) — 이 저장소의 첫 공개 오브젝트가 사는 곳.
# 이름에 "public"과 "images"가 둘 다 들어간다: 이 저장소가 지키는 불변식은
# 「소스는 공개될 수 없다」이고, 그 방어의 마지막 한 겹은 스토리지 콘솔을 연
# 사람이 버킷 이름만 보고 무엇을 넣으면 안 되는지 아는 것이다 — 종류만 말하면
# world-readable이라는 사실이 감춰지고, 위험만 말하면 "공개해도 되는 건 다
# 여기"로 읽힌다.
#
# 이름에 STORAGE_PUBLIC_ENDPOINT_URL 의 "PUBLIC" 을 그대로 재사용하지 않는다 —
# 그 값은 "공개 버킷"이 아니라 "브라우저가 presigned 요청을 쏘는 주소"라는
# 뜻으로 이미 쓰이고 있다(비공개 버킷용). 같은 낱말을 새 값에 쓰면 두 의미가
# 한 접두어를 나눠 갖게 된다.
STORAGE_IMAGES_BUCKET = _env("STORAGE_IMAGES_BUCKET", "codemit-dev-public-images")

# 공개 이미지 버킷의 서명 없는 기준 주소. `storage.public.compose_public_image_url`
# 이 `{이 값}/{object_key}` 로 조립해 API 응답에 싣는다 — presigned URL이 아니므로
# 매 요청 같은 문자열이 나오고, CDN이 그대로 캐시한다(ADR-0032).
#
# DJANGO_SECRET_KEY·STORAGE_BACKEND·CODEMIT_OPERATOR_ORIGIN 가드(위)와 같은 원칙 —
# 배포 환경에서 비면 부팅을 거부한다. 컨테이너가 뜬 채 깨진 이미지 링크만 그리는
# 것보다 정직하게 못 뜨는 편이 낫다.
_storage_images_base_url_env = _env("STORAGE_IMAGES_BASE_URL", "")
if IS_DEPLOYED_ENVIRONMENT and not _storage_images_base_url_env:
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 "
        "STORAGE_IMAGES_BASE_URL 이 비어 있다. 배포 환경에서는 공개 이미지 버킷의 "
        "CDN 기준 주소를 명시해야 한다 — 비면 컨테이너가 뜬 채 이미지 링크가 전부 깨진다."
    )
if _storage_images_base_url_env:
    STORAGE_IMAGES_BASE_URL = _storage_images_base_url_env
else:
    # dev·테스트: 로컬 MinIO의 (브라우저가 여는) 공개 endpoint + 버킷 이름으로
    # 스스로 조립한다 — 설정 없이도 뜬다.
    STORAGE_IMAGES_BASE_URL = f"{STORAGE_PUBLIC_ENDPOINT_URL}/{STORAGE_IMAGES_BUCKET}"

# 업로드는 수백 MB 파일을 올릴 시간을 준다. 다운로드는 짧게 끊어 재사용을 막는다.
STORAGE_UPLOAD_URL_TTL_SECONDS = int(_env("STORAGE_UPLOAD_URL_TTL_SECONDS", "900"))
STORAGE_DOWNLOAD_URL_TTL_SECONDS = int(_env("STORAGE_DOWNLOAD_URL_TTL_SECONDS", "300"))

# 시연 영상 전용 다운로드 수명(#265, ADR-0036) — 화면 안에서 재생하는 동안 URL이
# 살아 있어야 해서 위 기본값(300초)보다 길다. 24시간으로 잡는다(ADR-0036이 정한
# 12~24시간 범위의 상단) — 유출된 링크가 그동안 유효하다는 대가는 있지만, 마감 후
# 전면 공개되는 자료라 그 창이 여는 것은 이미 공개된 것뿐이다. **PlatformPolicy가
# 아니라 설정 상수다** — 운영자가 화면에서 조정하게 하면 실수로 길게 잡는 길이
# 열린다(`submissions.resolvers.SubmissionDownloadTTLResolver`가 이 값을 읽는다).
STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS = int(
    _env("STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS", str(24 * 60 * 60))
)

# 테스트가 override_settings로 특정 target_ref 아래의 write_object 실패를 흉내낼
# 때 쓴다(#220, LLM_FAKE_RAISING_SUBMISSION_IDS와 같은 원칙) — 저장소만 낸
# 제출의 채점 박제(scoring.services)가 저장 실패를 만나면 Score를 만들지 않고
# 다음 스캔에서 재시도하는지를 이 훅으로만 재현할 수 있다.
STORAGE_FAKE_WRITE_RAISING_TARGET_REFS = [
    x for x in _env("STORAGE_FAKE_WRITE_RAISING_TARGET_REFS", "").split(",") if x
]

# target_ref -> 소유자·공개상태 판정 훅(storage.policy.TargetStateResolver).
# #10이 Submission의 소스·데모 가시성 판정을 여기 꽂았다(ADR-0005, ADR-0014).
# 비어 있으면 storage.policy.DenyUnknownTargetResolver 로 fail-closed 한다 — 테스트가
# 이 기본값을 override_settings 로 fake 리졸버로 바꿔치기할 수 있는 이유가 이것이다.
STORAGE_TARGET_RESOLVER = _env(
    "STORAGE_TARGET_RESOLVER", "submissions.resolvers.SubmissionTargetStateResolver"
)

# object_key -> 저장된 content-type 조회 훅(storage.policy.ContentTypeResolver, #241).
# 다운로드 presigned URL의 파일명에 확장자를 붙이는 데 쓴다. 비어 있으면
# storage.policy.UnknownContentTypeResolver 로 "모른다"만 돌려준다 — 그래도
# 파일명 자체는 여전히 만들어진다(확장자만 없다).
STORAGE_CONTENT_TYPE_RESOLVER = _env(
    "STORAGE_CONTENT_TYPE_RESOLVER", "submissions.resolvers.SubmissionContentTypeResolver"
)

# target_ref -> 이 슬롯의 업로드 바이트 상한 훅(storage.policy.MaxUploadSizeResolver,
# #261). 상한이 있으면 presigned URL이 PUT 대신 POST로 발급되어 크기가 서명된
# 정책 조건에 묶인다(ADR-0032/ADR-0035 — PUT은 서명에 크기를 묶을 수단이 없다).
# 비어 있으면 storage.policy.UnboundedMaxUploadSizeResolver 로 항상 상한 없음을
# 돌려준다(기존 PUT 동작 그대로).
STORAGE_MAX_UPLOAD_SIZE_RESOLVER = _env(
    "STORAGE_MAX_UPLOAD_SIZE_RESOLVER", "submissions.resolvers.SubmissionMaxUploadSizeResolver"
)

# target_ref -> 다운로드 URL 수명(초) 훅(storage.policy.DownloadTTLResolver, #265).
# 비어 있으면 storage.policy.DefaultDownloadTTLResolver 로 모든 target_ref에 같은
# 기본 TTL(STORAGE_DOWNLOAD_URL_TTL_SECONDS)을 준다.
STORAGE_DOWNLOAD_TTL_RESOLVER = _env(
    "STORAGE_DOWNLOAD_TTL_RESOLVER", "submissions.resolvers.SubmissionDownloadTTLResolver"
)

# object_key -> 그 파일이 파기됐는가 조회 훅(storage.policy.ObjectDestructionResolver, #262).
# 다운로드 요청이 "보존 기간이 지났다"를 오류가 아니라 정상 응답으로 답하는 데 쓴다.
# 비어 있으면 storage.policy.UnknownDestructionResolver로 항상 "파기되지 않았다"만
# 돌려준다 — 모른다고 다운로드를 막을 이유가 없다(#241의 content-type 리졸버와 같은 방향).
STORAGE_DESTRUCTION_RESOLVER = _env(
    "STORAGE_DESTRUCTION_RESOLVER", "submissions.resolvers.SubmissionAssetDestructionResolver"
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
# **빈 디렉터리라도 있게 한다**(2026-09-21). admin 을 내린 뒤(#46) 이 백엔드에는 모을 정적
# 파일이 없어 `collectstatic` 이 이 디렉터리를 만들지 않는다 — 그러면 WhiteNoise 가
# 프로세스가 뜰 때마다 `No directory at: …/staticfiles/` 경고를 찍었다(prod 에서 gunicorn
# 워커 넷·events 하나, Loki 로 처음 보였다). 쓸 수 없는 파일시스템이면 경고를 그대로 둔다.
try:
    STATIC_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
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
# 질문이기 때문이다(위 CODEMIT_DEPLOYMENT_TARGET 설명 참고). 실제 카카오·GitHub·구글
# API를 부르려면 SOCIAL_AUTH_MODE=real 을 명시해야 한다 — production 배포가
# 그렇게 한다.
SOCIAL_AUTH_MODE = _env("SOCIAL_AUTH_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(SOCIAL_AUTH_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 SOCIAL_AUTH_MODE 가 "
        "fake 다. 운영 배포에서는 SOCIAL_AUTH_MODE=real 을 반드시 설정해야 한다."
    )

# 카카오 OAuth 앱 자격증명 (#95/#96, spec #92). authorize 리다이렉트・code→token
# 교환은 백엔드가 아니라 프론트엔드 BFF가 진다(#95) — 이 프로세스는 이 값들을
# 실제로 쓰지 않는다. 그런데도 여기서 부팅 가드를 세우는 이유는
# CODEMIT_OPERATOR_ORIGIN(#43)과 같다: 배포 스택이 "떴다/안 떴다"를 판정하는
# 신호를 backend 컨테이너 하나로 모아 둬야, 운영자가 스택을 올릴 때 여러
# 컨테이너의 로그를 각각 뒤지지 않고 이 컨테이너의 종료 코드 하나로 "OAuth 앱
# 자격증명이 빠졌다"는 것을 즉시 알 수 있다(frontend/instrumentation.ts가 같은
# 값을 프론트 쪽에서 한 번 더 요구하는 것도 같은 이유 — 두 쪽 다 잊혀야만
# 사고가 나게 한다). SOCIAL_AUTH_MODE=real인데 이 값들이 비면, 카카오 로그인
# 버튼은 컨테이너가 멀쩡히 뜬 채로 항상 실패한다 — #83이 어댑터에 대해 닫은
# 바로 그 실패 모드다.
#
# redirect_uri는 카카오 콘솔에 등록한 값과 한 글자도 다르면 안 된다 — 다르면
# 카카오가 code→token 교환 자체를 거절한다(docker/prod.env.example 참고).
KAKAO_REST_API_KEY = _env("KAKAO_REST_API_KEY", "")
KAKAO_SECRET_KEY = _env("KAKAO_SECRET_KEY", "")
KAKAO_REDIRECT_URI = _env("KAKAO_REDIRECT_URI", "")

if IS_DEPLOYED_ENVIRONMENT:
    _missing_kakao_settings = [
        name
        for name, value in (
            ("KAKAO_REST_API_KEY", KAKAO_REST_API_KEY),
            ("KAKAO_SECRET_KEY", KAKAO_SECRET_KEY),
            ("KAKAO_REDIRECT_URI", KAKAO_REDIRECT_URI),
        )
        if not value
    ]
    if _missing_kakao_settings:
        raise ImproperlyConfigured(
            f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 다음 카카오 OAuth "
            f"자격증명이 비어 있다: {', '.join(_missing_kakao_settings)}. authorize "
            "리다이렉트・code→token 교환은 프론트엔드 BFF가 지지만(#95), 이 값들이 없으면 "
            "로그인 버튼이 컨테이너가 뜬 채로 항상 실패한다."
        )

# --- 로깅 -------------------------------------------------------------------
#
# **500 이 컨테이너 로그에 보여야 한다.** Django 기본 로깅에서 `django.request` 의
# ERROR 는 `mail_admins` 로만 가고, `django` 로거의 콘솔 핸들러는 `DEBUG=True` 일
# 때만 붙는다 — 그래서 `DEBUG=False` 인 배포에서는 500 이 나도 `docker compose
# logs` 에 **한 줄도** 남지 않는다.
#
# 옛 staging 에서 본인확인 500 을 쫓을 때 실제로 그랬다: 로그는 멀쩡한데 사용자만
# 500 을 받았고, 원인(VERIFICATION_ENCRYPTION_KEY 가 Fernet 키가 아니었다)은 같은
# 요청을 손으로 재현해서야 나왔다. 우리 코드가 남기는 logger.error 는 보이는데
# 처리되지 않은 예외만 안 보이는 상태라, 「로그에 없으니 백엔드는 무사하다」는
# 잘못된 결론까지 나왔다.
#
# `disable_existing_loggers: False` — 이 설정이 앱 로거(verification.adapters 등)를
# 끄지 않도록 한다. 그 로거들은 전파로 여기 핸들러에 닿는다.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
        # 배포 환경은 한 줄 JSON(2026-09-21, core/json_logging.py) — prod 로그를 모으는
        # Loki 가 필드로 거를 수 있게 한다. dev 는 사람이 읽는 위 포맷 그대로다.
        "json": {"()": "core.json_logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if IS_DEPLOYED_ENVIRONMENT else "standard",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # 처리되지 않은 예외가 여기로 온다 — 이 한 줄이 이 블록의 이유다.
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # 요청 로그는 gunicorn 이 아니라 Django 가 낼 필요가 없다 — 시끄럽기만 하다.
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Verification (ADR-0011, ADR-0007) ------------------------------------
# 본인확인 어댑터도 같은 원칙: 기본값은 항상 fake이고, production 배포만
# real을 명시한다.
VERIFICATION_ADAPTER_MODE = _env("VERIFICATION_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(VERIFICATION_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 "
        "VERIFICATION_ADAPTER_MODE 가 fake 다. 운영 배포에서는 실제 "
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

# **비어 있지 않은 것만으로는 부족하다.** 옛 staging 에서 실제로 겪었다 — 사람이 이
# 칸에 아무 문자열이나 채웠고, 「비어 있는지」만 보는 가드가 통과시켰다. 컨테이너는
# 멀쩡히 떴고, 본인확인이 **성공해서 실명을 암호화하려는 순간**
# `Fernet key must be 32 url-safe base64-encoded bytes` 로 500 이 났다. 사용자에게는
# 본인확인이 깨진 것으로만 보이고, 원인은 벤더 응답 어디에도 없다 — 이 저장소는
# 그 실패 모양을 이미 거부하기로 했다(CLAUDE.md, #83 의 어댑터 가드와 같은 규율).
#
# dev 도 함께 검사한다. 값을 **주지 않는** 것은 dev 에서 정상이고(위의 fallback 이
# 받는다), 여기서 걸리는 것은 「줬는데 쓸 수 없는 값」뿐이다 — 그건 어느 환경에서도
# 오타가 아니라 고장이다.
try:
    Fernet(_verification_key.encode() if isinstance(_verification_key, str) else _verification_key)
except (ValueError, TypeError) as _fernet_exc:
    raise ImproperlyConfigured(
        "VERIFICATION_ENCRYPTION_KEY 가 Fernet 키가 아니다. 실명·생년월일·CI/DI 암호화에 "
        "쓰이므로 본인확인이 성공하는 순간 500 이 난다. "
        "`python -c \"from cryptography.fernet import Fernet; "
        'print(Fernet.generate_key().decode())"` 로 생성한 값을 넣어라.'
    ) from _fernet_exc

VERIFICATION_ENCRYPTION_KEY = _verification_key

# --- 결제 · Escrow 예치 (#9, ADR-0007) --------------------------------------
# PG 어댑터도 같은 원칙: 기본값은 항상 Fake PG다 — 웹훅 재전송·타임아웃·순서 뒤바뀜을
# 네트워크 없이 결정적으로 주입할 수 있다. production은 토스 "실물"에
# PAYMENT_ADAPTER_MODE=real로 명시한다(ADR-0008). 샌드박스냐 실물이냐는 이 모드 값이
# 아니라 함께 주입하는 토스 자격증명·엔드포인트가 어디를 가리키는지로 갈린다.
PAYMENT_ADAPTER_MODE = _env("PAYMENT_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(PAYMENT_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 PAYMENT_ADAPTER_MODE 가 "
        "fake 다. 운영 배포에서는 실제 PG 어댑터의 dotted path를 반드시 "
        "설정해야 한다."
    )

# 토스페이먼츠 결제 어댑터(#87)가 쓰는 자격증명. `payments.adapters_toss.TossPGAdapter`가
# 인자 없이 생성되는 시점(`core.adapters.resolve_adapter`)에 `TOSS_API_SECRET_KEY`가
# 비어 있으면 스스로 거부한다 — 여기서 부팅을 막지 않는 이유는 dev에서는
# PAYMENT_ADAPTER_MODE가 기본값 "fake"라 이 클래스 자체가 생성되지 않기 때문이다.
# 배포 환경에서 PAYMENT_ADAPTER_MODE가 이 클래스를 가리키는데 키가 비어 있으면
# `core.adapters.check_adapter_mode`가 어댑터 생성 자체가 실패하는 것을 잡아
# `core.E002`로 부팅을 거부한다(AC: 자격증명 누락은 배포에서 부팅 실패다).
#
# 환경별로 실제 주입되는 변수 이름이 다르다(#87 코드리뷰 지적 6) — dev는 저장소
# 루트 .env가 이미 `TOSS_API_SECRET_KEY`라는 이름을 쓰고, prod compose는
# `TOSS_LIVE_SECRET_KEY`로 못박아 뒀다 — 실물 키는 그 이름으로만 들어온다. 두 이름 중
# 먼저 채워진 값을 쓴다 — 환경마다 하나만 채워지므로 순서는 충돌하지 않는다. 옛
# staging 의 샌드박스 이름 `TOSS_SANDBOX_SECRET_KEY` 는 staging 과 함께 거뒀다(#844 —
# prod compose 는 그 이름을 컨테이너에 넘기지 않았다).
TOSS_API_SECRET_KEY = _env("TOSS_API_SECRET_KEY", "") or _env("TOSS_LIVE_SECRET_KEY", "")
# 벤더가 문서화한 API 버전 헤더값(`TossPayments-api-version`). dev의 테스트 키는
# 2022-11-16을 쓴다 — 값 자체는 벤더 사실이라 코드에 하드코딩하지 않고 환경에서 읽는다.
TOSS_API_VERSION = _env("TOSS_API_VERSION", "2022-11-16")

# 토스 지급대행 셀러 등록·수정·지급 요청 세 API가 요구하는 JWE 암호화 키(#57).
# 64자 hex 문자열(A256GCM용 32바이트) — `TossPayments-api-security-mode:
# ENCRYPTION`을 쓰는 요청의 본문을 이 키로 직접(alg=dir) 암호화하고, 같은 키로
# `payout.changed`/`seller.changed` 웹훅 서명(HMAC-SHA256)도 검증한다
# (`payouts.adapters_toss` 참고). TOSS_API_SECRET_KEY와 마찬가지로 dotted path가
# 실물 어댑터를 가리킬 때만(PAYOUT_ADAPTER_MODE/SELLER_ADAPTER_MODE) 이 값이
# 실제로 쓰인다 — dev 기본값(fake)에서는 비어 있어도 아무 문제가 없다.
TOSS_API_SECURE_KEY = _env("TOSS_API_SECURE_KEY", "")

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
CELERY_BROKER_URL = _env("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = _env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TIMEZONE = TIME_ZONE
# **dev·CI 는 태스크를 큐에 넣는 자리에서 그대로 돌린다**(#582, ADR-0056) — 공모전 이미지 최적화 같은
# 일반 태스크가 워커 없이 도는 모양이다. 강의실 채점은 Celery 가 아니라 grader 가 한다(#584,
# 아래 `CLASSROOM_GRADER_*`). dev compose 의 celery-worker·beat 는 이 값을 false 로 받는다 —
# beat 가 쏜 태스크를 beat 자신이 돌리면 안 된다.
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", not IS_DEPLOYED_ENVIRONMENT)
if IS_DEPLOYED_ENVIRONMENT and CELERY_TASK_ALWAYS_EAGER:
    raise ImproperlyConfigured(
        "배포 환경에서 CELERY_TASK_ALWAYS_EAGER 가 켜져 있다 — 태스크가 워커가 아니라 "
        "요청 안에서 돌게 된다(#582). 값을 지운다."
    )

# --- 강의실 채점 grader (#584, ADR-0059) ---------------------------------------------
# `manage.py grader` 상주 프로세스가 DB 의 큐(`scoring_queued_at`)에서 시도를 집어 비동기로
# 채점한다 — 브로커·채점 큐가 없다. 상한은 그 프로세스 안의 값이다.
#
# 바깥(벤더·강사 서버)으로 나가는 호출의 한도 — 강사가 적은 서버는 믿지 않는다.
# 응답 본문은 이 크기까지만 읽고 넘으면 끊는다(끝없이 흘려 메모리를 채우는 서버, 「닿았음」으로 센다).
SAFE_OUTBOUND_RESPONSE_MAX_BYTES = int(_env("SAFE_OUTBOUND_RESPONSE_MAX_BYTES", str(2 * 1024 * 1024)))
# 연결 단계만의 타임아웃(초) — 전체 타임아웃(채점은 180초)과 따로다. 응답 없는 서버가 슬롯을 길게 쥐지 않게.
SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS = float(_env("SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS", "10"))
# grader 의 소스 읽기 스레드 풀(스토리지·GitHub clone·문법 검사 — **DB 를 쓰지 않는다**). DB 일은 스레드
# 하나(`grader-db`)에서만 해 DB 연결이 정확히 1개다 — 여럿으로 늘리면 연결도 여럿이 되므로 설정값이 아니다.
# grader 가 잠긴 행을 기다리는 상한(밀리초) — 결과 쓰기·임대 연장이 이 안에 잠금을 못 얻으면 포기하고
# 다시 한다(옛 채점 워커가 행 잠금을 쥔 채 벤더를 기다리는 동안 DB 스레드 하나가 서 버리지 않게).
CLASSROOM_GRADER_LOCK_TIMEOUT_MS = int(_env("CLASSROOM_GRADER_LOCK_TIMEOUT_MS", "2000"))
# 결과 쓰기가 잠금에 막힐 때 같은 결과를 다시 쓰려고 시도하는 총 시간(초). 넘으면 결과를 버리고 임대
# 만료 뒤 다시 줍는다.
CLASSROOM_GRADER_LOCK_RETRY_SECONDS = int(_env("CLASSROOM_GRADER_LOCK_RETRY_SECONDS", "30"))
CLASSROOM_GRADER_SOURCE_THREADS = int(_env("CLASSROOM_GRADER_SOURCE_THREADS", "8"))
CLASSROOM_GRADER_GLOBAL_LIMIT = int(_env("CLASSROOM_GRADER_GLOBAL_LIMIT", "64"))
CLASSROOM_GRADER_PER_CONNECTION_LIMIT = int(_env("CLASSROOM_GRADER_PER_CONNECTION_LIMIT", "8"))
# 큐를 읽는 간격(초) — 제출 뒤 채점이 시작되기까지의 최대 지연이다. dev·CI(e2e 시험 하나 3초)도
# 같은 값이라 운영과 같은 길을 탄다.
CLASSROOM_GRADER_POLL_SECONDS = float(_env("CLASSROOM_GRADER_POLL_SECONDS", "0.5"))
# grader 의 LLM 지표 엔드포인트 포트(#585) — 0 이면 열지 않는다(dev·시험). 배포 compose 가 9102 를 준다.
CLASSROOM_GRADER_METRICS_PORT = int(_env("CLASSROOM_GRADER_METRICS_PORT", "0"))
# pytest 만 켠다 — 큐에 넣는 자리에서 한 시도를 동기로 채점해 상주 프로세스 없이 시험이 결과를
# 본다. 배포·dev·e2e 는 항상 꺼져 있고 `grader` 서비스가 채점한다.
CLASSROOM_GRADER_INLINE = _RUNNING_TESTS

# --- DB 연결 사용률 경고 (core.db_connection_scan, #455/#453) ------------------------
# 2026-09-18 prod 장애("too many clients already")의 재발 방지 — 한도에 가까워지면
# 사람이 500 을 보기 전에 오류 수집기로 먼저 알린다.
#
# 어느 DB 별칭을 볼지도 설정이다: 지금은 "default"(dev·CI·prod가 보는
# 그 Postgres) 하나뿐이지만, 연결 풀러(pgbouncer)가 앞에 서면(#458) 앱이 보는
# "default" 연결은 풀러가 흡수한 뒤의 것이라 실제 서버 연결 수를 보여주지 않는다 —
# 그때는 풀러를 건너뛰는 별도 DATABASES 별칭을 추가하고 이 값만 그 이름으로 바꾸면
# 된다. 이 스캔의 코드는 바뀌지 않는다(스코프 밖 — #457/#458이 풀러 자체를 놓는다).
DB_CONNECTION_MONITOR_ALIAS = _env("DB_CONNECTION_MONITOR_ALIAS", "default")
# 사용률(사용 중 연결 ÷ 상한)이 이 값 이상이면 경고를 보낸다.
DB_CONNECTION_ALERT_THRESHOLD = float(_env("DB_CONNECTION_ALERT_THRESHOLD", "0.8"))
# 임계를 넘은 상태가 이어지는 동안 같은 경고를 다시 보내기까지 최소 간격 — 스캔 자기
# 주기(기본 60초)보다 길어야 "1분마다 쏟아진다"는 문제가 사라진다.
DB_CONNECTION_ALERT_INTERVAL_SECONDS = int(_env("DB_CONNECTION_ALERT_INTERVAL_SECONDS", "900"))

if _RUNNING_TESTS:
    # pytest 에는 Redis 가 없다(위 세션 캐시와 같은 전제, "테스트는 서로를 밟지
    # 않는다"). 태스크는 dev·CI 와 같이 eager 로 큐에 넣는 자리에서 돈다(#582) —
    # 환경변수가 무엇이든 시험은 그 모양으로 고정한다. 브로커는 혹시 eager 를 끈
    # 시험이 발행해도 Redis 를 찾지 않게 kombu 의 인메모리 트랜스포트로 둔다.
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"

# 비밀번호 해시는 일부러 느리다(PBKDF2 수십만 회) — **배포 환경에서만 그렇게 둔다**
# (2026-10-02). dev·CI·pytest 는 빠른 해셔로 새 해시를 만든다: 운영자 계정 시드 한
# 번이 서버에서 1.06초, 운영자 앱을 거친 로그인 한 번이 0.55초라 그것만으로 e2e
# 시험 하나 3초 한도를 넘었고, pytest 의 운영자 시험 대부분이 시험 하나 CPU 1초
# 한도(`tests/conftest.py`)를 넘은 원인도 이것이었다. 시험이 보는 것은 「맞는
# 비밀번호로만 들어간다」이지 해시 알고리즘의 강도가 아니다(Django 문서가 테스트에
# 권하는 그대로). 판정은 다른 배포 가드와 같은 `IS_DEPLOYED_ENVIRONMENT` 라
# prod 는 Django 기본값(PBKDF2)을 그대로 쓴다 — `tests/
# test_deployment_config.py` 가 고정한다. PBKDF2 를 둘째로 남기는 이유는 이미 그
# 해시로 저장된 dev 계정도 그대로 로그인되게 하려는 것이다.
if not IS_DEPLOYED_ENVIRONMENT:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
        "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    ]

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
            f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 "
            f"{_notification_setting_name}={_notification_adapter_path!r} 가 Fake 구현체다. "
            "운영 배포에서는 실제 벤더 어댑터의 dotted path를 반드시 "
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

# 알리고(Aligo) SMS/LMS 실물 어댑터(#51)가 쓰는 자격증명. 토스 어댑터
# (TOSS_API_SECRET_KEY)와 같은 원칙 — 여기서 부팅을 막지 않는다. dev는
# NOTIFICATION_SMS_ADAPTER/LMS_ADAPTER가 기본값 "fake"라 이 클래스 자체가
# 생성되지 않기 때문이다. 배포 환경에서 이 클래스를 가리키는데 값이 비어
# 있으면 `core.adapters.check_adapter_mode`가 어댑터 생성 실패를 잡아
# `core.E002`로 부팅을 거부한다.
ALIGO_API_KEY = _env("ALIGO_API_KEY", "")
ALIGO_USER_ID = _env("ALIGO_USER_ID", "")
ALIGO_SENDER_PHONE_NUMBER = _env("ALIGO_SENDER_PHONE_NUMBER", "")

# --- AI 채점 어댑터 (#12, ADR-0006, ADR-0007, ADR-0014) -----------------------------
#
# PAYMENT_ADAPTER_MODE·STORAGE_BACKEND와 같은 원칙: 기본값은 항상 fake다. dev/CI는
# 네트워크 없이 결정적으로 채점 플로우 전체를 돈다. production 배포만
# LLM_ADAPTER_MODE에 실제 어댑터의 dotted path(또는 향후 등록될 별칭)를 명시한다.
LLM_ADAPTER_MODE = _env("LLM_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(LLM_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 LLM_ADAPTER_MODE 가 "
        "fake 다. Score가 실제 채점 없이 만들어지면 Distribution 대상 판정이 통째로 "
        "무효가 된다. 운영 배포에서는 실제 LLM 어댑터를 반드시 설정해야 한다."
    )

# --- 강의실 채점 어댑터 모드 (#340, ADR-0043) ---------------------------------------
#
# `classroom.scoring`은 강사 본인의 키로 `OpenAIScoringAdapter`를 직접 생성한다
# (LLM_ADAPTER_MODE·get_adapter()를 거치지 않는다, `classroom/scoring.py` 모듈
# docstring) — "누구 키로 도는가"는 이 설정이 건드리지 않는다. 이 설정이 가르는
# 것은 "그 키로 실제로 네트워크에 나가는가" 하나뿐이다: 기본값 fake는 배포되지
# 않은 환경(dev·CI)에서 네트워크 없이 결정적으로 강의실 채점을 끝낸다
# (`classroom.scoring.FakeClassroomScoringAdapter`) — 가짜 키를 넣으면 실제
# OpenAI로 나가고 진짜 키를 넣으면 돈이 나가던 문제(#340)를 없앤다.
# production은 이 값을 실제 어댑터의 dotted path로 반드시 설정해야 한다 — 강사
# 본인의 키로 실물 OpenAI를 쓰는 배포 환경의 원칙은 이 설정으로 바뀌지 않는다.
CLASSROOM_SCORING_ADAPTER_MODE = _env("CLASSROOM_SCORING_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(CLASSROOM_SCORING_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 "
        "CLASSROOM_SCORING_ADAPTER_MODE 가 fake 다. 강의실 ClassroomScore가 실제 채점 "
        "없이 만들어지면 참여자에게 통과·미통과가 보증 없이 내려간다. 운영 "
        "배포에서는 실제 LLM 어댑터의 dotted path를 반드시 설정해야 한다."
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
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 "
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE 가 fake 다. 운영 배포에서는 "
        "실제 LLM 어댑터를 반드시 설정해야 한다."
    )

# 테스트가 override_settings로 특정 contest_id의 대화 응답 실패를 흉내낼 때 쓴다
# (LLM_FAKE_RAISING_SUBMISSION_IDS와 같은 원칙).
LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS = [
    int(x) for x in _env("LLM_REQUIREMENT_CHAT_FAKE_RAISING_CONTEST_IDS", "").split(",") if x
]

# --- 소스 변환 플러그인 (#496, #495) -----------------------------------------------
#
# 소스 선별이 UTF-8로 못 읽은 파일을 넘겨받아 채점용 텍스트로 바꾸는 플러그인의
# dotted path 목록(쉼표로 구분, 적힌 순서대로 묻는다). 목록이 비면 읽을 수 없는
# 파일은 예전처럼 버려진다. 쓸 수 없는 경로는 부팅 검사
# (`core.source_converters.check_source_converters`)가 거절한다.
#
# dev·CI 기본값에는 Packet Tracer(#497)가 켜져 있고, **배포 환경의 기본값은 빈
# 목록이다** — Cisco 약관 검토(#498)가 끝나기 전에는 prod 에서 켜지 않는다.
# `_env` 가 아니라 `os.environ.get` 인 이유: 빈 문자열을 「미설정」이 아니라 「빈
# 목록」으로 읽어야 compose 가 명시적으로 끌 수 있다.
_DEFAULT_SOURCE_CONVERTERS = (
    "" if IS_DEPLOYED_ENVIRONMENT else "core.source_converters.packet_tracer.PacketTracerConverter"
)
SOURCE_CONVERTERS = [
    p.strip()
    for p in os.environ.get("SOURCE_CONVERTERS", _DEFAULT_SOURCE_CONVERTERS).split(",")
    if p.strip()
]

# --- GitHub 저장소 어댑터 (#193, ADR-0007, ADR-0027) --------------------------------
#
# LLM_ADAPTER_MODE와 같은 원칙: 기본값은 항상 fake다. dev/CI는 네트워크 없이
# 결정적으로 공개 여부 판정·clone을 흉내낸다. production 배포만
# GITHUB_ADAPTER_MODE에 실제 어댑터의 dotted path를 명시한다 — 이 값이
# fake이거나 임포트되지 않으면 `core.adapters.check_adapter_mode`(#83)가 부팅을
# 거부한다(여섯 값이던 것이 이제 일곱이다).
GITHUB_ADAPTER_MODE = _env("GITHUB_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(GITHUB_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 GITHUB_ADAPTER_MODE 가 "
        "fake 다. 운영 배포에서는 실제 GitHub 어댑터의 dotted path를 "
        "반드시 설정해야 한다."
    )

# 실물 어댑터가 GitHub REST API를 칠 때 쓰는 선택적 자격증명. 없어도 동작한다 —
# 공개 저장소 조회·zipball 다운로드는 인증 없이도 가능하고(익명 요청은 시간당
# 요청 한도만 더 낮다), 참가자의 자격증명을 platform이 보관하지 않는다는
# ADR-0027의 결정과 다른 층위다(이건 platform 자신의 GitHub App/PAT다).
GITHUB_API_TOKEN = _env("GITHUB_API_TOKEN", "")

# 테스트/dev가 fake 어댑터의 clone 결과를 결정적으로 채우고 싶을 때 쓴다 —
# {repository_url: {path: content}} 모양. 없는 URL은
# `repositories.adapters.FakeGitHubAdapter`의 기본 파일로 응답한다.
GITHUB_FAKE_REPO_FILES: dict = {}

# --- 이벤트 버스 (ADR-0046) ---------------------------------------------------------
#
# 강의실이 새로고침 없이 화면을 갱신하는 데 쓰는 실시간 신호(`core.events`).
# 다른 `*_ADAPTER_MODE`와 같은 원칙으로 기본값은 항상 fake다. #380이 두 env
# 예시 파일(`docker/prod.env.example`)에 실제
# 값(`core.events_redis.RedisEventBus`)을 채우는 것과 같은 커밋에서 이 부팅
# 가드를 더한다 — 그 전에 가드만 먼저 걸면 서버의 `.env` 가 아직 이 값을
# 모르는 채로 다음 자동 배포가 부팅을 거부하며 죽는다(`core/events.py` 모듈
# docstring 참고).
EVENT_BUS_ADAPTER_MODE = _env("EVENT_BUS_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(EVENT_BUS_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 EVENT_BUS_ADAPTER_MODE 가 "
        "fake 다. 강의실 화면이 실시간 신호를 받지 못해 조용히 폴링에만 의존하게 된다. "
        "운영 배포에서는 실제 이벤트 버스 어댑터(core.events_redis.RedisEventBus)의 "
        "dotted path를 반드시 설정해야 한다."
    )
# Operator 세션(DB 1)·Celery 브로커(DB 0)와 같은 Redis 인스턴스, 다른 DB
# 인덱스(2) — 세 용도가 키를 섞지 않게 한다(SESSION_REDIS_URL 주석과 같은 이유).
EVENT_BUS_REDIS_URL = _env("EVENT_BUS_REDIS_URL", f"redis://127.0.0.1:{_DEV_REDIS_PORT}/2")

# --- 운영 지표 1분 집계 (#827, `ops_metrics`) -----------------------------------------
#
# 호출 지점이 그 분(UTC 분 시작 시각)의 Redis 해시에 더하기만 하고, celery beat 가 1분마다 닫힌 분을
# DB 행으로 옮긴다. 세션(1)·브로커(0)·이벤트 버스(2)와 같은 인스턴스, **DB 인덱스 3** — 키를 섞지 않고,
# 이 인덱스를 통째로 훑어도(SCAN) 다른 용도의 키를 보지 않는다. 시험은 프로세스 안 흉내 저장소를 쓴다
# (위 세션 캐시와 같은 이유 — 같은 Redis 를 여러 체크아웃이 나눠 쓴다).
OPS_METRICS_REDIS_URL = _env("OPS_METRICS_REDIS_URL", f"redis://127.0.0.1:{_DEV_REDIS_PORT}/3")
OPS_METRICS_STORE = "memory" if _RUNNING_TESTS else "redis"
#: 분 해시의 TTL — flush 가 멈춰도(beat 가 죽어도) 사흘 안에 되살리면 잃지 않는다. 그보다 길면 버린다.
OPS_METRICS_KEY_TTL_SECONDS = 3 * 24 * 3600
#: grader 생존 신호(`ops:heartbeat:grader`)의 TTL — 30초마다 쓴다. 경보(#830)는 「3분 넘게 없음」을 보므로
#: 그보다 길게 둬 「마지막으로 산 시각」을 읽을 수 있게 한다. 키가 없으면 10분 넘게 소식이 없는 것이다.
OPS_METRICS_HEARTBEAT_SECONDS = 30
OPS_METRICS_HEARTBEAT_TTL_SECONDS = 600
#: 집계 행을 두는 날 수 — 매일 새벽 정리 작업이 이보다 오래된 행을 지운다.
OPS_METRICS_RETENTION_DAYS = 90
#: 요청 지표(#828)를 프로세스 안에 모았다가 Redis 로 보내는 간격(초) — 요청마다 왕복하면 116~300µs 가 붙고
#: Redis 가 멈추면 0.25초가 요청마다 붙는다(`ops_metrics.request_buffer`). SIGKILL 된 워커는 이만큼을 잃는다.
#: 시험은 0(버퍼 없이 바로 더한다).
OPS_METRICS_REQUEST_FLUSH_SECONDS = 0 if _RUNNING_TESTS else 5
#: 운영 경보(#830, `ops_metrics.alerts`)를 보낼 디스코드 웹훅 — 비면 보내지 않고 상태만 기록한다(조용히 꺼짐).
#: 값은 배포 .env 에만 있다. 콘솔 링크는 `OPERATOR_WEB_ORIGIN` + `/ops` 다.
OPS_ALERT_DISCORD_WEBHOOK_URL = _env("OPS_ALERT_DISCORD_WEBHOOK_URL", "")
#: 웹훅 한 번의 소켓 한도(초) — 검사는 1분마다 돌고 규칙이 여섯이라 최악에도 1분 안에 끝난다.
OPS_ALERT_DISCORD_TIMEOUT_SECONDS = 5

# --- Handover · Escrow 해제 (#14, ADR-0003/0004/0005/0014) --------------------------
#
# 인도 승인 기간은 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.handover_acceptance_period_days`로 옮겼다.

# --- Payout 실행 (#15, ADR-0004/0008) -------------------------------------------------
#
# 토스 지급대행 어댑터도 PAYMENT_ADAPTER_MODE와 같은 원칙: 기본값은 항상 Fake다.
# production은 토스 지급대행 실물에 real로 바인딩한다(ADR-0008).
PAYOUT_ADAPTER_MODE = _env("PAYOUT_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(PAYOUT_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 PAYOUT_ADAPTER_MODE 가 "
        "fake 다. 운영 배포에서는 실제 지급대행 어댑터의 dotted path를 "
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
# 환경변수로 읽었지만 어느 배포에도 그 값을 준 적이 없어 실질적으로 코드
# 상수였고, 요율은 환경의 성질이 아니라 사업 정책이다 — 환경마다
# 달라지면 그것은 설정이 아니라 버그다. `policies.models.PlatformPolicy`(DB 단일
# 행)가 대신하고, `policies.scope.current_policy()`로 읽는다. 두 경로를
# 남기지 않는다 — CSRF 방어를 두 기계로 두었다가 한쪽 발급처가 사라져 영구 403이
# 된 사고가 이 저장소에 있다.

# --- Seller(지급대행사 수취인) 등록 어댑터 (#50, ADR-0007, ADR-0020) -------------------
#
# PAYOUT_ADAPTER_MODE와 같은 원칙: 기본값은 항상 fake다. 실제 토스 지급대행 셀러
# 등록은 이 티켓 범위 밖이다(#57) — production에서만 real dotted path를
# 요구한다.
SELLER_ADAPTER_MODE = _env("SELLER_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(SELLER_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 SELLER_ADAPTER_MODE "
        "가 fake 다. 운영 배포에서는 실제 Seller 등록 어댑터의 dotted "
        "path를 반드시 설정해야 한다."
    )

# 지급대행 주간 한도는 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.seller_weekly_limit_amount`로 옮겼다. **이
# 값은 우리 정책이 아니라 토스가 정한 사실**이다(ADR-0020) — 같은 행에 있어도
# 우리 판단으로 올릴 수 있는 값이 아니다.

# --- 공모전 검색 어댑터 (#449, 부모 #444 스펙, ADR-0007) ------------------------------
#
# 다른 `*_ADAPTER_MODE`와 같은 원칙으로 기본값은 항상 fake다 — pytest·CI·dev는
# `contests.search.FakeContestSearchAdapter`(DB 포함 검색)로 네트워크 없이 돈다.
#
# **설정 이름은 코디네이터가 2026-09-17에 고정했다**(#449 코멘트) — prod의
# `.env`가 이미 이 이름과 값을 쓴다. 실물은 dotted path
# `contests.search_opensearch.OpenSearchContestSearch`(모듈
# `contests/search_opensearch.py`, #450이 만든다)이고, 그 어댑터의 접속 주소는
# 별도 설정 `OPENSEARCH_URL`이다(prod 는 `http://search:9200`) — 이 설정은
# #450이 더한다.
#
# 실물 어댑터가 이제 있다(#450, `contests.search_opensearch.
# OpenSearchContestSearch`) — 다른 `*_ADAPTER_MODE`와 같은 원칙으로 배포
# 환경에서 fake로 남으면 부팅을 거부한다(#451). 임포트 가능 여부·계약 충족
# 여부는 `core.adapters.check_adapter_mode`가 `django.core.checks`로 등록되어
# 따로 확인한다(`contests/checks.py`의 `check_search_adapter_mode`) — 아래는
# "fake" 별칭 자체만 여기서 즉시 막는다(다른 어댑터들과 같은 두 갈래).
SEARCH_ADAPTER_MODE = _env("SEARCH_ADAPTER_MODE", "fake")
if IS_DEPLOYED_ENVIRONMENT and _is_fake_adapter_binding(SEARCH_ADAPTER_MODE):
    raise ImproperlyConfigured(
        f"CODEMIT_DEPLOYMENT_TARGET={CODEMIT_DEPLOYMENT_TARGET!r} 인데 SEARCH_ADAPTER_MODE 가 "
        "fake 다. 운영 배포에서는 실제 검색 어댑터의 dotted path"
        "(contests.search_opensearch.OpenSearchContestSearch)를 반드시 설정해야 한다."
    )

# 실물 어댑터(`contests.search_opensearch.OpenSearchContestSearch`, #450)의 접속
# 주소다. prod는 `http://search:9200`(compose 서비스 이름 `search`,
# #451이 그 서비스를 띄운다). dev `search` 프로필(docker/compose.dev.yaml)은
# 호스트 포트로도 내므로 컨테이너 밖(pytest 없는 수동 확인·live 테스트)에서는
# `CODEMIT_SEARCH_PORT`로 붙는다 — 기본값은 컴포즈 내부망 주소다.
OPENSEARCH_URL = _env("OPENSEARCH_URL", "http://127.0.0.1:9200")

# --- Distribution (#16, ADR-0003/0004/0006) -------------------------------------------
#
# 배분 대기 기간은 더 이상 여기 없다(#78, ADR-0023) —
# `policies.models.PlatformPolicy.distribution_wait_days`로 옮겼다.

# --- Notification 연결: Contest 라이프사이클 (#19, ADR-0009/0010) ----------------------
#
# 마감·심사기간 종료·Distribution이 다가올 때 Sponsor·Developer에게 미리 알린다.
# 실제 발송(즉시/야간 연기/대체발송)은 notifications.services(#18)가 그대로
# 담당한다 — 여기서는 "언제 그 알림을 만들 것인가"만 정한다
# (contests.lifecycle_notifications, #465 전까지는 notifications.lifecycle).
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
# 고친다 — dev·CI는 HTTP로도 돌아야 하므로, 이 하드닝은
# IS_PRODUCTION_DEPLOYMENT에만 켠다. fake 어댑터가 섞이지 않게 막는
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

# --- 오류 수집 (GlitchTip, 2026-09-16) ------------------------------------
# `SENTRY_DSN` 이 있을 때만 켜진다 — dev·CI 는 주지 않으므로 꺼진 채로 돈다.
# 무엇을 보내지 않는지는 core/observability.py 의 모듈 docstring 이 들고 있다.
from core.observability import configure_sentry  # noqa: E402

SENTRY_ENABLED = configure_sentry()

#: compose 네트워크 안에서만 풀리는 서비스 이름 — 이 이름으로 들어온 요청은 TLS 프록시를 거친
#: 것으로 친다(core.internal_hosts). 공개 도메인은 여기 넣지 않는다.
INTERNAL_SERVICE_HOSTS = ("backend", "events")
