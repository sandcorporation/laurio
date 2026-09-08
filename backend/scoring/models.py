"""AI 채점 결과 (#12, ADR-0006, ADR-0014, #219/ADR-0030).

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
    # 채점에 실제로 쓰인 자산 목록 (#191, ADR-0027) —
    # [{"asset_id": int, "commit_sha": str | None}, ...]. 이의를 제기하는 사람과
    # 심판하는 사람이 "같은 것을 보고" 이야기하려면 무엇을 보고 채점했는지가
    # 스냅샷에 고정돼야 한다. `commit_sha`는 `kind=repository` 자산에만 붙고
    # (#193이 채운다), `kind=source` 자산은 항상 null이다. Score는 append-only라
    # (ADR-0006) 이 목록도 한 번 쓰이면 다시 바뀌지 않는다 — 나중에 자산이 지워져도
    # (제출 수정은 마감 전에만 가능하므로 실제로는 일어나지 않지만) 이 스냅샷은
    # 그대로 남는다.
    scored_assets = models.JSONField(default=list)
    # 채점 시점에 저장소 도달 가능성을 직접 재확인한 기록 (#219, ADR-0030) —
    # [{"asset_id": int, "checked_at": iso str, "is_public": bool | None,
    #   "source": "live_check" | "fallback_last_known", "detail": str}, ...].
    # `SubmissionAsset.is_public_checked_at`은 그 뒤 스캔이 계속 덮어쓰는 값이라
    # "채점 그 순간에 어떤 상태였는가"를 나중에 복원할 수 없다 — 이 필드가 그
    # 순간을 스냅샷으로 고정한다. 재확인이 일어나지 않은 채점(소스만으로
    # 충분했거나 저장소 자체가 없는 제출)에는 빈 리스트로 남는다.
    repository_reachability_check = models.JSONField(default=list, blank=True)
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
    # 다시 시도해도 같은 결과가 나올 실패인가(#88 코드리뷰 지적 2,
    # scoring.adapters.LLMAdapterPermanentError). True면 scoring.services.
    # submission-scoring 스캔의 대상 조회가 이 Submission을 이후 스캔에서 뺀다 —
    # 안 그러면 매 스캔이 같은 결정적 실패를 영원히 반복하면서 Score 없이
    # 배분 컷라인에서 조용히 빠진다. 기본값 False는 기존 데이터(전부 재시도
    # 가능한 실패로 취급되던 시절)와 호환된다.
    permanent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "채점 실패 이력"
        verbose_name_plural = "채점 실패 이력"

    def __str__(self) -> str:  # pragma: no cover
        return f"ScoringAttempt(submission={self.submission_id}, at={self.attempted_at})"
