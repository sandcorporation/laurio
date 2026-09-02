"""`core.adapters` — `resolve_adapter`·`check_adapter_mode` 단위 테스트 (#83).

이 파일만 예외적으로 HTTP를 거치지 않는다 — 둘 다 어느 API에도 매여 있지 않은
순수 인프라 헬퍼다(payments/verification/payouts/scoring/contests의
`get_adapter()`들이 공유해 쓴다). `tests/test_deployment_config.py`가
subprocess로 "부팅이 실제로 거부되는가"를 통합 검증하는 것과는 다른 층위의
질문 — "이 함수 자체가 여러 실패 모드를 올바르게 구분하는가" — 을 묻는다.

`check_adapter_mode`는 `django.conf.settings`를 호출 시점에 읽으므로(#83
코드리뷰 지적로 settings.py 모듈 실행 시점 평가에서 `django.core.checks`
등록으로 옮긴 결과) `override_settings`로 안전하게 재현할 수 있다 —
`test_deployment_config.py`의 나머지 가드들과 달리 서브프로세스가 필요 없다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pytest
from django.test import override_settings

from core.adapters import check_adapter_mode, resolve_adapter

# --- resolve_adapter -----------------------------------------------------------


class _FakeThing:
    pass


def test_resolve_adapter_returns_fake_factory_result_for_fake_mode():
    sentinel = object()
    result = resolve_adapter(mode="fake", fake_factory=lambda: sentinel, not_implemented_hint="x")
    assert result is sentinel


def test_resolve_adapter_raises_not_implemented_when_module_does_not_exist():
    """모듈 자체가 없다 — 정직하게 "아직 구현되지 않았다"로 안내한다."""

    with pytest.raises(NotImplementedError):
        resolve_adapter(
            mode="tests.this_module_does_not_exist_at_all.SomeAdapter",
            fake_factory=_FakeThing,
            not_implemented_hint="아직 구현되지 않았다",
        )


def test_resolve_adapter_raises_not_implemented_when_class_missing_from_existing_module():
    """모듈은 있는데 그 클래스가 없다 — 이것도 "아직 구현되지 않았다"다."""

    with pytest.raises(NotImplementedError):
        resolve_adapter(
            mode="tests.adapter_stubs.ThisClassDoesNotExist",
            fake_factory=_FakeThing,
            not_implemented_hint="아직 구현되지 않았다",
        )


def test_resolve_adapter_propagates_the_real_error_when_the_module_itself_is_broken():
    """모듈은 있는데 그 모듈이 내부에서 부르는 다른 모듈이 없어 깨지면, "아직
    구현되지 않았다"로 덮지 않고 원래 예외를 그대로 올려보낸다(#83 코드리뷰
    지적) — 없는 모듈과 깨진 모듈은 다른 사실이고, 후자를 전자의 메시지로
    덮으면 실제 버그를 찾는 사람이 엉뚱한 곳을 보게 된다."""

    with pytest.raises(ModuleNotFoundError) as exc_info:
        resolve_adapter(
            mode="tests.broken_adapter_fixture.BrokenAdapter",
            fake_factory=_FakeThing,
            not_implemented_hint="아직 구현되지 않았다",
        )
    # tests.broken_adapter_fixture 자신이 아니라, 그 안에서 부르는 다른(없는)
    # 모듈 이름이 예외에 남아 있어야 한다 — "이 모듈이 없다"가 아니라 "이
    # 모듈이 부르는 게 없다"는 사실이 구분된다는 증거다.
    assert exc_info.value.name != "tests.broken_adapter_fixture"
    assert "_this_dependency_does_not_exist_anywhere" in (exc_info.value.name or "")


# --- check_adapter_mode ----------------------------------------------------------


@runtime_checkable
class _Greetable(Protocol):
    def greet(self) -> str: ...


class _Greeter:
    def greet(self) -> str:
        return "hi"


class _WrongShape:
    """`_Greetable`이 요구하는 `greet`가 없다 — 존재는 하지만 계약을 만족 못한다."""


class _RequiresArgument:
    """생성자가 필수 인자를 요구한다 — `resolve_adapter`는 인자 없이 생성한다."""

    def __init__(self, must_have_this):
        self.must_have_this = must_have_this

    def greet(self) -> str:
        return "hi"


def test_check_adapter_mode_skips_when_not_deployed():
    with override_settings(IS_DEPLOYED_ENVIRONMENT=False, _CHECK_ADAPTER_TEST_MODE="anything"):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert errors == []


def test_check_adapter_mode_skips_when_fake():
    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, _CHECK_ADAPTER_TEST_MODE="fake"):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert errors == []


def test_check_adapter_mode_reports_import_failure():
    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True, _CHECK_ADAPTER_TEST_MODE="tests.does_not_exist.Nope"
    ):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert [e.id for e in errors] == ["core.E001"]


def test_check_adapter_mode_reports_instantiation_failure():
    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        _CHECK_ADAPTER_TEST_MODE="tests.test_core_adapters._RequiresArgument",
    ):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert [e.id for e in errors] == ["core.E002"]


def test_check_adapter_mode_reports_protocol_mismatch():
    """존재는 하지만 엉뚱한 클래스를 가리키는 오타가, "import는 됐으니 통과"가
    아니라 계약 불충족으로 걸린다(#83 코드리뷰 지적 — `payments.adapters.PGError`
    같은 값이 부팅 가드를 통과하고 첫 결제에서야 죽는 것을 막는다)."""

    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        _CHECK_ADAPTER_TEST_MODE="tests.test_core_adapters._WrongShape",
    ):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert [e.id for e in errors] == ["core.E003"]


def test_check_adapter_mode_passes_for_a_conforming_class():
    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        _CHECK_ADAPTER_TEST_MODE="tests.test_core_adapters._Greeter",
    ):
        errors = check_adapter_mode(setting_name="_CHECK_ADAPTER_TEST_MODE", protocol=_Greetable)
    assert errors == []
