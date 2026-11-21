"""AI 채점 결과 (#12, ADR-0006, ADR-0014, #219/ADR-0030).

`Score`는 편의 기능이 아니라 Distribution 대상을 가르는 판정자다. LLM은 비결정적이라
같은 Submission을 두 번 채점하면 다른 점수가 나올 수 있으므로, 마감 직후 1회 채점한
결과를 점수·근거·프롬프트·모델 버전과 함께 불변 스냅샷으로 고정한다. `ledger.models`가
이미 검증한 `AppendOnlyModel`(원장의 append-only 규율, ADR-0004)을 그대로 재사용한다 —
"한 번 저장되면 다시 저장(수정)하거나 지울 수 없다"는 요구가 Score에도 글자 그대로
적용되기 때문이다. 재채점 코드 경로는 존재하지 않는다: `scoring.services`는 이미
Score가 있는 Submission을 항상 건드리지 않고 지나친다.

**`AppendOnlyModel`은 자기 자신의 `save`/`delete`와 QuerySet의 `update`/`delete`만
막는다(#240).** Django의 캐스케이드 삭제 collector는 그 어느 것도 거치지 않고 직접
DELETE 질의를 만든다 — `Contest.delete()` → (CASCADE) → `Submission` → (CASCADE) →
`Score`로 이어지면 이 스냅샷이 조용히 함께 사라진다(staging에서 실측: Contest 하나를
지우는 조회에 `scoring.Score: 3`이 삭제 대상으로 잡혔다). `Score.submission`을
`on_delete=PROTECT`로 바꿔 그 경로를 끊는다 — `distributions.DistributionShare.submission`
이 이미 같은 이유로 PROTECT다. Contest·Submission을 지우려는 시도는 `Score`가 하나라도
달려 있으면 `django.db.models.deletion.ProtectedError`로 실패하고, `Score`가 없는
Contest·Submission은 지금처럼 지워진다(PROTECT는 참조가 있을 때만 막는다).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from ledger.models import AppendOnlyError, AppendOnlyModel, AppendOnlyQuerySet


class Score(AppendOnlyModel):
    """Submission 하나에 대한 불변 채점 스냅샷. 마감 직후 정확히 한 번만 만들어진다."""

    submission = models.OneToOneField(
        "submissions.Submission", related_name="score", on_delete=models.PROTECT
    )
    # 필수 Requirement 달성률(0.00 ~ 100.00). Distribution(#16) 컷라인 판정의
    # 유일한 근거가 될 값이다(CONTEXT.md의 Score 정의) — 이 티켓은 그 소비처를
    # 만들지 않지만, 값의 의미는 이미 그렇게 고정한다.
    percentage = models.DecimalField(max_digits=5, decimal_places=2)
    # 실제 호출에 쓰인 LLM 모델 식별자(예: "fake-llm-v1", 실제 어댑터가 붙으면
    # "claude-sonnet-4-5-20250929" 같은 값). 나중에 어떤 모델이 이 판정을 내렸는지
    # 감사할 수 있어야 한다(ADR-0006).
    model_version = models.CharField(max_length=200)
    # LLM에 실제로 보낸 프롬프트 전문 — 소스 발췌·자가 응답을 포함한다(Evidence 는 #909 부터 싣지 않는다).
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


class ScoreCorrectionQuerySet(AppendOnlyQuerySet):
    pass


class ScoreCorrection(models.Model):
    """원래 `Score` 에 덧대는 정정 기록 하나(#1179, 스펙 #1178, ADR-0006 개정).

    `Score` 는 제출당 하나이고 append-only 라 플랫폼 오류로 틀린 점수를 바로잡을 길이 없었다.
    원래 행은 그대로 두고 이 행을 더한다 — 「현재 점수」는 끝난 정정 중 가장 나중 것, 없으면 원래
    `Score` 다(`scoring.current.current_score`). 판정 필드는 `Score` 와 모양이 같아 응답 스키마가 그대로 돈다.

    **한 번만 바뀐다.** 정정 채점은 시간이 걸리므로 「진행 중」으로 먼저 만들고, 채점이 끝나면 판정을
    채워 「끝」으로, 실패하면 「실패」로 한 번 넘긴다. 끝·실패가 된 행은 다시 저장할 수 없고, 어떤 행도
    지울 수 없다(대량 수정·삭제도 막는다). 정정 행 자체가 감사 기록이다 — 누가(`operator`)·언제·왜(`reason`)·
    무엇으로(`prompt`·`model_version`).
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "진행 중"
        DONE = "done", "끝"
        FAILED = "failed", "실패"

    score = models.ForeignKey(Score, related_name="corrections", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    # 판정 — `Score` 와 같은 필드. 「진행 중」·「실패」에는 비어 있다.
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    model_version = models.CharField(max_length=200, blank=True, default="")
    prompt = models.TextField(blank=True, default="")
    reasoning = models.JSONField(default=list, blank=True)
    scored_assets = models.JSONField(default=list, blank=True)
    repository_reachability_check = models.JSONField(default=list, blank=True)
    reason = models.TextField()
    # 「실패」로 넘긴 까닭(#1180) — 운영자가 다시 걸지 판단한다. 「진행 중」·「끝」에는 비어 있다.
    error = models.TextField(blank=True, default="", db_default="")
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="score_corrections", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = models.Manager.from_queryset(ScoreCorrectionQuerySet)()

    class Meta:
        verbose_name = "점수 정정"
        verbose_name_plural = "점수 정정"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status="done") | models.Q(percentage__isnull=False, finished_at__isnull=False),
                name="score_correction_done_has_verdict",
            ),
            models.CheckConstraint(condition=~models.Q(reason=""), name="score_correction_reason_required"),
            # 한 Score 에 진행 중 정정은 하나다(#1180) — 둘이 동시에 걸리면 어느 판정이 「현재」인지가 끝난 순서로 갈린다.
            models.UniqueConstraint(
                fields=["score"],
                condition=models.Q(status="in_progress"),
                name="score_correction_one_in_progress",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            stored = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored != self.Status.IN_PROGRESS:
                raise AppendOnlyError(
                    f"ScoreCorrection({self.pk}) 은 이미 {stored} 다 — 끝·실패가 된 정정은 다시 저장할 수 없다. "
                    "다시 바로잡으려면 새 정정을 더한다."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("ScoreCorrection 은 감사 기록이라 지울 수 없다.")

    def __str__(self) -> str:  # pragma: no cover
        return f"ScoreCorrection(score={self.score_id}, status={self.status}, percentage={self.percentage})"


def hard_delete_demo_seed_scores() -> int:
    """데모 시드가 심은 Contest 에 매달린 `Score` 만 append-only 가드를 우회해 지운다
    (#254, ADR-0064). 지운 행 수를 돌려준다.

    **왜 `hard_delete_e2e_fixture_rows`(#240) 를 쓰지 않는가** — 그 함수는 아무 queryset
    이나 받아 지우므로 데모 행과 실데이터 행을 구별할 수 없고, 그래서 배포 환경에서는 스스로
    거부한다. 그 거부를 풀면 #240 이 막은 문이 다시 열린다. 이 함수는 반대로 **queryset 을
    받지 않는다** — 삭제 범위는 여기서 `Contest.is_demo_seed`(그 표지를 쓰는 곳은
    `seed_demo_contests` 하나뿐이다) 로 고정되고, 호출부가 그 범위를 넓힐 길이 없다.
    표지가 없는 Score 는 제목·소유자가 무엇이든 이 함수의 집합에 들어오지 않는다.

    **dev 에서는 돈다, production 에서는 거부한다.** 데모 시드 자체가 production 을
    거부하므로(`seed_demo_contests.handle`) 이 함수가 production 에서 불릴 정상 경로는
    없지만, 호출부의 규율에 맡기지 않는다 — #240 과 ADR-0033 이 남긴 교훈이 「독스트링은
    뚫린다」였다. `hard_delete_e2e_fixture_rows` 와 같은 모양으로 함수 자신이 거부한다.

    `models.QuerySet.delete` 를 언바운드로 직접 호출해 `AppendOnlyQuerySet.delete` 의
    오버라이드를 건너뛰는 것은 #240 과 같다.
    """
    if settings.IS_PRODUCTION_DEPLOYMENT:
        raise AppendOnlyError(
            f"CODEMIT_DEPLOYMENT_TARGET={settings.CODEMIT_DEPLOYMENT_TARGET} 인데 "
            "hard_delete_demo_seed_scores 가 호출됐다 — 데모 시드는 production 에 심지 "
            "않으므로 지울 데모 Score 도 없다. append-only 실데이터를 지우려는 시도로 취급한다."
        )
    # 정정 행이 원래 Score 를 PROTECT 로 가리키므로 먼저 지운다(#1179) — 같은 표지로 범위를 고정한다.
    corrections = ScoreCorrection.objects.filter(score__submission__contestsubmission__contest__is_demo_seed=True)
    deleted_corrections, _ = models.QuerySet.delete(corrections)
    queryset = Score.objects.filter(submission__contestsubmission__contest__is_demo_seed=True)
    deleted, _ = models.QuerySet.delete(queryset)
    return deleted + deleted_corrections


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


class AgentRun(models.Model):
    """에이전트 실행 하나의 기록(#1000) — 받아들였든 보류했든 시도 원본을 남긴다.

    `record` 는 `core.agent_scoring.run_agent_job` 이 만든 원본이다: 시도마다 구조화 출력·usage·턴·
    도구 호출 수·근거 검사 결과·거절 사유, 그리고 지침 sha256·벤더·모델·박제본 커밋.
    `review` 는 받아들였지만 사람이 한 번 더 볼 것(필수 전부 충족·전부 미충족)이다 — 운영자 조회
    (`/api/internal/agent-runs`)가 보류와 함께 보여 준다.
    """

    class Outcome(models.TextChoices):
        ACCEPTED = "accepted", "받아들임"
        HELD = "held", "보류"

    submission = models.ForeignKey(
        "submissions.Submission", related_name="agent_runs", on_delete=models.CASCADE
    )
    purpose = models.CharField(max_length=20)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    model_version = models.CharField(max_length=200)
    reasons = models.JSONField(default=list, blank=True)
    review = models.CharField(max_length=200, blank=True, default="")
    record = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "에이전트 실행 기록"
        verbose_name_plural = "에이전트 실행 기록"

    def __str__(self) -> str:  # pragma: no cover
        return f"AgentRun(submission={self.submission_id}, {self.purpose}, {self.outcome})"


class SubmissionQualityReview(AppendOnlyModel):
    """공모전 제출 하나의 완성도 기록(#884, ADR-0072) — `Requirement` 마다 0~5 와 근거, 가중 점수, 완성도.

    `Score` 와 같은 append-only 스냅샷이고 **Score 와 무관하다**: 달성률·Distribution·Award 의 뜻과
    계산을 바꾸지 않고, 상금 배분에 쓰지 않는다. 마감 뒤 Score 가 생긴 제출(「입력 없음」·「채점 실패」
    자동 0% 제외)에 플랫폼 키로 **판마다 한 번** 매긴다 — 판은 현재 점수다(#1181): 원래 `Score` 판 하나, 점수
    정정(`ScoreCorrection`)이 끝나면 그 정정 판으로 하나 더. 화면은 가장 나중 판을 읽는다.

    **`on_delete=CASCADE` 다(Score 는 PROTECT).** 이 행은 Score 가 있는 제출에만 생기고, Score 의
    PROTECT 가 이미 그 제출·공모전의 삭제를 막는다. 그 막음을 넘는 길은 시드 정리
    (`hard_delete_demo_seed_scores`·`hard_delete_e2e_fixture_rows`)뿐이고, 그때 이 행도 함께 지워져야
    재시드가 돈다 — PROTECT 로 두면 두 정리 경로가 모두 이 모델을 따로 알아야 한다."""

    submission = models.ForeignKey(
        "submissions.Submission", related_name="contest_quality_reviews", on_delete=models.CASCADE
    )
    #: 판 — 이 리뷰가 읽은 현재 점수의 정정(#1181). None 이면 원래 `Score` 판이다. 판마다 하나다(아래 제약).
    #: 정정 행이 시드 정리로 지워지면 그 판의 리뷰도 함께 지운다.
    correction = models.ForeignKey(
        "scoring.ScoreCorrection", null=True, blank=True, related_name="quality_reviews", on_delete=models.CASCADE
    )
    #: 개최자 「완성도 순위」가 읽는 리뷰인가(#1181). 원래 판은 늘 참이다. 정정 판은 쓸 때 상금 배분이 끝났으면
    #: (`contests.ports.PRIZE_SETTLED`) 거짓이다 — 배분이 끝난 공모전의 순위는 고정한다(스펙 #1178).
    ranked = models.BooleanField(default=True, db_default=True)
    #: Requirement id·문구·필수 여부의 해시(`core.quality_review.checklist_fingerprint`).
    checklist_fingerprint = models.CharField(max_length=64)
    model_version = models.CharField(max_length=200)
    prompt = models.TextField()
    #: [{"item_id", "label"(Requirement 문구 스냅샷), "required", "score"(0~5), "reasoning"}, ...]
    items = models.JSONField()
    weighted_score = models.PositiveIntegerField()
    max_weighted_score = models.PositiveIntegerField()
    #: 0~100 — 화면은 소수 첫째 자리까지. 등수는 이 값이 아니라 `weighted_score` 로 매긴다.
    completeness = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "완성도"
        verbose_name_plural = "완성도"
        constraints = [
            # 판마다 하나 — 겹친 두 스캔의 삽입도 막는다(OneToOne 이던 때와 같은 일).
            models.UniqueConstraint(
                fields=["submission"],
                condition=models.Q(correction__isnull=True),
                name="scoring_quality_review_one_original",
            ),
            models.UniqueConstraint(
                fields=["submission", "correction"],
                condition=models.Q(correction__isnull=False),
                name="scoring_quality_review_one_per_correction",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"SubmissionQualityReview(submission={self.submission_id}, weighted={self.weighted_score})"


class SubmissionBonusScore(models.Model):
    """공모전 제출 하나 × 가산 Requirement 하나의 개최자 점수(#905, ADR-0073) — 0~5 와 한 줄 메모(선택).

    AI 는 가산을 판정하지도, 완성도 채점하지도 않는다. 개최자가 **마감 뒤**에만 매긴다
    (`contests.submission_api.rate_bonus`). Score·달성률·Distribution·Award 와 무관하고 완성도 합계에만 든다.
    고치기는 덮어쓰기다 — 이력은 남기지 않는다. 제출·Requirement 와 함께 지워진다(시드 정리 경로가 따로 알 필요가
    없게 `SubmissionQualityReview` 처럼 CASCADE)."""

    submission = models.ForeignKey("submissions.Submission", related_name="bonus_scores", on_delete=models.CASCADE)
    requirement = models.ForeignKey("contests.Requirement", related_name="bonus_scores", on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField()
    #: 한 줄 — 강의실 `ClassroomBonusScore` 와 같은 길이(200).
    memo = models.CharField(max_length=200, blank=True, default="")
    rated_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="+", null=True, on_delete=models.SET_NULL)
    rated_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submission", "requirement"], name="scoring_bonus_score_unique"),
            models.CheckConstraint(condition=models.Q(score__gte=0, score__lte=5), name="scoring_bonus_score_range"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"SubmissionBonusScore(submission={self.submission_id}, requirement={self.requirement_id})"


class QualityReviewAttempt(models.Model):
    """실패한 완성도 채점의 이력(#884) — `ScoringAttempt` 와 같은 운영 로그. 스캔은 영구 실패가
    하나라도 있거나 `QUALITY_FAILURE_LIMIT` 번 실패한 제출을 더 집지 않는다(`scoring.quality`)."""

    submission = models.ForeignKey(
        "submissions.Submission", related_name="quality_review_attempts", on_delete=models.CASCADE
    )
    #: 실패한 판(#1181) — 실패 상한·영구 실패는 판마다 센다. None 이면 원래 `Score` 판이다.
    correction = models.ForeignKey(
        "scoring.ScoreCorrection",
        null=True,
        blank=True,
        related_name="quality_review_attempts",
        on_delete=models.CASCADE,
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    error = models.TextField()
    permanent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "완성도 채점 실패 이력"
        verbose_name_plural = "완성도 채점 실패 이력"

    def __str__(self) -> str:  # pragma: no cover
        return f"QualityReviewAttempt(submission={self.submission_id}, at={self.attempted_at})"


class ScoringExperiment(models.Model):
    """채점 방식 비교 실험 하나(#1246, 스펙 #1244) — 공모전 하나의 채점된 제출에 줄(방식:모델)마다 회차만큼 돌린다.

    **운영 표에 닿지 않는다**: `Score`·`ScoreCorrection`·`AgentRun`·순위·지급을 쓰지 않고, 결과는
    `ScoringExperimentRun` 에만 남는다. 만드는 곳은 `manage.py compare_scoring_methods` 뿐이다.
    """

    name = models.CharField(max_length=120, unique=True)
    #: 공모전 재료면 그 공모전. 사본 재료(#1262)면 비고 `material` 이 찬다.
    contest = models.ForeignKey(
        "contests.Contest", related_name="scoring_experiments", on_delete=models.PROTECT, null=True, blank=True
    )
    #: 사본 재료의 이름(#1262, `core.experiment_material`) — 운영 강의실 제출을 가명으로 꺼낸 것. 칸은 가명 id 로 남는다.
    material = models.CharField(max_length=120, blank=True, default="", db_default="")
    material_exported_at = models.DateTimeField(null=True, blank=True)  # 사본을 가져온 때 — 7일 경고
    material_required_ids = models.JSONField(default=list, blank=True, null=True)  # 사본 재료의 필수 항목 id — 보고표의 필수 일치율
    created_by = models.CharField(max_length=150)
    rows = models.JSONField()  # ["agent:claude-sonnet-5-5", ...] — 첫째가 기준 줄
    repeat = models.PositiveSmallIntegerField()
    limit_submissions = models.PositiveIntegerField(null=True, blank=True)
    #: `limit_submissions` 건을 고르는 법(#1259) — "id"(id 순 앞 N 건) 또는 "spread"(운영 점수 분위로 N 건). 이 값이 있기
    #: 전에 만든 실험은 "id" 다 — 이어 돌려도 고른 집합이 바뀌지 않는다.
    pick = models.CharField(max_length=10, default="id", db_default="id")
    #: 비용만 재는 실험(#1261) — 뽑힌 재료의 기대 점수가 모두 같아 방식을 가를 수 없는데 `--cost-only` 로 돌렸다.
    #: 보고표 머리가 「비용 측정 전용 — 점수 비교 아님」이라고 말한다.
    cost_only = models.BooleanField(default=False, db_default=False)
    daily_limit_usd = models.DecimalField(max_digits=10, decimal_places=4)  # 만들 때의 실험 하루 상한
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "채점 방식 비교 실험"
        verbose_name_plural = "채점 방식 비교 실험"

    def __str__(self) -> str:  # pragma: no cover
        return f"ScoringExperiment({self.name})"


class ScoringExperimentRun(models.Model):
    """실험의 칸 하나 = (제출, 줄, 회차) 한 번 돌린 결과(#1246). 같은 칸은 한 번만 — 상한에 멈췄다가 다시 돌리면
    남은 칸만 돈다."""

    class Status(models.TextChoices):
        SCORED = "scored", "채점"
        HELD = "held", "보류"
        FAILED = "failed", "실패"

    experiment = models.ForeignKey(ScoringExperiment, related_name="runs", on_delete=models.CASCADE)
    submission = models.ForeignKey(
        "contests.ContestSubmission", related_name="scoring_experiment_runs", on_delete=models.CASCADE,
        null=True, blank=True,
    )
    #: 사본 재료의 가명 id(#1262) — 운영 제출과 잇는 칸이 없다. 공모전 재료면 빈 글.
    material_id = models.CharField(max_length=16, blank=True, default="", db_default="")
    row = models.CharField(max_length=120)
    round = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    verdicts = models.JSONField(default=list, blank=True)  # [{requirement_id, met, evidence, reason}]
    evidence_offered = models.PositiveIntegerField(default=0)  # 모델이 낸 근거 수(루프가 버린 것 포함)
    evidence_real = models.PositiveIntegerField(default=0)  # 그중 박제본에 실재한 수
    evidence_all_real = models.BooleanField(default=False)
    problem = models.TextField(blank=True, default="")  # 보류·실패 까닭
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    model_version = models.CharField(max_length=200, blank=True, default="")
    record = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField()  # `Clock.now()` — 실험 하루 상한이 실행 토큰과 같은 시계로 센다

    @property
    def subject_key(self) -> int:
        """칸의 제출을 정수로 — 공모전 제출 번호, 사본 재료면 가명의 정수 꼴(`core.experiment_material.Item.key`)."""

        return self.submission_id if self.submission_id is not None else int(self.material_id, 16)

    class Meta:
        ordering = ["experiment_id", "submission_id", "row", "round"]
        constraints = [
            models.UniqueConstraint(fields=["experiment", "submission", "row", "round"], name="scoring_experiment_cell"),
            models.UniqueConstraint(
                fields=["experiment", "material_id", "row", "round"],
                condition=models.Q(submission__isnull=True),
                name="scoring_experiment_material_cell",
            ),
        ]
        verbose_name = "채점 방식 비교 실험 회차"
        verbose_name_plural = "채점 방식 비교 실험 회차"

    def __str__(self) -> str:  # pragma: no cover
        return f"ScoringExperimentRun({self.experiment_id}, {self.submission_id}, {self.row}, {self.round})"
