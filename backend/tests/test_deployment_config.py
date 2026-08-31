"""배포 환경 부팅 가드 (#23, ADR-0007).

이 프로젝트의 유일한 테스트 시임은 HTTP지만, 이 파일이 검증하는 대상은 요청을
받기도 전에 끝나는 부팅 시점의 `ImproperlyConfigured`다 — HTTP로는 원천적으로
도달할 수 없다. `config/settings.py`는 모듈 임포트 시점에 가드를 평가하므로, 같은
프로세스 안에서 `override_settings`로 재현할 수 없다(이미 임포트가 끝난 뒤라
`LAURIO_DEPLOYMENT_TARGET` 분기를 다시 태울 방법이 없다). 그래서 `storage/checks.py`가
`manage.py check`(부팅 파이프라인 그 자체)로 검증되는 것과 같은 원칙을,
서브프로세스로 `manage.py check`를 직접 실행해 종료 코드와 에러 메시지를 확인하는
방식으로 적용한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from django.test import override_settings

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 50자 이상 · 고유 문자 5종 이상 · "django-insecure-" 접두 아님 — production
# SECRET_KEY 강도 가드(config/settings.py)를 통과하는 값.
_STRONG_SECRET_KEY = "prod-Kx8f3Kq0mN2pR7tYcVbGhJkLdSaWeUiOaXzCvBnMqWeRtYuIoPaSdFgHjKlZxCvB"

# dev의 fallback과 같은, 이미 저장소에 공개된 고정 Fernet 키(config/settings.py 참고) —
# 새로 유출되는 비밀이 아니다. 부팅 가드는 이 값의 "강도"가 아니라 "비어 있는지"만
# 본다(SECRET_KEY와 달리 production 전용 강도 검사가 없다).
_FERNET_KEY = "A0crfksMrBmbSY37jIyOwcPRFpK9rc_eIaNnL89lIfo="


def _base_env(*, target: str, secret_key: str) -> dict[str, str]:
    """`target`("staging"|"production")에서 전부 채워야 정상 부팅되는 최소 완전 환경.

    모든 시크릿·어댑터 모드를 명시적으로 채운다 — 테스트가 실행되는 셸이 우연히
    가진 환경변수에 기대지 않기 위해서다(`_run_check`가 이 dict로 os.environ의
    같은 키를 전부 덮어쓴다).
    """

    return {
        "DJANGO_SECRET_KEY": secret_key,
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "api.laurio.example",
        "LAURIO_DEPLOYMENT_TARGET": target,
        "POSTGRES_DB": "laurio",
        "POSTGRES_USER": "laurio",
        "POSTGRES_PASSWORD": f"{target}-strong-password",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "55432",
        "INTERNAL_API_TOKEN": f"{target}-internal-token",
        # 운영자 앱 오리진(#43). 배포 환경에서 비면 부팅이 거부된다.
        "LAURIO_OPERATOR_ORIGIN": f"https://operator.{target}.laurio.example",
        "JWT_SIGNING_KEY": f"{target}-jwt-signing-key",
        "PAYMENT_WEBHOOK_SECRET": f"{target}-payment-webhook-secret",
        "PAYOUT_WEBHOOK_SECRET": f"{target}-payout-webhook-secret",
        "VERIFICATION_ENCRYPTION_KEY": _FERNET_KEY,
        "STORAGE_BACKEND": "s3",
        "STORAGE_BUCKET": f"laurio-{target}",
        "STORAGE_ENDPOINT_URL": "https://s3.amazonaws.com",
        "STORAGE_ACCESS_KEY": "dummy",
        "STORAGE_SECRET_KEY": "dummy",
        "STORAGE_REGION": "us-east-1",
        "SOCIAL_AUTH_MODE": "real",
        "VERIFICATION_ADAPTER_MODE": "real",
        "PAYMENT_ADAPTER_MODE": "real",
        "PAYOUT_ADAPTER_MODE": "real",
        "SELLER_ADAPTER_MODE": "real",
        "LLM_ADAPTER_MODE": "real",
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE": "real",
        "NOTIFICATION_ALIMTALK_ADAPTER": "notifications.adapters.RealAlimtalkAdapter",
        "NOTIFICATION_SMS_ADAPTER": "notifications.adapters.RealSmsAdapter",
        "NOTIFICATION_LMS_ADAPTER": "notifications.adapters.RealLmsAdapter",
    }


def _production_env(**overrides: str) -> dict[str, str]:
    env = _base_env(target="production", secret_key=_STRONG_SECRET_KEY)
    env.update(overrides)
    return env


def _staging_env(**overrides: str) -> dict[str, str]:
    # staging은 SECRET_KEY 강도 가드 대상이 아니다 — 짧은 값도 통과해야 한다는 것 자체가
    # 이 파일의 회귀 테스트 중 하나다.
    env = _base_env(target="staging", secret_key="staging-secret-key")
    env.update(overrides)
    return env


def _run_check(env: dict[str, str], *, deploy: bool = False) -> subprocess.CompletedProcess:
    import os

    full_env = {**os.environ, **env}
    args = [sys.executable, "manage.py", "check"]
    if deploy:
        args.append("--deploy")
    return subprocess.run(
        args,
        cwd=BACKEND_DIR,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


# --- production: 다섯 개의 check --deploy 경고가 실제로 해소됐는지 --------------------


def test_production_config_passes_check_deploy_with_zero_warnings():
    result = _run_check(_production_env(), deploy=True)

    assert result.returncode == 0, result.stderr
    assert "System check identified no issues" in result.stdout


@pytest.mark.parametrize("secret_key", ["short", "x" * 60, "django-insecure-" + "x" * 60])
def test_production_config_refuses_weak_secret_key(secret_key):
    result = _run_check(_production_env(DJANGO_SECRET_KEY=secret_key))

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr
    assert "ImproperlyConfigured" in result.stderr


def test_production_config_refuses_debug_true():
    result = _run_check(_production_env(DJANGO_DEBUG="true"))

    assert result.returncode != 0
    assert "DJANGO_DEBUG" in result.stderr
    assert "ImproperlyConfigured" in result.stderr


# --- staging: 강도 가드는 면제되지만 fake 어댑터 가드는 production과 동일 -------------


def test_staging_config_boots_fine_with_a_short_secret_key():
    result = _run_check(_staging_env())

    assert result.returncode == 0, result.stderr


_FAKE_ADAPTER_OVERRIDES = [
    ("STORAGE_BACKEND", "fake"),
    ("SOCIAL_AUTH_MODE", "fake"),
    ("VERIFICATION_ADAPTER_MODE", "fake"),
    ("PAYMENT_ADAPTER_MODE", "fake"),
    ("PAYOUT_ADAPTER_MODE", "fake"),
    ("SELLER_ADAPTER_MODE", "fake"),
    ("LLM_ADAPTER_MODE", "fake"),
    ("LLM_REQUIREMENT_CHAT_ADAPTER_MODE", "fake"),
    ("NOTIFICATION_ALIMTALK_ADAPTER", "notifications.adapters.FakeAlimtalkAdapter"),
    ("NOTIFICATION_SMS_ADAPTER", "notifications.adapters.FakeSmsAdapter"),
    ("NOTIFICATION_LMS_ADAPTER", "notifications.adapters.FakeLmsAdapter"),
]


@pytest.mark.parametrize("target", ["staging", "production"])
@pytest.mark.parametrize("field,fake_value", _FAKE_ADAPTER_OVERRIDES)
def test_deployed_environment_refuses_to_boot_with_a_fake_adapter(target, field, fake_value):
    env_builder = _production_env if target == "production" else _staging_env
    env = env_builder(**{field: fake_value})

    result = _run_check(env)

    assert result.returncode != 0, (
        f"{target} config with {field}={fake_value!r} booted successfully — "
        "이 값이 fake로 배포되면 요청은 200을 돌려주면서 실제로는 아무 일도 일어나지 "
        "않는다(스토리지는 파일이 사라지고, 결제/지급/채점/알림은 아무것도 하지 않는다)."
    )
    assert "ImproperlyConfigured" in result.stderr
    assert field in result.stderr


# --- development(미설정): 기존 CI 비-production 잡과 같은 동작이 안 깨졌는지 --------


def test_development_target_still_boots_with_every_adapter_fake():
    """LAURIO_DEPLOYMENT_TARGET 미설정(dev·CI)은 이 가드들의 대상이 아니어야 한다.

    이 티켓이 IS_PRODUCTION_DEPLOYMENT를 IS_DEPLOYED_ENVIRONMENT로 넓히면서 CI의
    기존 비-production 잡(DEBUG=false, 모든 어댑터 fake)까지 걸리게 되면, CI 자체가
    깨진다 — #10 리뷰가 이미 한 번 겪은 정확히 그 실패 모드다.
    """

    import os

    env = {
        **os.environ,
        "DJANGO_SECRET_KEY": "ci-only-insecure-key",
        "DJANGO_DEBUG": "false",
        "DJANGO_ALLOWED_HOSTS": "*",
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "55432",
        "INTERNAL_API_TOKEN": "ci-only-insecure-internal-token",
        "JWT_SIGNING_KEY": "ci-only-insecure-jwt-signing-key",
        "PAYMENT_WEBHOOK_SECRET": "ci-only-insecure-fake-pg-webhook-secret",
        "PAYOUT_WEBHOOK_SECRET": "ci-only-insecure-fake-toss-payout-webhook-secret",
        "VERIFICATION_ENCRYPTION_KEY": _FERNET_KEY,
        "STORAGE_BACKEND": "fake",
        "SOCIAL_AUTH_MODE": "fake",
        "VERIFICATION_ADAPTER_MODE": "fake",
        "PAYMENT_ADAPTER_MODE": "fake",
        "PAYOUT_ADAPTER_MODE": "fake",
        "LLM_ADAPTER_MODE": "fake",
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE": "fake",
    }
    env.pop("LAURIO_DEPLOYMENT_TARGET", None)

    result = subprocess.run(
        [sys.executable, "manage.py", "check", "--fail-level", "WARNING"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


# --- LAURIO_DEPLOYMENT_TARGET 자체의 유효성 (코디네이터 리뷰 지적) ------------------


@pytest.mark.parametrize(
    "bad_target", ["prod", "Production", "PRODUCTION", "stagng", "prod ", " production"]
)
def test_unknown_deployment_target_refuses_to_boot(bad_target):
    """오타·대소문자 실수 하나가 조용히 "development"로 흘러 이 티켓의 모든 가드
    (fake 어댑터 거부·SECRET_KEY 강도·DEBUG 거부·TLS 하드닝)를 무력화하면 안 된다 —
    허용된 세 값이 아니면 그 자리에서 바로 죽어야 한다."""

    env = _production_env(LAURIO_DEPLOYMENT_TARGET=bad_target)

    result = _run_check(env)

    assert result.returncode != 0, (
        f"LAURIO_DEPLOYMENT_TARGET={bad_target!r} 가 조용히 통과했다 — 이 값이 "
        "'production'/'staging'과 매치하지 않으면 모든 배포 가드가 꺼진 채로 부팅된다."
    )
    assert "ImproperlyConfigured" in result.stderr
    assert "LAURIO_DEPLOYMENT_TARGET" in result.stderr


# --- "fake"라는 별칭 문자열만 피해 가는 dotted path 우회 (코디네이터 리뷰 지적) -----

_FAKE_DOTTED_PATH_BYPASSES = [
    ("STORAGE_BACKEND", "storage.adapters.fake.FakeStorageAdapter"),
    ("LLM_ADAPTER_MODE", "scoring.adapters.FakeLLMScoringAdapter"),
    (
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE",
        "contests.requirement_chat.FakeRequirementChatAdapter",
    ),
]


@pytest.mark.parametrize("target", ["staging", "production"])
@pytest.mark.parametrize("field,fake_dotted_path", _FAKE_DOTTED_PATH_BYPASSES)
def test_deployed_environment_refuses_a_fake_adapter_named_by_dotted_path(
    target, field, fake_dotted_path
):
    """STORAGE_BACKEND는 "fake"가 별칭 dict를 거쳐 실제 dotted path로 풀리고,
    LLM_ADAPTER_MODE/LLM_REQUIREMENT_CHAT_ADAPTER_MODE는 "fake"가 아니면 뭐든
    dotted path로 그대로 import한다(core.adapters.resolve_adapter) — 즉 문자 그대로
    "fake"만 피하면 실제로는 여전히 Fake 어댑터가 조용히 바인딩된다. 이전 가드는
    `value == "fake"`만 봐서 이 경로를 놓쳤다."""

    env_builder = _production_env if target == "production" else _staging_env
    env = env_builder(**{field: fake_dotted_path})

    result = _run_check(env)

    assert result.returncode != 0, (
        f"{target} config with {field}={fake_dotted_path!r} booted successfully — "
        "'fake' 별칭 문자열만 피했을 뿐 실제로는 여전히 Fake 어댑터가 바인딩된다."
    )
    assert "ImproperlyConfigured" in result.stderr
    assert field in result.stderr


# --- Celery beat가 부르는 내부 엔드포인트는 SSL 리다이렉트에서 빠져야 한다 ----------
# (코디네이터 리뷰 지적: production의 SECURE_SSL_REDIRECT=True가 컨테이너 내부
# 네트워크에서 평문 HTTP로 오는 Celery의 틱 호출까지 301로 되돌려 보내면, 평문
# gunicorn은애초에 TLS 핸드셰이크를 할 수 없어 매 틱이 SSLError로 죽는다. 이건
# subprocess 없이도 같은 프로세스에서 override_settings로 재현 가능하다 —
# SECURE_SSL_REDIRECT/SECURE_REDIRECT_EXEMPT는 매 요청마다 SecurityMiddleware가
# django.conf.settings에서 다시 읽는 일반 설정이지, LAURIO_DEPLOYMENT_TARGET처럼
# import 시점에 한 번만 평가되는 값이 아니기 때문이다.


@pytest.mark.django_db
def test_internal_endpoints_are_exempt_from_ssl_redirect_but_other_paths_are_not(client):
    with override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^api/internal/"]):
        internal_response = client.post("/api/internal/tick", HTTP_X_INTERNAL_TOKEN="wrong-token")
        other_response = client.get("/api/health")

    assert internal_response.status_code not in (301, 302), (
        "내부 엔드포인트가 SSL 리다이렉트 대상이면 Celery beat의 평문 내부 호출이 "
        "301을 받고, 평문 gunicorn은 TLS 핸드셰이크를 못 하므로 매 틱이 죽는다."
    )
    assert other_response.status_code in (301, 302), (
        "내부 엔드포인트만 예외여야 한다 — 예외 패턴이 너무 넓으면 공개 API까지 "
        "SSL 리다이렉트가 조용히 꺼진다."
    )


# --- 운영자 오리진: 비어 있으면 배포 환경에서 부팅을 거부한다 (#43 후속) ------------


@pytest.mark.parametrize("target", ["staging", "production"])
def test_deployed_environment_refuses_to_boot_without_an_operator_origin(target):
    """비면 Host 헤더 유도로 떨어지는데, `SECURE_PROXY_SSL_HEADER` 는 production 에만
    걸린다 — TLS 종단 뒤의 staging 에서는 scheme 이 http 로 잡혀 브라우저가 보낸
    https 오리진과 어긋나고, **로그인을 포함한 모든 변경 요청이 403** 이 된다.
    fail-closed 라 보안 구멍은 아니지만 운영이 통째로 죽는다.

    프론트엔드가 LAURIO_WEB_ORIGIN 에 대해 이미 같은 실패를 겪고 같은 방식으로
    막았다(frontend/instrumentation.ts).
    """

    env = (_production_env if target == "production" else _staging_env)()
    env["LAURIO_OPERATOR_ORIGIN"] = ""

    result = _run_check(env)

    assert result.returncode != 0
    assert "LAURIO_OPERATOR_ORIGIN" in result.stderr


def test_development_target_boots_without_an_operator_origin():
    """dev·CI 는 요청이 실제로 도착한 주소로 조립한다 — 강제하지 않는다."""

    env = _base_env(target="development", secret_key=_STRONG_SECRET_KEY)
    env["LAURIO_DEPLOYMENT_TARGET"] = "development"
    env["LAURIO_OPERATOR_ORIGIN"] = ""

    result = _run_check(env)

    assert result.returncode == 0, result.stderr
