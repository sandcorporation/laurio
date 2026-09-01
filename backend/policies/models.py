"""PlatformPolicy — 정책값의 단일 행 (#75, ADR-0023).

수수료율·원천징수율·개최비·연장비·기간·리드타임·배분 컷라인이 `settings.py`의
환경변수 12개와 `DistributionCutline`·`DeliverableType.minimum_prize` 두 테이블에
흩어져 있었다(ADR-0023). 이 티켓(#75)은 그중 **플랫폼 수수료율과 원천징수율
둘만** 이 모델로 옮긴다 — 나머지 열 개(개최비·연장비·기간·리드타임·주간한도)는
#78이, 배분 컷라인은 #79가 각자 옮긴다. 그래서 이 모델은 지금 필드가 둘뿐이지만,
이후 티켓들이 필드를 추가할 자리로 의도되었다(운영자 API로 바꾸는 것도 #76의
몫이다 — 지금은 `manage.py shell`로만 바꿀 수 있고 그래도 된다).

`DistributionCutline`(`distributions.models`)과 같은 관용구를 쓴다 — 단일 행
(pk=1), 없으면 `policies.services.get_current_policy()`가 기본값으로 만든다.
"""

from __future__ import annotations

from django.db import models


class PlatformPolicy(models.Model):
    """플랫폼 정책값 — 단일 행(pk=1)만 쓴다.

    상위 등급 Operator만 바꿀 수 있어야 하지만, 그 API는 이 티켓의 범위 밖이다
    (#76). 지금은 `manage.py shell`로만 바뀐다.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    # 1/10000(bp) 단위 정수 비율로 다뤄 float 오차 없이 원 단위 정수 금액을
    # 계산한다(ADR-0004). 기본값 1000(10%)은 기존 PAYOUT_PLATFORM_FEE_BPS
    # 환경변수의 기본값과 같다.
    platform_fee_bps = models.PositiveIntegerField(default=1000)

    # 기본값 440(4.4%) — 공모전 상금은 기타소득이고 필요경비 80%가 인정되어
    # 기타소득금액(지급액×20%)에 22%가 붙는다 → 지급액 기준 4.4%(ADR-0008).
    # 이전 기본값 330(3.3%)은 사업소득 세율이었다 — 이 티켓이 바로잡는다(#75).
    withholding_tax_bps = models.PositiveIntegerField(default=440)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "플랫폼 정책"
        verbose_name_plural = "플랫폼 정책"

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"PlatformPolicy(platform_fee_bps={self.platform_fee_bps}, "
            f"withholding_tax_bps={self.withholding_tax_bps})"
        )
