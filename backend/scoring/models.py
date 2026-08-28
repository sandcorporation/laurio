"""AI 채점 결과 (#12, ADR-0006, ADR-0014).

`Score`는 편의 기능이 아니라 Distribution 대상을 가르는 판정자다. LLM은 비결정적이라
같은 Submission을 두 번 채점하면 다른 점수가 나올 수 있으므로, 마감 직후 1회 채점한
결과를 점수·근거·프롬프트·모델 버전과 함께 불변 스냅샷으로 고정한다. `ledger.models`가
이미 검증한 `AppendOnlyModel`(원장의 append-only 규율, ADR-0004)을 그대로 재사용한다 —
"한 번 저장되면 다시 저장(수정)하거나 지울 수 없다"는 요구가 Score에도 글자 그대로
적용되기 때문이다. 재채점 코드 경로는 존재하지 않는다: `scoring.services`는 이미
Score가 있는 Submission을 항상 건드리지 않고 지나친다.
"""

from __future__ import annotations

from django.db import models

from ledger.models import AppendOnlyModel


class Score(AppendOnlyModel):
    """Submission 하나에 대한 불변 채점 스냅샷. 마감 직후 정확히 한 번만 만들어진다."""

    submission = models.OneToOneField(
        "submissions.Submission", related_name="score", on_delete=models.CASCADE
    )
    # 필수 Requirement 달성률(0.00 ~ 100.00). Distribution(#16) 컷라인 판정의
    # 유일한 근거가 될 값이다(CONTEXT.md의 Score 정의) — 이 티켓은 그 소비처를
    # 만들지 않지만, 값의 의미는 이미 그렇게 고정한다.
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    # 실제 호출에 쓰인 LLM 모델 식별자(예: "fake-llm-v1", 실제 어댑터가 붙으면
    # "claude-sonnet-4-5-20250929" 같은 값). 나중에 어떤 모델이 이 판정을 내렸는지
    # 감사할 수 있어야 한다(ADR-0006).
    model_version = models.CharField(max_length=200)
    # LLM에 실제로 보낸 프롬프트 전문 — 소스 발췌·Evidence·자가 응답을 포함한다.
    # 이의제기(#21) 절차에서 운영자가 "무엇을 근거로 이 판정이 나왔는지"를 그대로
    # 재현해 볼 수 있어야 한다.
    prompt = models.TextField()
    # Requirement별 판정 근거. [{"requirement_id": int, "is_met": bool, "reasoning": str}, ...]
    reasoning = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Score"
        verbose_name_plural = "Score"

    def __str__(self) -> str:  # pragma: no cover
        return f"Score(submission={self.submission_id}, percentage={self.percentage})"


class ScoringAttempt(models.Model):
    """실패한 채점 시도의 이력.

    Score와 달리 append-only일 필요는 없다 — 그 자체가 판정이 아니라 "언제, 왜
    실패했는지"에 대한 운영 로그다. 운영자가 채점이 끝나지 않은 Contest를 식별할 때
    (#12 AC) 가장 최근 실패 사유를 보여주는 데 쓴다.
    """

    submission = models.ForeignKey(
        "submissions.Submission", related_name="scoring_attempts", on_delete=models.CASCADE
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    error = models.TextField()

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "채점 실패 이력"
        verbose_name_plural = "채점 실패 이력"

    def __str__(self) -> str:  # pragma: no cover
        return f"ScoringAttempt(submission={self.submission_id}, at={self.attempted_at})"
