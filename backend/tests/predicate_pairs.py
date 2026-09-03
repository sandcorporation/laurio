"""술어 ↔ Q 쌍의 일치를 경계값으로 지키는 공용 헬퍼 (#143, #124).

파이썬 술어(`contest.judging_window_open(now)`)를 Q 에서 파생하거나 그 반대는 일반적으로 불가능하다.
대신 경계 직전·경계·직후 픽스처를 만들어 「술어 결과 == Q 필터 포함 여부」를 단언한다 —
`test_home_curation` 의 경계값 테스트가 먼저 이 모양이었고 그것을 일반화했다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable


def assert_predicate_matches_q(cases: Iterable[tuple[str, object]], predicate: Callable, queryset) -> None:
    """`cases` 는 (라벨, 저장된 모델 인스턴스) 쌍. `predicate(instance)` 가 참인 것과 `queryset` 이
    돌려주는 pk 집합이 정확히 같아야 한다."""

    cases = list(cases)
    assert cases, "경계값 픽스처가 비어 있다"
    included = set(queryset.values_list("pk", flat=True))
    for label, instance in cases:
        expected = bool(predicate(instance))
        actual = instance.pk in included
        assert expected == actual, (
            f"{label}: 술어는 {expected!r}인데 Q 필터는 {actual!r} — 경계에서 두 표현이 갈렸다"
        )
