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
    NEW_CONTEST_IN_CATEGORY = "new_contest_in_category", "관심 Category 신규 Contest"


# 유형별 거래성/광고성 플래그. 광고성(is_promotional=True)은 옵트인 없이 발송되지
# 않는다(ADR-0010). 거래성/광고성은 배타적이지 않게 둘 다 갖는 구조도 가능하지만,
# 지금 정의된 유형들은 전부 어느 한쪽으로만 떨어진다.
NOTIFICATION_TYPE_FLAGS: dict[str, dict[str, bool]] = {
    NotificationType.DEADLINE_REMINDER: {"is_transactional": True, "is_promotional": False},
    NotificationType.JUDGING_PERIOD_ENDING_REMINDER: {
        "is_transactional": True,
        "is_promotional": False,
    },
    NotificationType.DISTRIBUTION_FINAL_WARNING: {
        "is_transactional": True,
        "is_promotional": False,
    },
    NotificationType.RESULT_NOTICE: {"is_transactional": True, "is_promotional": False},
    NotificationType.NEW_CONTEST_IN_CATEGORY: {"is_transactional": False, "is_promotional": True},
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
    """Laurio 가 당사자에게 보내는 통지 한 건(CONTEXT.md).

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
        SENT = "sent", "성공"
        FAILED = "failed", "실패"

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
