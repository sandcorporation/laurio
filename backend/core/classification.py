"""status enum 이 자기 분류를 소유한다 (#141, #121).

「어떤 status 가 X 에 해당하는가」를 열세 module 이 각자 값 집합 리터럴로 답하던 동안 같은 사고가
세 번 났다 — 새 상태(JUDGING_ENDED, CONFIRMED_SELLER_PENDING)가 생겼는데 어느 호출부의 집합에는
빠져, 환불이 Escrow 에 갇히고 채점이 영원히 빠지고 배치 슬롯이 낭비됐다. 값 집합에는 「빠짐없음」을
강제하는 것이 없었다.

`Classification` 은 질문 하나에 대한 **enum 전체 사상**이다 — 모든 값에 명시적으로 답을 적는다.
`tests/test_status_classification.py` 가 모든 질문의 키 집합 == enum 전체 값을 단언하므로, 값을 더하는
사람은 질문마다 결정을 지나칠 수 없다. 사상에 없는 값(마이그레이션 사고로 DB 에 남은 enum 밖 문자열)은
KeyError 로 큰 소리를 낸다 — 조용히 False 가 되는 것보다 낫다.

    Contest.Status.SCOREABLE(contest.status)            # 질문 — bool
    status__in=Contest.Status.SCOREABLE.statuses         # 같은 질문의 집합 표현(필터)
    Contest.Status.HOME_AXIS(contest.status)             # 값이 bool 이 아닌 축도 같은 모양
    Contest.Status.HOME_AXIS.where(HomeStatusAxis.OPEN)  # 그 축에서 특정 답을 갖는 값들

전이(from→to)는 질문이 아니다 — 그대로 enum 값을 쓴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

V = TypeVar("V")


class Classification(Generic[V]):
    """질문 하나 = enum 의 모든 값 → 답. 불변이고, 조회는 사상 조회 한 번이다."""

    def __init__(self, mapping: Mapping[Any, V], *, question: str = ""):
        self._mapping = dict(mapping)
        self.question = question

    def __call__(self, status) -> V:
        return self._mapping[status]

    @property
    def mapping(self) -> Mapping[Any, V]:
        return dict(self._mapping)

    @property
    def keys(self) -> frozenset:
        return frozenset(self._mapping)

    def where(self, answer: V) -> frozenset:
        """이 질문에 `answer` 로 답하는 값들 — `status__in=` 에 그대로 쓴다."""

        return frozenset(status for status, value in self._mapping.items() if value == answer)

    @property
    def statuses(self) -> frozenset:
        """bool 질문의 「그렇다」 집합."""

        return self.where(True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Classification({self.question or '?'}: {sorted(self.where(True))})"


def classifications_of(enum_cls) -> dict[str, Classification]:
    """enum 클래스에 붙은 모든 질문 — 키 집합 테스트가 이것을 돈다."""

    return {name: value for name, value in vars(enum_cls).items() if isinstance(value, Classification)}
