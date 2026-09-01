"""PlatformPolicy — 정책값의 단일 행 (#75, #76, ADR-0023).

수수료율·원천징수율·개최비·연장비·기간·리드타임·배분 컷라인이 `settings.py`의
환경변수 12개와 `DistributionCutline`·`DeliverableType.minimum_prize` 두 테이블에
흩어져 있었다(ADR-0023). 이 티켓(#75)은 그중 **플랫폼 수수료율과 원천징수율
둘만** 이 모델로 옮긴다 — 나머지 열 개(개최비·연장비·기간·리드타임·주간한도)는
#78이, 배분 컷라인은 #79가 각자 옮긴다. 그래서 이 모델은 지금 필드가 넷뿐이지만,
이후 티켓들이 필드를 추가할 자리로 의도되었다.

`DistributionCutline`(`distributions.models`)과 같은 관용구를 쓴다 — 단일 행
(pk=1), 없으면 `policies.services.get_current_policy()`가 기본값으로 만든다.

**#76이 운영자 API를 얹는다.** 바꾸는 경로는 이제 `POST /api/operator/policy`
하나다 — `manage.py shell`·psql은 더 이상 정상 경로가 아니다(비상시 최후
수단으로는 여전히 남지만 그것이 감사 기록을 남기지 않는다는 점은 그대로다).
`version`이 그 API의 동시성 규율을 지탱한다: `policies.services.update_policy`가
`select_for_update()`로 이 행을 잠그고 `version`이 호출자가 GET에서 읽은 값과
같을 때만 갱신한다 — 두 Operator가 동시에 다른 값으로 바꾸려 하면 먼저 커밋한
쪽만 통과하고 나머지는 409로 거절되어 다시 지금 값을 읽고 재시도해야 한다
(`core.transitions.claim_transition`의 조건부 UPDATE 규율과 같은 정신 — 다만
상태 전이가 아니라 임의 필드 갱신이라 `state_field` 대신 `version`으로 조건을
건다). 이렇게 하지 않으면 두 번째 쓰기가 첫 번째의 결과를 조용히 덮어써
`PolicyChange`의 `before`가 실제 이전 값과 어긋나는(이력이 거짓말하는) 사고가
난다.

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

from django.conf import settings
from django.db import models


class PlatformPolicy(models.Model):
    """플랫폼 정책값 — 단일 행(pk=1)만 쓴다.

    상위 등급 Operator만 `POST /api/operator/policy`로 바꿀 수 있다(#76,
    `core.operator_auth.SuperuserOperatorAuth`). 이 모델의 CheckConstraint는
    여전히 존재한다 — API 레이어의 검증(4xx로 친절하게 거절)이 최전선이고,
    이 제약은 그것을 우회하는 어떤 경로(관리 명령, 마이그레이션, 버그)에도
    말이 안 되는 값이 끝내 저장되지 않게 하는 최후의 방어선이다.
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

    # 낙관적 동시성 제어(#76) — GET이 이 값을 함께 돌려주고, PATCH는 호출자가
    # 그때 읽은 값을 `expected_version`으로 되돌려 보내야 한다.
    # `select_for_update()`로 잠근 뒤 `version`이 일치할 때만 갱신하고, 갱신할
    # 때마다 1 증가시킨다 — 두 Operator가 동시에 바꿔도 하나가 조용히 사라지지
    # 않고, 나중 것은 409로 거절되어 다시 읽고 재시도해야 한다.
    version = models.PositiveIntegerField(default=0)

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
        ]

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"PlatformPolicy(platform_fee_bps={self.platform_fee_bps}, "
            f"withholding_tax_bps={self.withholding_tax_bps})"
        )


class PolicyChange(models.Model):
    """`PlatformPolicy`에 대한 한 번의 변경 사건 — 누가·언제·무엇을 무엇으로·왜 (#76).

    `AppealRuling`이 심판에 신원을 붙인 것과 같은 규율이다: 수수료율을 바꾸는
    것은 이의 하나가 아니라 **앞으로의 모든 돈**을 움직이는 판단이므로, 그
    판단에는 근거(`reason`)와 행위자(`operator`)가 반드시 따라붙는다.

    **행 단위가 아니라 사건 단위다.** 한 번의 PATCH가 여러 필드를 동시에
    바꿀 수 있으므로(예: 수수료율과 원천징수율을 같이 조정), 그 변경들을
    필드마다 따로 남기면 "그때 무엇을 함께 바꿨는가"라는 맥락을 잃는다.
    `before`·`after`는 그 PATCH 요청이 실제로 바꾼 필드만 담은 JSON 딕셔너리다
    (건드리지 않은 필드는 나타나지 않는다) — `policies.services.update_policy`가
    잠금 아래에서 적용 직전·직후 값으로 채운다.

    `operator`는 PROTECT다 — `AppealRuling.ruled_by`·`SourceReading.read_by`와
    같은 이유로, 바꾼 계정을 지워도 감사 기록이 주인을 잃지 않는다(#72가 세운
    관용구). 이 이력은 append-only로 다룬다 — 수정·삭제 엔드포인트가 없다.
    """

    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="policy_changes", on_delete=models.PROTECT
    )
    reason = models.TextField()
    before = models.JSONField()
    after = models.JSONField()
    changed_at = models.DateTimeField()

    class Meta:
        verbose_name = "정책 변경 이력"
        verbose_name_plural = "정책 변경 이력"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"PolicyChange(operator_id={self.operator_id}, at={self.changed_at})"
