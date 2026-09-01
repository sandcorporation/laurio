"""PlatformPolicy — 정책값의 단일 행 (#75/#78, ADR-0023).

수수료율·원천징수율·개최비·연장비·기간·리드타임·배분 컷라인이 `settings.py`의
환경변수 12개와 `DistributionCutline`·`DeliverableType.minimum_prize` 두 테이블에
흩어져 있었다(ADR-0023). #75가 **플랫폼 수수료율과 원천징수율 둘만** 먼저 이
모델로 옮겼고, 이 티켓(#78)이 나머지 열 개(개최비·연장비·기간·리드타임 3종·
지급대행 주간 한도)를 옮긴다 — 배분 컷라인만 #79가 남긴다(같이 손대면 두
체인이 같은 모델에서 충돌한다). 운영자 API로 바꾸는 것은 여전히 #76의 몫이다
— 지금은 `manage.py shell`로만 바꿀 수 있고 그래도 된다.

**지급대행 주간 한도는 성질이 다르다.** 나머지 아홉 개는 우리가 정하는 사업
판단이지만, 이 값은 토스가 정한 사실이다(주간 1천만원, ADR-0020) — 우리
판단으로 올릴 수 있는 값이 아니다. 같은 행에 두되 그 구분을 필드 주석에
남긴다.

`DistributionCutline`(`distributions.models`)과 같은 관용구를 쓴다 — 단일 행
(pk=1), 없으면 `policies.services.get_current_policy()`가 기본값으로 만든다.

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

    # --- 요금 (#78) ---------------------------------------------------------
    # Sponsor가 Contest를 개최할 때 Prize와 별도로 결제하는 개최 등록비(원 단위
    # 정수, ADR-0004). 옛 CONTEST_LISTING_FEE 환경변수의 기본값과 같다.
    contest_listing_fee = models.PositiveIntegerField(default=50_000)

    # 심사기간 유료 연장 1회당 결제 금액(원 단위 정수). 옛 CONTEST_EXTENSION_FEE
    # 환경변수의 기본값과 같다.
    judging_extension_fee = models.PositiveIntegerField(default=30_000)

    # --- 기간 (#78) ---------------------------------------------------------
    # 마감 후 기본 심사기간(일). CLOSED 전이가 일어나는 조건부 UPDATE 안에서
    # deadline_at + 이 값으로 judging_ends_at을 채운다. 옛 JUDGING_PERIOD_DAYS
    # 환경변수의 기본값과 같다.
    judging_period_days = models.PositiveIntegerField(default=7)

    # 유료 연장 1회가 심사기간을 늘리는 길이(일). judging_ends_at 컬럼에만
    # 더해진다 — 예약된 스케줄러 규칙은 건드리지 않는다(ADR-0003). 옛
    # JUDGING_EXTENSION_DAYS 환경변수의 기본값과 같다.
    judging_extension_days = models.PositiveIntegerField(default=7)

    # Award 후 Sponsor가 인수를 확인하지 않아도 이 기간(일)이 지나면
    # 스케줄러가 Escrow를 해제한다. 옛 HANDOVER_ACCEPTANCE_PERIOD_DAYS
    # 환경변수의 기본값과 같다.
    handover_acceptance_period_days = models.PositiveIntegerField(default=14)

    # 심사기간 종료(JUDGING_ENDED) 후 이 기간(일) 동안 아무도 Award하지 않으면
    # 스케줄러가 Score 컷라인을 통과한 Submission들에게 Prize를 1/N로
    # 배분한다. 옛 DISTRIBUTION_WAIT_DAYS 환경변수의 기본값과 같다.
    distribution_wait_days = models.PositiveIntegerField(default=14)

    # --- 알림 리드타임 (#78) -------------------------------------------------
    # 마감이 이만큼(시간) 남으면 Sponsor·참가 Developer에게 미리 알린다. 옛
    # DEADLINE_REMINDER_LEAD_HOURS 환경변수의 기본값과 같다.
    deadline_reminder_lead_hours = models.PositiveIntegerField(default=24)

    # 심사기간 종료가 이만큼(시간) 남으면 Sponsor에게 Award를 상기시킨다. 옛
    # JUDGING_END_REMINDER_LEAD_HOURS 환경변수의 기본값과 같다.
    judging_end_reminder_lead_hours = models.PositiveIntegerField(default=24)

    # Distribution 실행이 이만큼(일) 앞서면 낮 시각(NOTIFICATION_DAYTIME_HOUR)에
    # 금액을 명시한 최종 경고를 보낸다. 옛 DISTRIBUTION_FINAL_WARNING_LEAD_DAYS
    # 환경변수의 기본값과 같다.
    distribution_final_warning_lead_days = models.PositiveIntegerField(default=1)

    # --- 벤더 제약 (#78) -----------------------------------------------------
    # **우리 정책이 아니라 토스가 정한 사실이다**(ADR-0020) — 부분 승인된
    # Seller가 심사 없이 지급받을 수 있는 주간 한도(원 단위 정수). 그 이상은
    # 심사 대기(under_review)로 다룬다, 실패가 아니다. 나머지 필드와 같은
    # 행에 두지만 우리 판단으로 올릴 수 있는 값이 아니다 — 이 구분이 흐려지면
    # 언젠가 누가 화면에서 이 숫자를 올리고 벤더 쪽에서 거절당한다. 옛
    # SELLER_WEEKLY_LIMIT_AMOUNT 환경변수의 기본값과 같다.
    seller_weekly_limit_amount = models.PositiveIntegerField(default=10_000_000)

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
            # 0일 기간은 말이 안 된다("심사기간 0일"은 심사기간이 없다는
            # 뜻이지 정책이 아니다) — #73 스펙이 명시한 거부 대상 중 하나다.
            # 나머지 방어선(운영자 API의 4xx 검증)은 #76의 몫이지만, 지금은
            # 이 모델이 유일한 방어선이므로 여기서도 막는다(#78).
            models.CheckConstraint(
                condition=models.Q(judging_period_days__gte=1),
                name="judging_period_days_at_least_one_day",
            ),
            models.CheckConstraint(
                condition=models.Q(judging_extension_days__gte=1),
                name="judging_extension_days_at_least_one_day",
            ),
            models.CheckConstraint(
                condition=models.Q(handover_acceptance_period_days__gte=1),
                name="handover_acceptance_period_days_at_least_one_day",
            ),
            models.CheckConstraint(
                condition=models.Q(distribution_wait_days__gte=1),
                name="distribution_wait_days_at_least_one_day",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"PlatformPolicy(platform_fee_bps={self.platform_fee_bps}, "
            f"withholding_tax_bps={self.withholding_tax_bps})"
        )
