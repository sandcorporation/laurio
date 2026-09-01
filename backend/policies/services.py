"""PlatformPolicy 읽기 — 호출 스코프당 한 번 (#75, ADR-0023).

`core.transitions`가 `Clock.now()`를 스캔 한 번당 한 번만 구해 그 값을 인자로
넘기는 것과 같은 관용구다: 값마다(또는 Payout마다) 정책을 다시 조회하면 채점·
배분·지급 경로에서 쿼리가 값의 수·건수만큼 늘어난다. 이 모듈의 함수는 호출자가
요청(또는 스캔) 시작 시점에 정확히 한 번만 부르고, 그 뒤로는 반환값을 계속
재사용해야 한다.
"""

from __future__ import annotations

from .models import PlatformPolicy


def get_current_policy() -> PlatformPolicy:
    """현재 정책 행을 읽는다. 행이 없으면(신선한 DB) 기본값으로 만든다.

    `core.models.ClockOverride`가 쓰는 것과 같은 get_or_create 관용구 — 부팅과
    첫 요청이 마이그레이션 직후에도 그냥 동작해야 한다(ADR-0023). 배분 컷라인도
    이 행의 `distribution_cutline_percentage` 필드에서 나온다(#79) — 옛
    `distributions.DistributionCutline`은 마이그레이션으로 이 모델에 흡수되고
    지워졌다.
    """

    policy, _created = PlatformPolicy.objects.get_or_create(pk=1)
    return policy
