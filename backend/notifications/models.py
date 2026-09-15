from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    """Notification 유형. 각 유형은 거래성/광고성 플래그를 고정으로 갖는다(ADR-0010).

    실제 Contest 라이프사이클 이벤트에 연결하는 것은 이 티켓 범위 밖이다(#19). 여기서는
    유형 어휘와 플래그만 정의해, 나중에 그 이벤트들이 이 유형들로 알림을 만들 수 있게
    해둔다. User Story 80~89 에 나오는 유형 중 최소 집합을 담았다.
    """

    DEADLINE_REMINDER = "deadline_reminder", "마감 임박 알림"
    JUDGING_PERIOD_ENDING_REMINDER = "judging_period_ending_reminder", "심사기간 종료 임박 알림"
    DISTRIBUTION_FINAL_WARNING = "distribution_final_warning", "Distribution 최종 경고"
    RESULT_NOTICE = "result_notice", "결과 알림"
    # 채점이 끝났다 — 이의 창이 열렸다는 신호다(#74). 기한을 만들었으면 그
    # 시작을 알리는 것까지가 같은 결정이다: 알리지 않으면 그 기한은 "들어와 본
    # 사람에게만 공정한" 규칙이 된다.
    SCORING_COMPLETE = "scoring_complete", "채점 완료"
    # 이의가 심판됐다 — 인용이든 기각이든. 낸 사람이 결과를 알려면 들어와 봐야
    # 하는 상태를 없앤다. **심판자 개인의 이름은 담지 않는다**(#61 이 열람
    # 기록에 대해 세운 것과 같은 이유 — 운영자 신원을 참가자에게 흘리지 않는다).
    APPEAL_RULED = "appeal_ruled", "이의 심판 완료"
    NEW_CONTEST_IN_CATEGORY = "new_contest_in_category", "관심 Category 신규 Contest"
    # `Hold`(CONTEXT.md)의 차례가 Developer 로 바뀐 Payout 을 알린다(#169) — 주민등록번호
    # 제출 · 연락처 제출 · 지급대행사의 본인인증 문자 · 실이체 재시도 넷 전부 이 유형
    # 하나다. 어느 `Hold` 인지는 유형이 아니라 알림의 context 로 싣는다(payouts.progress.
    # HoldKind) — 상태마다 유형을 만들면 Hold → 문구 규칙이 두 곳에 생긴다(#130 이 세
    # 렌더러에서 하나로 모은 것을 다시 쪼개는 셈이다).
    PAYOUT_AWAITS_YOU = "payout_awaits_you", "지급이 당신을 기다린다"
    # 강의실 채점 예산이 경고 임계를 넘었다(#295) — 강사가 자기 클래스의
    # `classroom.Class.token_budget`을 정했을 때만 쓰인다. 강의실은 공모전
    # 가족이 아니라(ADR-0037) 이 유형을 만드는 쪽(`classroom.scoring`)이
    # `notifications`를 부르지 이 앱이 강의실을 알지 않는다 — 유형 어휘만
    # 여기 산다.
    CLASSROOM_TOKEN_BUDGET_WARNING = "classroom_token_budget_warning", "강의실 채점 예산 경고"
    # 강의실 제출 하나의 채점이 끝났다(#303) — 통과든 미통과든, 플랫폼 자동
    # 미달이든 매 시도마다 정확히 한 번. 낸 사람(`ClassMember.user`)에게만
    # 간다 — 강사에게는 자기가 낸 것이 아니면 가지 않는다(#301과 같은 이유로
    # `classroom.scoring`이 이 앱을 모른 채 이 유형 이름만 쓴다).
    CLASSROOM_SUBMISSION_SCORED = "classroom_submission_scored", "강의실 제출 채점 완료"
    # 강의실 채점 키가 벤더에게 거절당했다(#355·#356, ADR-0045) — 그 클래스의
    # 강사에게만 간다, 참여자에게는 절대 가지 않는다. 상태가 "거부됨"으로
    # **바뀌는 그 순간**에만 한 번 간다(`classroom.scoring._mark_scoring_key_
    # rejected`) — 밀린 제출이 몇 건이든, tick이 몇 번을 돌든 상태 전이 한
    # 번에 하나다. 강사가 키를 고쳤다가 그 키도 거절당하면 그때 다시 간다.
    CLASSROOM_SCORING_KEY_REJECTED = "classroom_scoring_key_rejected", "강의실 채점 키 거부"
    # Operator 가 한 사용자에게 직접 보내는 알림이다(#418, CONTEXT.md 「운영자
    # 알림」) — 무료 공모전 수상자에게 개최자 보상(기프티콘 등)을 전하는 것이
    # 첫 쓰임이다. 제목·본문·(선택) 이미지는 이 앱의 `OperatorNotice`가 담고,
    # 이 유형 자체는 어휘만 정의한다(다른 강의실 유형과 같은 분리 원칙). 앱
    # 안에서만 보이고 문자 채널로 나가지 않으며(`is_internal_only`), 강의실
    # 알림이 아니라 `CLASSROOM_NOTIFICATION_TYPES`에 넣지 않는다.
    OPERATOR_NOTICE = "operator_notice", "운영팀 알림"


#: 강의실 제품이 만드는 알림 유형 전부(#304) — 클래스 알림 화면·종 배지가 이
#: 집합만 센다. 공모전 마감·지급·이의 심판 등은 여기 들어가지 않는다. 지금은
#: `is_internal_only`인 유형과 겹치지만(둘 다 클래스 알림이 전부다) 의도적으로
#: 별개의 목록이다 — 하나는 "밖으로 나가는가"를, 하나는 "어느 제품 것인가"를
#: 답한다. 나중에 강의실 알림 중 밖으로 나가는 것이 생겨도 이 목록만 늘리면 된다.
CLASSROOM_NOTIFICATION_TYPES = frozenset(
    {
        NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING,
        NotificationType.CLASSROOM_SUBMISSION_SCORED,
        NotificationType.CLASSROOM_SCORING_KEY_REJECTED,
    }
)


# 유형별 거래성/광고성/야간유예/외부발송 플래그. 광고성(is_promotional=True)은
# 옵트인 없이 발송되지 않는다(ADR-0010). 거래성/광고성은 배타적이지 않게 둘 다
# 갖는 구조도 가능하지만, 지금 정의된 유형들은 전부 어느 한쪽으로만 떨어진다.
#
# `is_quiet_hours_exempt`(#169, ADR-0010 개정)는 야간(21~08시) 전면 유예의 예외를
# 여는 유일한 자리다 — 호출부(`create_notification` 을 부르는 자리)가 발송할 때마다
# "이건 급하다"고 주장할 수 있게 하지 않는다. 예외를 받는 것은 `PAYOUT_AWAITS_YOU`
# 하나뿐이다.
#
# `is_internal_only`(#301)는 이 유형이 **어느 채널로도 밖에 나가지 않는다**는
# 성질을 고정한다 — 알림톡·SMS·LMS 어느 것도 시도하지 않고, 그래서 야간 연기
# 대상도 되지 않는다(보낼 것 자체가 없으니 미룰 것도 없다). 만드는 쪽이 매번
# "이건 안 보내도 된다"고 주장하는 게 아니라 유형이 그런 것이다 — 호출부에
# 이 성질을 뒤집을 자리를 열어두지 않는다.
NOTIFICATION_TYPE_FLAGS: dict[str, dict[str, bool]] = {
    NotificationType.DEADLINE_REMINDER: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    NotificationType.JUDGING_PERIOD_ENDING_REMINDER: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    NotificationType.DISTRIBUTION_FINAL_WARNING: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    NotificationType.RESULT_NOTICE: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    # 둘 다 거래성이다 — 참가자가 낸 것에 대한 처리 결과이지 광고가 아니므로
    # 옵트인이 필요 없다(ADR-0010).
    NotificationType.SCORING_COMPLETE: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    NotificationType.APPEAL_RULED: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    NotificationType.NEW_CONTEST_IN_CATEGORY: {
        "is_transactional": False,
        "is_promotional": True,
        "is_quiet_hours_exempt": False,
        "is_internal_only": False,
    },
    # 유일한 야간유예 예외(#169, ADR-0010 개정) — 광고성 옵트인과 무관하게(거래성)
    # 발송되고, 야간에도 즉시 나간다. ADR-0010 자신이 전면 차단을 "의도적 초과
    # 준수"라 적었고 정보통신망법의 야간 제한은 광고성에만 걸리므로, 법적 요구를
    # 낮추는 것이 아니라 스스로 얹은 여유분을 이 유형 하나에서만 거두는 것이다.
    NotificationType.PAYOUT_AWAITS_YOU: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": True,
        "is_internal_only": False,
    },
    # 강사 본인의 지출에 대한 경고다 — 거래성이고 옵트인이 필요 없다. **서비스
    # 안에서만 보낸다**(#301) — 학습용 도구라 밤에 휴대폰이 울릴 일이 아니고,
    # 예산이 찼다는 사실 자체는 채점 정지 상태로 이미 보존돼 다음 아침에 봐도
    # 늦지 않는다. 강의실 알림은 전부 이 규칙 하나로 묶인다 — 만드는 쪽마다
    # "이건 문자로 안 나가도 된다"고 따로 주장하지 않는다.
    NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": True,
    },
    # 낸 사람 자신의 제출에 대한 처리 결과다 — 거래성이고 옵트인이 필요 없다.
    # 강의실 알림은 전부 서비스 안에서만이라는 같은 규칙을 받는다(#301, #303).
    NotificationType.CLASSROOM_SUBMISSION_SCORED: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": True,
    },
    # 강사 본인의 계정 문제(키 거부)에 대한 경고다 — 거래성이고 옵트인이
    # 필요 없다. 강의실 알림은 전부 서비스 안에서만이라는 같은 규칙을
    # 받는다(#301, #356).
    NotificationType.CLASSROOM_SCORING_KEY_REJECTED: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": True,
    },
    # Operator 가 사람 하나에게 보내는 거래성 알림이다(#418) — 전화번호가 없는
    # 사람(본인확인을 하지 않은 사람)에게도 닿아야 하므로 애초에 문자 채널을
    # 시도하지 않는다(`is_internal_only`). 광고성이 아니므로 옵트인이 필요
    # 없고, 야간에도 앱 안에서는 바로 보인다(발송 자체가 없으니 미룰 것도
    # 없다 — 다른 internal_only 유형과 같은 이유).
    NotificationType.OPERATOR_NOTICE: {
        "is_transactional": True,
        "is_promotional": False,
        "is_quiet_hours_exempt": False,
        "is_internal_only": True,
    },
}


class NotificationOptIn(models.Model):
    """광고성 Notification 유형에 대한 사용자의 사전 동의(User Story 83).

    거래성 유형에는 옵트인이 필요 없으므로 이 테이블에 행이 없어도 무관하다.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    opted_in = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "notification_type"], name="unique_optin_per_user_and_type"
            )
        ]
        verbose_name = "알림 옵트인"
        verbose_name_plural = "알림 옵트인"


class Notification(models.Model):
    """Codemit 가 당사자에게 보내는 통지 한 건(CONTEXT.md).

    도달 여부와 무관하게 발송 이력 자체가 통지의 증거다. 상태는 "발송 예정"과
    "발송됨"이 구분된 채 관리된다(ADR-0010): QUEUED 는 즉시 시도 대상, DEFERRED 는
    야간 차단으로 다음 날 08시까지 대기 중, SENT/FAILED 는 시도가 끝난 것,
    BLOCKED_NO_OPT_IN 은 광고성인데 옵트인이 없어 애초에 시도하지 않은 것이다.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "발송 대기(즉시)"
        DEFERRED = "deferred", "야간 연기"
        SENT = "sent", "발송됨"
        FAILED = "failed", "발송 실패(전 채널 소진)"
        BLOCKED_NO_OPT_IN = "blocked_no_opt_in", "옵트인 없음으로 차단"
        # 유형 자체가 `is_internal_only`인 알림의 종결 상태(#301) — 채널을
        # 한 번도 시도하지 않았다는 뜻이다. `FAILED`(시도했지만 전부
        # 실패했다)와 뜻이 다르므로 상태를 공유하지 않는다: 이 상태는
        # `dispatches`가 항상 비어 있다.
        NOT_DISPATCHED = "not_dispatched", "채널 미시도(서비스 내부 전용)"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    is_transactional = models.BooleanField()
    is_promotional = models.BooleanField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    # 야간 연기일 때만 채워진다 — "다음 날 08시"라는 확정된 발송 예정 시각.
    scheduled_for = models.DateTimeField(null=True, blank=True)
    # QUEUED로 (재)진입한 시각(#10 리뷰 지적). DEFERRED->QUEUED 선점과 같은 조건부
    # UPDATE 안에서 함께 채워진다(core.transitions.claim_transition 의 extra_fields).
    # 이 필드가 있어야 "선점은 됐는데 발송 시도 도중 예외로 멈춘" 행을 야간 큐
    # 스캐너가 다시 찾아 재시도할 수 있다 — DEFERRED만 다시 줍던 예전 스캐너는 이런
    # 행을 영원히 놓쳤다. Django의 auto_now는 쓰지 않는다 — auto_now는 실제 벽시계를
    # 쓰고 이 프로젝트의 주입 가능한 Clock을 우회하므로, 테스트가 시각을 고정해도
    # 이 필드만 어긋난다.
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    # 수신자가 알림 목록을 연 시점 — 발송 측 상태(위 `Status`)와는 완전히 다른 축이다
    # (#230). `status`는 "우리가 이걸 내보냈는가"를, `read_at`은 "받는 사람이 이걸
    # 봤는가"를 답한다 — 하나가 없어도(예: `FAILED`) 다른 하나는 성립할 수 있고(웹
    # 화면에서 실패 이력을 읽었다), 읽었다고 발송 이력(`status`·`dispatches`)이
    # 바뀌지 않는다는 AC가 그래서 구조적으로 성립한다: 이 필드는 어떤 발송 로직도
    # 참조하지 않는 순수 추가 컬럼이다. `null`이 "안 읽음", 값이 있으면 그 시각에
    # 읽었다는 뜻 — boolean이 아니라 시각을 남기는 이유는 이 저장소의 다른 "언제
    # 됐는가" 필드들(`claimed_at`·`scheduled_for`)과 같다: 나중에 "언제 읽었는지"가
    # 필요해지면 다시 물을 컬럼이 이미 있다.
    read_at = models.DateTimeField(null=True, blank=True)

    # 실제 발송 문구를 채우는 데 쓰이는 구조화된 맥락(#19) — 예: Distribution
    # 최종 경고의 금액(ADR-0009 "무엇을 잃게 되는지 알아야 한다"), 대상 Contest.
    # notifications 기반(#18)의 dispatch·quiet-hours·fallback 로직은 이 필드를
    # 전혀 참조하지 않는다 — 실제 채널 어댑터(장차 실물 카카오 연동)가 문구를
    # 렌더링할 때 쓸 자리이자, Sponsor의 발송 이력 화면이 "무엇을 통지받았는지"를
    # 보여주는 근거다.
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "알림"
        verbose_name_plural = "알림"
        indexes = [
            # 야간 큐 스캔의 WHERE 절(status='deferred' AND scheduled_for<=...)이 타는 인덱스.
            models.Index(fields=["status", "scheduled_for"], name="notif_status_sched_idx"),
            # QUEUED에 멈춰 있는 행을 찾는 WHERE 절(status='queued' AND claimed_at<=...)
            # 이 타는 인덱스.
            models.Index(fields=["status", "claimed_at"], name="notif_status_claimed_idx"),
            # 안 읽은 개수(벨 배지, #230)의 WHERE 절
            # (recipient_id=... AND read_at IS NULL)이 타는 인덱스.
            models.Index(fields=["recipient", "read_at"], name="notif_recipient_read_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"Notification({self.pk}, {self.notification_type}, {self.status})"


class NotificationDispatch(models.Model):
    """채널 하나에 대한 발송 시도 한 번의 기록(ADR-0009).

    채널별 발송 시각·결과·실패사유를 전부 보존한다 — 도달 콜백이 없는 채널도 "시도했다"
    는 사실 자체가 증거다.
    """

    class Channel(models.TextChoices):
        ALIMTALK = "alimtalk", "알림톡"
        SMS = "sms", "SMS"
        LMS = "lms", "LMS"

    class Status(models.TextChoices):
        # 벤더를 부르기 직전에 남긴다(#51 코드리뷰 지적 7) — 벤더 호출이 실제로
        # 성공한 "뒤" 이 행을 SENT로 확정 "전"에 프로세스가 죽으면, 이 행이
        # PENDING인 채로 남아 "이 채널을 이미 시도했을 수도 있다"는 증거가
        # 된다. 정상적으로 끝난 요청·응답에서는 이 상태가 최종적으로 남지
        # 않는다 — SENT/FAILED 중 하나로 같은 요청 안에서 항상 갱신된다.
        PENDING = "pending", "발송 시도 중(결과 미확정)"
        SENT = "sent", "성공"
        FAILED = "failed", "실패"
        # PENDING인 채 재선점된 채널의 종결 상태(#51 3차 코드리뷰 지적 1).
        # FAILED로 확정하면 두 가지가 동시에 틀린다 — ① 실제로는 벤더가
        # 성공했을 수도 있는데 "확정 실패"로 이력에 남고, ② 다음 재선점이
        # FAILED를 "안전하게 재시도해도 되는 실패"로 오인해 이미 성공했을 수
        # 있는 채널에 다시 벤더를 불러 재과금·중복 도달을 만든다(정확히 이
        # PENDING 처리 자체가 막으려던 사고). 그렇다고 PENDING 그대로 두면
        # 사유가 빈 채로 무기한 남아 발송 이력이 아무것도 설명하지 못한다
        # (#51 2차 코드리뷰 지적 6). INDETERMINATE는 이 둘을 동시에 만족한다
        # — 이력에는 "왜 재시도하지 않았는지"가 사유로 남고, `_attempt_dispatch`
        # 는 이 상태도 SENT/PENDING과 같이 "이미 손댔으니 다시 벤더를 부르지
        # 않는다"로 취급한다.
        INDETERMINATE = "indeterminate", "결과 불명(재시도 안 함)"

    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="dispatches"
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(max_length=20, choices=Status.choices)
    attempted_at = models.DateTimeField()
    failure_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "채널별 발송 이력"
        verbose_name_plural = "채널별 발송 이력"
        # attempted_at 만으로는 동시에(같은 시각으로) 남는 여러 채널 시도의 순서를
        # 보장하지 못한다 — 이 프로젝트는 시각을 호출 스코프당 한 번만 구해 재사용하므로
        # 같은 Notification 의 여러 채널 시도가 attempted_at 이 완전히 같은 값을 갖는
        # 것이 정상이다. id를 2차 정렬키로 둬서 "시도한 순서"가 항상 안정적으로 나오게
        # 한다.
        ordering = ["attempted_at", "id"]

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"NotificationDispatch({self.notification_id}, {self.channel}, {self.status})"


class OperatorNotice(models.Model):
    """`NotificationType.OPERATOR_NOTICE` 한 건의 제목·본문·보낸 운영자(#418).

    이 값들을 `Notification.context`(다른 유형들이 문구 렌더링에 쓰는 자리)에
    두지 않는 이유는 하나다 — `context`는 그대로 수신자 앱에 노출되는데,
    `APPEAL_RULED`가 심판자 이름을 담지 않는 것과 같은 이유로 **보낸 운영자
    신원은 참가자에게 보이면 안 된다.** 그래서 신원이 필요한 값(`sent_by`)은
    별도 테이블에 두고, `notifications.api._serialize`가 제목·본문·이미지
    유무만 골라 수신자 응답에 얹는다.

    보낸 뒤 고치거나 지울 API 가 없다(append-only) — 잘못 보냈으면 새 알림으로
    바로잡는다(CONTEXT.md 「운영자 알림」).
    """

    notification = models.OneToOneField(
        Notification, on_delete=models.CASCADE, related_name="operator_notice"
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # PROTECT — Operator 계정이 지워져도(비활성화는 삭제가 아니지만) 이 이력에서
    # "누가 보냈는가"가 사라지면 안 된다. `policies.models.PolicyChange.operator`와
    # 같은 감사 규율(ADR-0023).
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    # 이미지 한 장(선택, #419) — **비공개 버킷**의 객체 키만 담는다. 공개
    # 주소를 저장하지 않는다(ADR-0032의 공개 이미지 버킷과 다른 버킷, 공모전
    # 이미지와 달리 기프티콘 바코드처럼 주소만으로 새면 안 되는 값이라서다).
    # 다운로드 주소는 받는 사람·보낸 운영자에게만 열 때마다 짧게 발급한다
    # (`notifications.operator_api`·`notifications.api`).
    image_object_key = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "운영팀 알림"
        verbose_name_plural = "운영팀 알림"

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"OperatorNotice({self.notification_id}, {self.title!r})"
