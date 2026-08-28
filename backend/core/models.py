from django.db import models


class ClockOverride(models.Model):
    """테스트가 시각을 고정·전진시키기 위한 오버라이드. 단일 행(pk=1)만 쓴다.

    ADR-0003: "시각은 주입 가능한 의존성이다". 앱 코드는 `datetime.now()` 나
    `django.utils.timezone.now()` 를 직접 부르지 않고 항상 `core.clock.Clock.now()` 를
    거친다. 이 행이 비어 있으면 `Clock.now()` 는 실제 시각을 돌려주고, 테스트가 이 행을
    채우면 그 시각을 고정된 "현재"로 취급한다. 프로덕션에서는 이 행이 채워질 일이 없다.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    overridden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "시각 오버라이드"
        verbose_name_plural = "시각 오버라이드"

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"ClockOverride(overridden_at={self.overridden_at!r})"


class ScheduledStateDemo(models.Model):
    """ADR-0003 조건부 UPDATE 전이 메커니즘의 최소 증명용 스캐폴딩.

    실제 `Contest` 모델은 아직 없다(#8, 다른 체인 소관). 이 모델은 오직
    "전이 시각이 지난 행을 스캔해 `UPDATE ... WHERE id=? AND state='이전상태'` 로만
    전이시키고, rowcount 가 1일 때만 통과시킨다"는 메커니즘을 시연하기 위한 것이며
    도메인 로직을 담지 않는다. 이후 티켓이 실제 모델에 같은 메커니즘
    (`core.transitions.register_transition` / `core.transitions.claim_transition`)을
    재사용하면 된다.
    """

    class State(models.TextChoices):
        PENDING = "pending", "대기"
        DONE = "done", "완료"

    label = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.PENDING)
    due_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "전이 스캐폴딩"
        verbose_name_plural = "전이 스캐폴딩"
        # 틱 스캔의 WHERE 절(state=... AND due_at<=...)이 타는 인덱스. 없으면 백로그가
        # 쌓였을 때 매 틱마다 시퀀셜 스캔이 된다.
        indexes = [models.Index(fields=["state", "due_at"], name="core_ssd_state_due_at_idx")]

    def __str__(self) -> str:  # pragma: no cover - admin 편의용
        return f"ScheduledStateDemo({self.pk}, {self.state})"
