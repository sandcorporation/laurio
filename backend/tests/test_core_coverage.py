"""`core.coverage.assert_covers` 단위 테스트 (#176).

이 파일만 예외적으로 HTTP를 거치지 않는다 — 어느 API에도 매여 있지 않은 순수
원시 도구다(`test_core_adapters.py`와 같은 카테고리). `payouts.progress`의
`HoldKind` 번역표·`payouts.adapters_toss`의 벤더 상태 분류표·`payouts.schemas`의
`OperatorPayoutCountsOut`이 실제 사용처이고, 그 세 모듈은 이미 로드에 성공했으니
그 자체로는 "값이 하나 빠지면 정말 터지는가"를 증명하지 않는다 — 이 파일이
함수 자체로 증명한다.
"""

from __future__ import annotations

from enum import Enum

import pytest

from core.coverage import assert_covers


def test_assert_covers_raises_on_gap():
    with pytest.raises(RuntimeError, match=r"덮지 않는다.*'B'"):
        assert_covers({"A"}, {"A", "B"}, name="_어떤_표")


def test_assert_covers_passes_when_covered():
    assert_covers({"A", "B"}, {"A", "B"}, name="_어떤_표")


def test_assert_covers_passes_with_extra_when_not_bidirectional():
    """기본(단방향)은 `covered`에 `expected`보다 많은 값이 남아 있어도 통과한다
    — 벤더가 문서에 없는 값을 새로 보내는 것 자체는 사고가 아니다."""

    assert_covers({"A", "B", "C"}, {"A", "B"}, name="_어떤_표")


def test_assert_covers_names_the_enum_class_in_the_message():
    """`expected`가 enum 클래스 그 자체면 실패 메시지가 그 이름을 싣는다 —
    부팅 실패 로그만 보고도 "무엇을 기준으로 빠졌는가"를 알 수 있어야 한다."""

    class _Kind(str, Enum):
        A = "a"
        B = "b"

    with pytest.raises(RuntimeError, match=r"_Kind.*'b'"):
        assert_covers({_Kind.A}, _Kind, name="_어떤_표")


def test_assert_covers_bidirectional_raises_on_extra():
    """`bidirectional=True`면 `covered`에 `expected`에 없는 값이 남아도 던진다
    — 필드 이름이 정확히 일치해야 하는 표(`OperatorPayoutCountsOut`)를 위한
    엄격한 판정이다."""

    with pytest.raises(RuntimeError, match=r"남는 것.*'C'"):
        assert_covers({"A", "B", "C"}, {"A", "B"}, name="_어떤_표", bidirectional=True)


def test_assert_covers_bidirectional_passes_on_exact_match():
    assert_covers({"A", "B"}, {"A", "B"}, name="_어떤_표", bidirectional=True)
