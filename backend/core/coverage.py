"""값 집합이 전체를 빠짐없이 덮는지 모듈 로드 시점에 증명하는 원시 도구 (#176).

같은 판정("이 표가 저 값 전체를 빠짐없이 아는가")이 세 곳에서 각자 손으로
`set` 뺄셈을 하고 있었다 — `payouts.progress`의 `HoldKind` 번역표(enum ↔ dict),
`payouts.adapters_toss`의 벤더 상태 분류표(#174, set ↔ set), `payouts.schemas`의
`OperatorPayoutCountsOut`(#149, 양방향 — 빠짐과 남음을 둘 다 본다). 모양이 갈려
있어 서로 재사용하지 못했고, #174가 두 번째 사본을 새로 만들면서 그 사실이
드러났다 — 이 모듈이 세 곳 모두가 지나는 하나의 원시 도구다.

**의도적으로 Django를 포함해 아무것도 import하지 않는다.** 어댑터 계층
(`payouts.adapters_toss`)이 이 도구를 쓰려면, 이 도구 자체가 Django 모델을
끌고 오면 안 된다 — ADR-0007이 정한 "어댑터는 DB를 읽지도 쓰지도 않는다"를
어댑터가 import하는 모듈까지 조용히 어기지 않게 한다(#176 코드리뷰 지적:
예전에는 `payouts.progress`에서 이 도구를 빌려 왔는데, 그 모듈이 `.models`를
import하므로 벤더 HTTP만 알아야 할 어댑터 파일이 Django 모델을 끌고 왔다).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def assert_covers(
    covered: Iterable[Any],
    expected: Iterable[Any],
    *,
    name: str,
    bidirectional: bool = False,
) -> None:
    """`covered`(번역표라면 dict의 키, 아니면 set)가 `expected`(enum 전체이거나
    임의의 값 집합)를 빠짐없이 덮는지 — 아니면 던진다. 모듈 로드 시 호출해 값이
    하나 늘거나 오타로 하나 빠지면 import 시점에 바로 터지게 한다.

    `expected`가 `HoldKind` 같은 enum 클래스 그 자체면 실패 메시지에 그 이름을
    싣는다 — `set(HoldKind)`처럼 이미 풀어헤친 집합을 넘기면 그 이름이 사라져
    "무엇을 기준으로 빠졌는가"를 코드를 열어야 알 수 있다(#176 코드리뷰 지적).

    `bidirectional=True`면 `covered`에 `expected`에 없는 값이 남아도(초과) 던진다
    — 필드 이름이 정확히 일치해야 하는 표(`OperatorPayoutCountsOut`, #149)를 위한
    엄격한 판정이다. 기본은 한쪽 방향(빠짐)만 본다 — 벤더가 문서에 없는 값을
    새로 보내는 것 자체는 사고가 아니고, 우리 분류표가 그 값을 모르는 것만
    사고이기 때문이다.
    """

    expected_label = expected.__name__ if isinstance(expected, type) else "예상 값"
    covered_set = set(covered)
    expected_set = set(expected)
    missing = expected_set - covered_set
    extra = covered_set - expected_set if bidirectional else set()
    if not missing and not extra:
        return

    def _described(values: set) -> list[str]:
        return sorted(str(getattr(item, "value", item)) for item in values)

    message = f"{name} 이 {expected_label} 를 전부 덮지 않는다: {_described(missing)}"
    if bidirectional and extra:
        message += f" (남는 것 {_described(extra)})"
    raise RuntimeError(message)
