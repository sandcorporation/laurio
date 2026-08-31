"""Appeal 도메인 모델 (#21, ADR-0004, ADR-0006).

Developer가 자신의 불변 `Score` 스냅샷에 이의를 제기하고, 운영자가 그 스냅샷의
근거(점수·reasoning·model_version)와 함께 검토해 심판한다. 소스를 담은 `prompt` 는
그 근거에 **포함되지 않는다** — 펼치는 행위로만 나오고 그 행위가 기록된다
(#59·#60, ADR-0022). `Score`는
append-only라 이 앱은 그것을 절대 건드리지 않는다 — 재채점 경로는 존재하지
않는다(ADR-0006). 인용(UPHELD)되면 `ledger`에 정정 분개가 새로 추가될 뿐, 기존
분개는 그대로 남는다.

Submission 하나에 이의제기는 하나만 허용한다(`OneToOneField`) — 재이의는 이
티켓 범위 밖이다.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Appeal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "검토 대기"
        UPHELD = "upheld", "인용"
        REJECTED = "rejected", "기각"

    submission = models.OneToOneField(
        "submissions.Submission", related_name="appeal", on_delete=models.CASCADE
    )
    reason = models.TextField()
    # PENDING 을 벗어나는 전이는 조건부 UPDATE 로만 일어난다(services 참고) — 그것이
    # "정정 분개가 정확히 한 번" 을 보장하는 원자적 지점이다. 아래 AppealRuling 의
    # OneToOne 제약이 같은 사실을 스키마로 한 번 더 못 박는다.
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Appeal(submission={self.submission_id}, status={self.status})"


class AppealRuling(models.Model):
    """한 Appeal 에 대한 Operator 의 심판 (#44, ADR-0018).

    **왜 Appeal 에서 떼어냈나.** 예전에는 심판 결과 네 필드가 Appeal 안에 흩어진 채
    "심판 전엔 비어 있음" 이었고, 그것들이 서로 일관되어야 한다는 약속은 어디에도
    적혀 있지 않았다. 그 상태에서 `ruled_by` 를 다섯 번째로 붙이면 **신원 없는
    심판이 저장될 수 있는 상태가 그대로 남는다** — 이 티켓이 메우려는 바로 그
    공백이다.

    떼어내면 "심판이 존재하면 누가·언제·무엇을 결정했는지도 반드시 있다" 가 규율이
    아니라 **스키마**로 보장된다. 이 테이블에 행이 있다는 것 자체가 그 사실이다.

    `ruled_by` 는 PROTECT 다 — 심판한 Operator 계정을 지우면 감사 기록이 주인을
    잃는다. 비활성화는 하되(#45) 삭제는 막는다.

    `correction_*` 둘만 null 을 허용한다. 기각에는 움직인 돈이 없기 때문이고, 그것이
    이 테이블에서 "비어 있어도 되는" 유일한 이유다.
    """

    class Decision(models.TextChoices):
        UPHELD = "upheld", "인용"
        REJECTED = "rejected", "기각"

    appeal = models.OneToOneField(Appeal, related_name="ruling", on_delete=models.CASCADE)
    ruled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="appeal_rulings", on_delete=models.PROTECT
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    # 인용이든 기각이든 이유를 남긴다. 돈을 움직이는(또는 움직이지 않기로 하는)
    # 판단에 근거가 없으면 감사 기록으로서 값이 없다.
    note = models.TextField()
    ruled_at = models.DateTimeField()

    # 인용 시에만 채워진다 — Operator 가 근거를 검토해 직접 정하는 정정 금액이다.
    # 자동으로 재계산되지 않는다(재채점 경로가 없는 것과 같은 이유 — 이 값은 항상
    # 사람의 판단이다, ADR-0006).
    correction_amount = models.PositiveIntegerField(null=True, blank=True)
    # 인용 시 원장에 남긴 정정 분개. 원장에는 행위자 컬럼이 없다(ADR-0018) —
    # 이 번호로 이 행을 되짚으면 신원이 나오므로 감사 사슬은 여기서 이어진다.
    correction_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ruled_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"AppealRuling(appeal={self.appeal_id}, decision={self.decision})"


class SourceReading(models.Model):
    """Operator 가 이의 심판 중 제출 소스를 펼친 사건 하나 (#60, ADR-0022).

    **상태가 아니라 사건이다.** 같은 Operator 가 같은 Appeal 에서 다시 펼치면 행이
    하나 더 쌓인다 — 중복 제거하면 "한 번 봤다"와 "열 번 봤다"가 구별되지 않아
    기록의 값이 사라진다. `AppealRuling` 이 그랬듯(#44) 네 필드 전부 NOT NULL 이고,
    `read_by` 는 PROTECT 다 — 열람한 Operator 계정을 지워도 감사 기록이 주인을
    잃지 않는다.

    `submission` 을 `appeal` 과 별도 필드로 둔다. `appeal.submission_id` 로도
    구할 수 있지만(OneToOne), Developer 쪽 조회 표면(#61)이 자기 Submission 의
    열람 기록을 appeal 을 거치지 않고 바로 찾아야 하므로 여기 직접 둔다.
    """

    submission = models.ForeignKey(
        "submissions.Submission", related_name="source_readings", on_delete=models.CASCADE
    )
    appeal = models.ForeignKey(Appeal, related_name="source_readings", on_delete=models.CASCADE)
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="source_readings", on_delete=models.PROTECT
    )
    read_at = models.DateTimeField()

    class Meta:
        ordering = ["-read_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"SourceReading(submission={self.submission_id}, appeal={self.appeal_id})"
