"""배포 환경 부팅 가드 (#23, #83, ADR-0007).

이 프로젝트의 유일한 테스트 시임은 HTTP지만, 이 파일이 검증하는 대상은 요청을
받기도 전에 끝나는 부팅 시점의 실패다 — HTTP로는 원천적으로 도달할 수 없다.
가드는 두 갈래다: `config/settings.py`의 대부분은 모듈 임포트 시점에
`ImproperlyConfigured`를 던지고, 어댑터 모드 가드(#83,
`core.adapters.check_adapter_mode`)는 `django.core.checks`로 등록되어
`django.setup()` 이후에만 평가된다(모델을 참조하는 실물 어댑터를 settings.py
임포트 도중 불러오면 `AppRegistryNotReady`가 나기 때문이다 — 그건
`except ImportError`로 잡히지 않는다). 두 갈래 다 같은 프로세스 안에서
`override_settings`로는 재현할 수 없다(이미 임포트가 끝난 뒤라
`LAURIO_DEPLOYMENT_TARGET` 분기를 다시 태울 방법이 없고, 체크 레지스트리도
매 프로세스에서 한 번만 구성된다). 그래서 `storage/checks.py`가 `manage.py
check`(부팅 파이프라인 그 자체)로 검증되는 것과 같은 원칙을, 서브프로세스로
`manage.py check`를 직접 실행해 종료 코드와 에러 메시지를 확인하는 방식으로
두 갈래 모두에 적용한다.
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


# --- VERIFICATION/PAYMENT/PAYOUT/SELLER/LLM*_ADAPTER_MODE 용 stub (#83) ---------
#
# 실물 어댑터(#85 PortOne, #87 Toss, #57 Seller 등록, #88 OpenAI)는 아직 없다.
# 이 파일이 검증하는 것은 "완전한 production/staging 환경이 부팅되는가"이지
# "실물 벤더가 실제로 연결되는가"가 아니므로, `tests/adapter_stubs.py`가 이름이
# Fake로 시작하지 않고 각 Protocol을 구조적으로 만족하는 최소 stub 클래스를
# dotted path로 제공한다(그 모듈 자체에 상세 설명이 있다) — 부팅 가드(#83,
# `core.adapters.check_adapter_mode`)가 "fake도 아니고 import·인스턴스화·
# 계약 충족도 안 되는 값"만 거부한다는 것을, 이 stub들은 통과한다는 것과 대비해
# 함께 증명한다. 이 stub들을 이 테스트 모듈 안에 직접 두지 않는 이유는 그
# 모듈의 독스트링이 설명한다 — settings.py가 아니라 이제 checks 프레임워크가
# 이 dotted path를 임포트하므로 시점 문제는 사라졌지만, 계속 가볍게 둔다.


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
        "VERIFICATION_ADAPTER_MODE": "tests.adapter_stubs.StubVerificationAdapter",
        "PAYMENT_ADAPTER_MODE": "tests.adapter_stubs.StubPGAdapter",
        "PAYOUT_ADAPTER_MODE": "tests.adapter_stubs.StubPayoutAdapter",
        "SELLER_ADAPTER_MODE": "tests.adapter_stubs.StubSellerAdapter",
        "LLM_ADAPTER_MODE": "tests.adapter_stubs.StubLLMScoringAdapter",
        "LLM_REQUIREMENT_CHAT_ADAPTER_MODE": "tests.adapter_stubs.StubRequirementChatAdapter",
        # #89: notifications.adapters.RealAlimtalkAdapter/RealSmsAdapter/RealLmsAdapter는
        # 저장소에 없는 클래스였다(그것이 이 티켓이 고치는 버그) — 실물 벤더
        # 어댑터(#51)가 나오기 전까지는 나머지 어댑터들과 같은 원칙으로 stub을
        # 가리킨다. 세 설정마다 channel이 다른 Stub을 쓴다(#51 코드리뷰 지적 8) —
        # notifications.checks가 이제 channel 일치도 검증하므로 하나를
        # 공유하면 그 자체가 걸린다.
        "NOTIFICATION_ALIMTALK_ADAPTER": "tests.adapter_stubs.StubAlimtalkChannelAdapter",
        "NOTIFICATION_SMS_ADAPTER": "tests.adapter_stubs.StubSmsChannelAdapter",
        "NOTIFICATION_LMS_ADAPTER": "tests.adapter_stubs.StubLmsChannelAdapter",
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
    # #83: verification/payment/payout도 이제 resolve_adapter로 dotted path를 그대로
    # import한다 — 전에는 "fake" 리터럴 외의 값이 전부 NotImplementedError였으므로 이
    # 우회 자체가 불가능했다. 세 어댑터를 옮기면서 새로 생긴 회귀 위험이다.
    ("VERIFICATION_ADAPTER_MODE", "verification.adapters.FakeVerificationAdapter"),
    ("PAYMENT_ADAPTER_MODE", "payments.adapters.FakePGAdapter"),
    ("PAYOUT_ADAPTER_MODE", "payouts.adapters.FakePayoutAdapter"),
    ("SELLER_ADAPTER_MODE", "payouts.adapters.FakeSellerAdapter"),
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


# --- 풀 수 없는(non-fake, non-importable) 어댑터 값은 부팅 자체를 거부한다 (#83) -----
#
# compose.staging.yaml이 실제로 겪었던 버그를 그대로 재현한다: PAYMENT_ADAPTER_MODE
# 같은 값에 "real"처럼 dotted path가 아닌(그리고 "fake"도 아닌) 문자열을 넣으면,
# 이전에는 부팅이 통과하고 첫 결제·본인확인 요청에서야 NotImplementedError로 죽었다.


_UNRESOLVABLE_ADAPTER_MODE_FIELDS = [
    "VERIFICATION_ADAPTER_MODE",
    "PAYMENT_ADAPTER_MODE",
    "PAYOUT_ADAPTER_MODE",
    "SELLER_ADAPTER_MODE",
    "LLM_ADAPTER_MODE",
    "LLM_REQUIREMENT_CHAT_ADAPTER_MODE",
    # #89: 알림 채널 셋도 이제 같은 가드(core.adapters.check_adapter_mode)를 받는다 —
    # 이전에는 존재하지 않는 클래스를 가리켜도 부팅이 통과했다(정확히 이 티켓이
    # 고치는 버그).
    "NOTIFICATION_ALIMTALK_ADAPTER",
    "NOTIFICATION_SMS_ADAPTER",
    "NOTIFICATION_LMS_ADAPTER",
]


@pytest.mark.parametrize("target", ["staging", "production"])
@pytest.mark.parametrize("field", _UNRESOLVABLE_ADAPTER_MODE_FIELDS)
def test_deployed_environment_refuses_to_boot_with_an_unresolvable_adapter_value(target, field):
    """`"real"`은 dotted path가 아니다 — `import_string`이 시도조차 되지 않고 바로
    `ImportError`가 난다. 이 값으로 배포되면 컨테이너는 뜨지만 실제 요청에서만
    죽는다는 것이 이 티켓(#83)이 고치는 버그다.

    이 가드는 `core.adapters.check_adapter_mode`로 `django.core.checks`에 등록되어
    있다(#83 코드리뷰 지적 — settings.py 모듈 실행 도중에 평가하면 모델을 참조하는
    실물 어댑터에서 `AppRegistryNotReady`가 난다) — 그래서 실패 신호가
    `ImproperlyConfigured`가 아니라 `SystemCheckError`/`core.E001`이다."""

    env_builder = _production_env if target == "production" else _staging_env
    env = env_builder(**{field: "real"})

    result = _run_check(env)

    assert result.returncode != 0, (
        f"{target} config with {field}='real' 이 부팅에 성공했다 — 'real'은 아무 클래스도 "
        "가리키지 않는 문자열이므로, 이 값 그대로 배포되면 요청이 들어올 때까지 아무도 "
        "이 실수를 모른다."
    )
    assert "core.E001" in result.stderr
    assert field in result.stderr


def test_development_target_boots_with_an_unresolvable_adapter_value():
    """dev·CI는 이 새 가드의 대상이 아니다 — 오타를 부팅 실패로 바꿀 만큼 배포와
    같은 무게가 아니다(#83). 값을 실제로 쓰려는 요청이 오기 전까지는 조용히 통과한다
    (resolve_adapter가 그 시점에 NotImplementedError를 던진다 — 기존 동작 그대로)."""

    env = _base_env(target="development", secret_key=_STRONG_SECRET_KEY)
    env["LAURIO_DEPLOYMENT_TARGET"] = "development"
    for field in _UNRESOLVABLE_ADAPTER_MODE_FIELDS:
        env[field] = "real"

    result = _run_check(env)

    assert result.returncode == 0, result.stderr


# --- 존재하지만 계약을 만족하지 않는 dotted path (#83 코드리뷰 지적) ---------------
#
# 가드가 "import만 되면 통과"였다면, payments.adapters.PGError처럼 실제로 존재하는
# (그러나 PGAdapter 계약과는 전혀 무관한) 클래스를 가리키는 오타가 부팅을 통과하고
# 첫 결제에서야 AttributeError라는 알아보기 어려운 모양으로 죽는다 — 가드가 막으려던
# 바로 그 실패 모드다. `core.adapters.check_adapter_mode`는 실제로 인스턴스화하고
# 계약을 만족하는지도 확인하므로 이 경로를 부팅 시점에 잡는다.


def test_deployed_environment_refuses_a_dotted_path_that_exists_but_does_not_satisfy_the_contract():
    env = _production_env(PAYMENT_ADAPTER_MODE="payments.adapters.PGError")

    result = _run_check(env)

    assert result.returncode != 0, (
        "payments.adapters.PGError는 존재하지만 PGAdapter 계약과 무관한 클래스다 — "
        "이 값으로 배포되면 부팅은 통과하고 첫 결제에서야 AttributeError로 죽는다."
    )
    assert "core.E003" in result.stderr
    assert "PAYMENT_ADAPTER_MODE" in result.stderr


def test_deployed_environment_refuses_a_notification_adapter_that_exists_but_does_not_satisfy_the_contract():
    """#89: 알림 채널도 같은 계약 검증을 받는다.

    `payments.adapters.PGError`는 존재하지만 `NotificationChannelAdapter`
    계약(channel 속성 + send 메서드)과 전혀 무관하다 — 이 값으로 배포되면
    부팅은 통과하고 첫 알림 시도에서야 AttributeError로 죽는다.
    """

    env = _production_env(NOTIFICATION_SMS_ADAPTER="payments.adapters.PGError")

    result = _run_check(env)

    assert result.returncode != 0, (
        "payments.adapters.PGError는 존재하지만 NotificationChannelAdapter 계약과 "
        "무관한 클래스다 — 이 값으로 배포되면 부팅은 통과하고 첫 알림에서야 "
        "AttributeError로 죽는다."
    )
    assert "core.E003" in result.stderr
    assert "NOTIFICATION_SMS_ADAPTER" in result.stderr


# --- 알리고(Aligo) SMS/LMS 실물 어댑터의 자격증명 (#51) -----------------------------
#
# AC: "NOTIFICATION_*_ADAPTER dotted path 셋이 채워져 배포 환경이 부팅한다" —
# TossPGAdapter(#87)와 같은 원칙으로, 인자 없이 생성되지만 자격증명이 비어
# 있으면 생성 자체가 실패해 core.adapters.check_adapter_mode가 core.E002로
# 부팅을 거부한다.


def test_staging_boots_with_aligo_sms_lms_adapters_and_credentials():
    env = _staging_env(
        NOTIFICATION_SMS_ADAPTER="notifications.adapters_aligo.AligoSmsAdapter",
        NOTIFICATION_LMS_ADAPTER="notifications.adapters_aligo.AligoLmsAdapter",
        ALIGO_API_KEY="dummy-key",
        ALIGO_USER_ID="dummy-user",
        ALIGO_SENDER_PHONE_NUMBER="01000000000",
    )

    result = _run_check(env)

    assert result.returncode == 0, result.stderr


def test_staging_alimtalk_adapter_boots_with_aligo_credentials():
    """알림톡 어댑터(#51)는 아직 벤더를 호출하지 않지만, 승인 이후 그대로 실물
    호출로 바꿀 수 있도록 자격증명은 미리 검증한다 — 그래서 이 값도 같은
    자격증명을 요구한다."""

    env = _staging_env(
        NOTIFICATION_ALIMTALK_ADAPTER="notifications.adapters_aligo.AligoAlimtalkAdapter",
        ALIGO_API_KEY="dummy-key",
        ALIGO_USER_ID="dummy-user",
        ALIGO_SENDER_PHONE_NUMBER="01000000000",
    )

    result = _run_check(env)

    assert result.returncode == 0, result.stderr


# --- 세 설정이 서로의 채널을 가리키면(#51 코드리뷰 지적 8) 부팅을 거부한다 -----------
#
# core.adapters.check_adapter_mode는 Protocol 구조(channel 속성 + send 메서드
# 존재)만 보므로, NOTIFICATION_SMS_ADAPTER가 실수로 channel="lms"인
# AligoLmsAdapter를 가리켜도 그 자체로는 깨끗이 통과한다 — 리뷰가 직접
# 실행해 확인한 사고: SMS 요금으로 전부 LMS를 보내면서 발송 이력에는
# channel="sms"로 남는다. notifications.checks의 추가 검증(notifications.E002)
# 이 이 어긋남을 부팅 시점에 잡아야 한다.


@pytest.mark.parametrize(
    "field,wrong_class_name",
    [
        ("NOTIFICATION_ALIMTALK_ADAPTER", "AligoSmsAdapter"),
        ("NOTIFICATION_SMS_ADAPTER", "AligoLmsAdapter"),
        ("NOTIFICATION_LMS_ADAPTER", "AligoAlimtalkAdapter"),
    ],
)
def test_staging_refuses_boot_when_a_notification_setting_points_at_the_wrong_channel(
    field, wrong_class_name
):
    env = _staging_env(
        **{field: f"notifications.adapters_aligo.{wrong_class_name}"},
        ALIGO_API_KEY="dummy-key",
        ALIGO_USER_ID="dummy-user",
        ALIGO_SENDER_PHONE_NUMBER="01000000000",
    )

    result = _run_check(env)

    assert result.returncode != 0, (
        f"{field}가 다른 채널의 어댑터({wrong_class_name})를 가리켜도 부팅에 "
        "성공했다 — Protocol 구조만 같으면 통과하는 core.adapters.check_adapter_mode "
        "의 빈틈이다(#51 코드리뷰 지적 8)."
    )
    assert "notifications.E002" in result.stderr
    assert field in result.stderr


@pytest.mark.parametrize(
    "field",
    [
        "NOTIFICATION_ALIMTALK_ADAPTER",
        "NOTIFICATION_SMS_ADAPTER",
        "NOTIFICATION_LMS_ADAPTER",
    ],
)
@pytest.mark.parametrize(
    "class_name",
    [
        "AligoAlimtalkAdapter",
        "AligoSmsAdapter",
        "AligoLmsAdapter",
    ],
)
def test_staging_refuses_boot_without_any_aligo_credential_env_var(field, class_name):
    env = _staging_env(**{field: f"notifications.adapters_aligo.{class_name}"})

    result = _run_check(env)

    assert result.returncode != 0, (
        "ALIGO_API_KEY/ALIGO_USER_ID/ALIGO_SENDER_PHONE_NUMBER 없이도 부팅에 "
        "성공했다 — AligoCredentialsError(ImproperlyConfigured)가 어댑터 생성을 "
        "막아야 core.E002로 부팅이 거부된다."
    )
    assert "core.E002" in result.stderr
    assert field in result.stderr


# --- 토스 결제 어댑터의 자격증명 환경변수 이름(#87 코드리뷰 지적 6) -----------------------
#
# TossPGAdapter는 settings.TOSS_API_SECRET_KEY를 읽는데, staging/prod
# compose는 그 이름이 아니라 TOSS_SANDBOX_SECRET_KEY/TOSS_LIVE_SECRET_KEY를
# 주입한다(docker/compose.staging.yaml, docker/compose.prod.yaml — 새드박스
# 키와 실물 키를 다른 이름으로 두어 운영자가 실수로 실물 키를 staging에
# 붙여넣어도 그 변수가 애초에 읽히지 않는다). settings.py가 이 셋 중 먼저
# 채워진 값을 쓰도록 폴백하지 않으면, 문서대로 TOSS_SANDBOX_SECRET_KEY/
# TOSS_LIVE_SECRET_KEY를 채워도 core.E002로 부팅이 거부된다.


def test_staging_toss_adapter_boots_with_sandbox_secret_key_env_var():
    env = _staging_env(
        PAYMENT_ADAPTER_MODE="payments.adapters_toss.TossPGAdapter",
        TOSS_SANDBOX_SECRET_KEY="test_sk_dummy_sandbox",
    )

    result = _run_check(env)

    assert result.returncode == 0, result.stderr


def test_production_toss_adapter_boots_with_live_secret_key_env_var():
    env = _production_env(
        PAYMENT_ADAPTER_MODE="payments.adapters_toss.TossPGAdapter",
        TOSS_LIVE_SECRET_KEY="live_sk_dummy",
    )

    result = _run_check(env)

    assert result.returncode == 0, result.stderr


def test_staging_toss_adapter_refuses_boot_without_any_toss_secret_key_env_var():
    env = _staging_env(PAYMENT_ADAPTER_MODE="payments.adapters_toss.TossPGAdapter")

    result = _run_check(env)

    assert result.returncode != 0, (
        "TOSS_API_SECRET_KEY도 TOSS_SANDBOX_SECRET_KEY도 없으면 "
        "TossPGAdapter의 생성자(ImproperlyConfigured)가 실패해 "
        "core.E002로 부팅이 거부되어야 한다."
    )
    assert "core.E002" in result.stderr
    assert "PAYMENT_ADAPTER_MODE" in result.stderr


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
