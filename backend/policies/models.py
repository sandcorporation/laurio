"""PlatformPolicy — 정책값의 단일 행 (#75, #79, ADR-0023).

수수료율·원천징수율·개최비·연장비·기간·리드타임·배분 컷라인이 `settings.py`의
환경변수 12개와 `DistributionCutline`·`DeliverableType.minimum_prize` 두 테이블에
흩어져 있었다(ADR-0023). #75가 **플랫폼 수수료율과 원천징수율**을, #79가
**배분 컷라인**(옛 `DistributionCutline`)을 이 모델로 옮겼다 — 나머지 열 개
(개최비·연장비·기간·리드타임·주간한도)는 #78의 몫이다. 이후 티켓들이 필드를
추가할 자리로 의도되었다(운영자 API로 바꾸는 것도 #76의 몫이다 — 지금은
`manage.py shell`로만 바꿀 수 있고 그래도 된다).

단일 행(pk=1) 관용구를 쓴다 — 없으면 `policies.services.get_current_policy()`가
기본값으로 만든다.

**코드리뷰 지적 반영(#75 후속)**:

1. 요율에 상한이 없으면 `platform_fee_bps=12000`(120%) 같은 오입력이 그대로
   저장되고, 한참 뒤 지급 요청 도중 `net_amount`(PositiveIntegerField의 DB
   CHECK)가 음수라 500으로 죽는다 — 원인이 지급 경로가 아니라 여기(정책 저장
   시점)인데 증상은 거기서 나타난다. 값을 바꾸는 유일한 경로가 지금은
   `manage.py shell`뿐이라(#76 전) 이 모델 자신이 막아야 한다. 아래 4개
   CheckConstraint가 "말이 안 되는 값은 애초에 저장되지 않는다"를 강제한다 —
   `platform_fee_bps + withholding_tax_bps <= 10000`이면 어떤 prize_amount에도
   `net_amount >= 0`이 수학적으로 보장된다(floor(a)+floor(b) <= floor(a+b)).
2. 원천징수 면제 임계값(과세최저한을 지급액 기준으로 환산한 값, 기본 250,000원)은
   `withholding_tax_bps`가 아니라 `withholding_necessary_expense_bps`(필요경비율)
   에서만 유도된다(`payouts.services._withholding_exempt_threshold`) — 두 요율이
   독립이라, 원천징수율만 바꿔도 면제 임계값이 조용히 틀려지는 사고가 구조적으로
   나지 않는다. 하드코딩된 임계값 필드 자체가 없으므로 "한쪽만 바꿔 불일치"가
   애초에 불가능하다.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models


class PlatformPolicy(models.Model):
    """플랫폼 정책값 — 단일 행(pk=1)만 쓴다.

    상위 등급 Operator만 바꿀 수 있어야 하지만, 그 API는 이 티켓의 범위 밖이다
    (#76). 지금은 `manage.py shell`로만 바뀐다 — 그래서 이 모델의 CheckConstraint가
    말이 안 되는 값이 저장되는 것을 막는 유일한 방어선이다.
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

    # 필요경비율(80%, 기본값 8000bp) — 기타소득금액 = 지급액 × (10000 -
    # withholding_necessary_expense_bps) / 10000. 원천징수 면제 임계값(지급액
    # 기준)은 이 값과 아래 withholding_minor_income_exempt_won에서만 유도된다 —
    # withholding_tax_bps와는 독립이다(코드리뷰 지적 3). 세율 자체를 바꾸는 것과
    # "소득 중 몇 %가 과세 대상인가"는 서로 다른 판단이라 분리했다.
    withholding_necessary_expense_bps = models.PositiveIntegerField(default=8000)

    # 과세최저한(기타소득금액 기준, 원). 국세청 기준 5만원 — 세법이 정한 고정값에
    # 가깝지만, 위 필요경비율과 짝을 이뤄 지급액 기준 임계값을 유도하는 입력이므로
    # 나머지 정책값과 같은 자리(단일 행)에 둔다.
    withholding_minor_income_exempt_won = models.PositiveIntegerField(default=50_000)

    # 배분(Distribution) 컷라인 — Score 백분율이 이 값 이상인 Submission만 무응답
    # 1/N 배분의 자격자다(#79, 옛 `distributions.DistributionCutline`). 그
    # 모델과 같은 단일 행 관용구를 그대로 흡수했다: 기본값 60.00은 옛 모델의
    # 기본값과 같다. `distributions.services._create_distribution_for_contest`가
    # 이 값을 읽어 `Distribution.cutline_percentage`에 스냅샷으로 남긴다 — 이
    # 필드 자체를 바꿔도 이미 만들어진 Distribution의 기록은 흔들리지 않는다
    # (ADR-0006이 Score에 대해 세운 것과 같은 규율).
    distribution_cutline_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("60.00")
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "플랫폼 정책"
        verbose_name_plural = "플랫폼 정책"
        constraints = [
            # "합리적인 상한" — 이 값을 넘는 입력은 오타이지 사업 판단일 수 없다.
            # 이 상한 자체가 정확한 정답은 아니지만(#76이 운영자 API에서 더
            # 세밀하게 다룰 것이다), 지금은 이 모델이 유일한 방어선이므로 반드시
            # 있어야 한다.
            models.CheckConstraint(
                condition=models.Q(platform_fee_bps__lte=9000),
                name="platform_fee_bps_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(withholding_tax_bps__lte=9000),
                name="withholding_tax_bps_sane_upper_bound",
            ),
            # 100%(10000bp)에 닿으면 아래 threshold 유도 계산(10000 - 이 값으로
            # 나눔)이 0으로 나누기가 된다 — 9999까지만 허용해 구조적으로 막는다.
            models.CheckConstraint(
                condition=models.Q(withholding_necessary_expense_bps__lte=9999),
                name="withholding_necessary_expense_bps_below_100_percent",
            ),
            # platform_fee_bps + withholding_tax_bps <= 10000이면 어떤
            # prize_amount에도 fee + withholding <= prize_amount다(정수 나눗셈의
            # floor(a) + floor(b) <= floor(a+b) 성질) — net_amount가 음수가 되어
            # PositiveIntegerField의 DB CHECK에 걸려 500으로 죽는 경로를 애초에
            # 없앤다(코드리뷰 지적 1).
            models.CheckConstraint(
                condition=models.Q(
                    platform_fee_bps__lte=10_000 - models.F("withholding_tax_bps")
                ),
                name="platform_fee_and_withholding_bps_leave_nonnegative_net",
            ),
            # 컷라인은 백분율이다 — 범위 밖의 값(음수, 100% 초과)은 오타이지
            # 사업 판단일 수 없다(#79). 옛 `DistributionCutline`에는 이 방어선이
            # 없었다 — admin이 사라진 뒤 값을 바꾸는 유일한 경로가
            # `manage.py shell`인 지금은 이 모델 자신이 막아야 한다.
            models.CheckConstraint(
                condition=models.Q(
                    distribution_cutline_percentage__gte=Decimal("0.00")
                )
                & models.Q(distribution_cutline_percentage__lte=Decimal("100.00")),
                name="distribution_cutline_percentage_within_0_100",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"PlatformPolicy(platform_fee_bps={self.platform_fee_bps}, "
            f"withholding_tax_bps={self.withholding_tax_bps})"
        )
