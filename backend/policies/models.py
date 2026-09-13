"""PlatformPolicy — 정책값의 단일 행 (#75/#78/#79, ADR-0023).

수수료율·원천징수율·개최비·연장비·기간·리드타임·배분 컷라인이 `settings.py`의
환경변수 12개와 `DistributionCutline`·`DeliverableType.minimum_prize` 두 테이블에
흩어져 있었다(ADR-0023). 셋으로 나눠 옮겼다 — #75가 플랫폼 수수료율과
원천징수율(과 그 부속값)을, #78이 나머지 열 개(개최비·연장비·기간 4종·
리드타임 3종·지급대행 주간 한도)를, #79가 배분 컷라인(옛
`distributions.DistributionCutline`)을. 운영자 API로 바꾸는 것은 #76이 맡는다 — `version`과 `PolicyChange`가 그것이다.

**지급대행 주간 한도는 성질이 다르다.** 나머지는 우리가 정하는 사업 판단이지만,
이 값은 토스가 정한 사실이다(주간 1천만원, ADR-0020) — 우리 판단으로 올릴 수
있는 값이 아니다. 같은 행에 두되 그 구분을 필드 주석에 남긴다.

단일 행(pk=1) 관용구를 쓴다 — 없으면 `policies.services.get_current_policy()`가
기본값으로 만든다.

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

from decimal import Decimal

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

    # --- 배분 (#79) ---------------------------------------------------------
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
    # --- 제출 자산 개수 상한 (#190, ADR-0027) --------------------------------
    # 한 Submission이 담을 수 있는 자산 수. 사업이 정하는 값이라 배포 없이 운영자가
    # 조정할 수 있어야 하고 바뀌면 이력이 남아야 한다(ADR-0023).
    #
    # **채점 예산 자체는 여기 없다.** `scoring.source_selection.MAX_SOURCE_BYTES`는
    # 모델 토큰 한도에 묶인 기술값이라 환경이 아니라 모델이 정한다 — 정책이 갖는
    # 것은 개수뿐이다.
    max_source_assets = models.PositiveIntegerField(default=5)
    max_demo_video_assets = models.PositiveIntegerField(default=5)
    max_demo_url_assets = models.PositiveIntegerField(default=10)
    max_repository_assets = models.PositiveIntegerField(default=8)

    # `source` + `repository` **합산** 상한. 그 둘은 같은 LLM 컨텍스트 예산을 나눠
    # 쓰므로(#191) 종류별 상한만으로는 막을 수 없다: 5 + 8 = 13개가 300KB를 나누면
    # 개당 23KB로 사실상 무의미한 채점이 되고, 모델 컨텍스트를 넘기면 그 400이
    # `LLMAdapterPermanentError`로 잡혀 **소스를 많이 낸 참가자가 오히려 Score 없이
    # 배분 컷라인에서 탈락한다**.
    #
    # **공개 여부와 무관하게 제출 시점에 센다.** 저장소 공개 판정은 비동기라(#193)
    # 제출 시점에는 어느 저장소가 채점 입력인지 알 수 없다 — 비공개 저장소도 정원을
    # 먹는 대신, "낸 것은 전부 채점된다"가 보장된다. `max_repository_assets`를 10이
    # 아니라 8로 두는 이유도 이것이다(합산 8이 지배하므로 10은 거짓말이 된다).
    max_scoring_input_assets = models.PositiveIntegerField(default=8)

    # Contest 하나에 붙일 수 있는 ContestImage 개수 상한 (#234, ADR-0032). 나머지
    # 자산 상한과 같은 자리(단일 행)에 둔다 — 사업이 정하는 값이라 배포 없이
    # 운영자가 조정할 수 있어야 하고 바뀌면 이력이 남아야 한다(ADR-0023). 이미지는
    # 채점 입력이 아니므로 `max_scoring_input_assets`가 묶는 LLM 컨텍스트 예산과는
    # 무관하다 — 그래서 별도 필드다.
    max_contest_images = models.PositiveIntegerField(default=10)

    # --- 자리만 만든다 — #263 (ADR-0035) -------------------------------------
    # 아래 여섯 필드는 #263 시점에는 아무 동작도 바꾸지 않았다. #261(업로드 용량
    # 강제)·#262(시연 영상 파기 스캔)·#264(스크린샷 자료 종류)가 각자 이 값을
    # 읽어 실제로 쓴다 — #263은 세 후속 티켓이 서로를 기다리지 않도록
    # `PlatformPolicy`에 필드를 한 번에 더해 마이그레이션 리프를 하나로 묶었을
    # 뿐이다. **`max_screenshot_assets`는 #264가 이미 읽는다**(`submissions.api.
    # _KIND_LIMIT_FIELDS`) — 바이트 상한 셋(`max_*_asset_bytes`)과 파기 유예일수는
    # 여전히 #261/#262를 기다린다.
    #
    # 종류별 업로드 바이트 상한(#261). `max_source_assets` 등(개수 상한)과
    # 이름을 구별한다 — `_assets`는 몇 개까지고 `_asset_bytes`는 파일 하나가
    # 얼마나 클 수 있는가다. `PositiveIntegerField`(최대 약 2.1GB)로는 넉넉한
    # 시연 영상 상한을 표현하기 벅차 `PositiveBigIntegerField`를 쓴다
    # (`ledger.models.JournalEntry.amount`와 같은 선택).
    max_source_asset_bytes = models.PositiveBigIntegerField(default=50 * 1024 * 1024)
    # 영상은 소스보다 넉넉하다 — 압도적으로 무거운 자료가 그것뿐이다(ADR-0035).
    max_demo_video_asset_bytes = models.PositiveBigIntegerField(default=500 * 1024 * 1024)
    # 스크린샷은 이미지라 공모전 이미지 상한(`contests.images.MAX_CONTEST_IMAGE_BYTES`,
    # 10MB, ADR-0032)과 같은 자리에 맞춘다. **값을 직접 import하지 않는다** —
    # `contests.images`가 이미 `policies.scope`를 가져다 쓰므로(#234), 반대
    # 방향으로 가져오면 순환 임포트가 된다. 그래서 리터럴을 그대로 복사해 두고,
    # 두 값이 갈라지지 않는지는
    # `tests/test_policies.py::test_screenshot_byte_cap_default_matches_contest_image_cap`가
    # 지킨다.
    max_screenshot_asset_bytes = models.PositiveBigIntegerField(default=10 * 1024 * 1024)
    # 인수 산출물(`handovers.BuildAsset`) — 빌드 설정·서명키·스토어 메타데이터·
    # 실행 문서 같은 작은 파일이 대상이라 소스보다도 상한이 낮다.
    max_build_asset_bytes = models.PositiveBigIntegerField(default=20 * 1024 * 1024)

    # 시연 영상 파일을 파기하기까지의 유예일수 — 이의 창(`judging_ends_at`)이
    # 닫힌 뒤 이만큼 지나야 스캔이 스토리지
    # 오브젝트를 지운다(ADR-0035). 0은 "창이 닫히자마자 지운다"는 뜻이라
    # 유효한 값이다 — 이의 심판이 끝나기 전에 지워지는 사고는 창이 닫혔다는
    # 것 자체가 막는다. 쓰는 곳은 #262.
    demo_video_retention_grace_days = models.PositiveIntegerField(default=30)

    # Submission 하나에 붙일 수 있는 스크린샷 자료 개수 상한 —
    # `max_source_assets` 등과 나란한 자리다. 쓰는 곳은 #264.
    max_screenshot_assets = models.PositiveIntegerField(default=10)

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
            # 코드리뷰 지적(#78 후속) — 리드타임·요금·기간 전부에 상한이
            # 없으면, 예를 들어 deadline_reminder_lead_hours를 24 대신
            # 2400으로 오타내는 순간 다음 스캔에서 모든 PUBLISHED Contest가
            # "마감 임박" 알림을 받고 Contest당 한 번뿐인
            # deadline_reminder_sent_at 플래그가 찍힌다 — 값을 되돌려도 그
            # Contest들의 진짜 마감 알림은 영영 나가지 않는다(되돌릴 수 없는
            # 손상). #75가 bps 요율에 상한을 건 것과 같은 근거가 그대로
            # 적용된다: 이 값을 넘는 입력은 오타이지 사업 판단일 수 없고,
            # 운영자 API(#76) 전까지는 이 모델이 유일한 방어선이다. 아래
            # 상한은 전부 기본값 대비 넉넉한 여유(수십 배)를 두면서도 자릿수가
            # 하나 더 붙는 흔한 오타는 막는다.
            models.CheckConstraint(
                condition=models.Q(contest_listing_fee__lte=10_000_000),
                name="contest_listing_fee_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(judging_extension_fee__lte=10_000_000),
                name="judging_extension_fee_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(judging_period_days__lte=180),
                name="judging_period_days_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(judging_extension_days__lte=180),
                name="judging_extension_days_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(handover_acceptance_period_days__lte=180),
                name="handover_acceptance_period_days_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(distribution_wait_days__lte=180),
                name="distribution_wait_days_sane_upper_bound",
            ),
            # 리드타임 상한(30일=720시간) — 사고 시나리오 그대로(24 -> 2400)를
            # 막는다: 2400은 720보다 훨씬 크다.
            models.CheckConstraint(
                condition=models.Q(deadline_reminder_lead_hours__lte=720),
                name="deadline_reminder_lead_hours_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(judging_end_reminder_lead_hours__lte=720),
                name="judging_end_reminder_lead_hours_sane_upper_bound",
            ),
            models.CheckConstraint(
                condition=models.Q(distribution_final_warning_lead_days__lte=30),
                name="distribution_final_warning_lead_days_sane_upper_bound",
            ),
            # 지급대행 주간 한도는 벤더가 정한 사실이라 "합리적인 값"을 우리가
            # 판단할 대상은 아니지만, 오타 방지 자체는 나머지 필드와 같은
            # 이유로 여전히 유효하다 — 자릿수 하나가 더 붙는 사고를 막는다.
            models.CheckConstraint(
                condition=models.Q(seller_weekly_limit_amount__lte=1_000_000_000),
                name="seller_weekly_limit_amount_sane_upper_bound",
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
            # 자산 상한 0은 "제한 없음"이 아니라 "아무 것도 못 낸다"다 — 소스가
            # 필수인 이상 `max_source_assets=0`이나 `max_scoring_input_assets=0`은
            # 제출 자체를 불가능하게 만든다. 상한 쪽은 오타 방지다: 자산 50개를
            # 허용해야 할 사업적 이유가 없고, 채점 예산을 그만큼 쪼개면 채점이
            # 무의미해진다(#190).
            *(
                models.CheckConstraint(
                    condition=models.Q(**{f"{field}__gte": 1, f"{field}__lte": 50}),
                    name=f"{field}_between_1_and_50",
                )
                for field in (
                    "max_source_assets",
                    "max_demo_video_assets",
                    "max_demo_url_assets",
                    "max_repository_assets",
                    "max_scoring_input_assets",
                    "max_contest_images",
                    "max_screenshot_assets",
                )
            ),
            # 바이트 상한 0은 "제한 없음"이 아니라 "아무 파일도 못 올린다"다 —
            # 위 자산 개수 상한과 같은 근거(#263). 상한 쪽은 오타 방지다: 자릿수
            # 하나가 더 붙는 흔한 실수(50MB를 5GB로)를 막는다.
            models.CheckConstraint(
                condition=models.Q(max_source_asset_bytes__gte=1)
                & models.Q(max_source_asset_bytes__lte=2_000_000_000),
                name="max_source_asset_bytes_sane_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_demo_video_asset_bytes__gte=1)
                & models.Q(max_demo_video_asset_bytes__lte=5_000_000_000),
                name="max_demo_video_asset_bytes_sane_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_screenshot_asset_bytes__gte=1)
                & models.Q(max_screenshot_asset_bytes__lte=100_000_000),
                name="max_screenshot_asset_bytes_sane_range",
            ),
            models.CheckConstraint(
                condition=models.Q(max_build_asset_bytes__gte=1)
                & models.Q(max_build_asset_bytes__lte=1_000_000_000),
                name="max_build_asset_bytes_sane_range",
            ),
            # 유예일수 0(즉시 파기)은 유효한 값이다 — 위 필드 주석 참고. 상한만
            # 막는다(다른 기간 필드와 같은 180일 상한, #78).
            models.CheckConstraint(
                condition=models.Q(demo_video_retention_grace_days__lte=180),
                name="demo_video_retention_grace_days_sane_upper_bound",
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
