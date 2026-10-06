"""채점 대기 판정을 한 곳에서 (#434, spec #432).

시도 하나가 지금 채점될 수 있는지, 아니라면 그 사유가 무엇인지를 이 모듈
하나가 답한다 — 스캔 후보 질의(`classroom.scoring`), 채점 직전 확인(같은
모듈), 참여자·강사 화면의 `pending_reason`, 강사 참여자별 격자의 칸 상태가
모두 이 답을 쓴다. 네 곳이 각자 판단하다 어긋난 것(모델이 거부된 시도가
격자에서만 "채점 중"으로 보이던 것)이 이 티켓의 출발점이다.

사유는 셋이고, 겹치면 이 순서로 하나만 돌려준다: 키(없음·거부) → 모델 거부
→ 예산 소진. `Class.scoring_key_unusable()`·`Problem.scoring_model_rejected_at`
·`Class.token_budget_exhausted()`가 각 사유의 실제 판정 기준이다 — 이 모듈은
그 셋을 한 순서로 세울 뿐 새 판단을 만들지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.db.models import Count, QuerySet

from .models import Class, ClassroomScoringAttempt, ClassroomSubmission, Problem

#: 참여자·강사 화면의 `pending_reason` 값(#346, #295, #403) — 순서가 곧
#: 우선순위다.
NO_API_KEY = "no_api_key"
MODEL_REJECTED = "model_rejected"
BUDGET_EXHAUSTED = "budget_exhausted"


def blocking_reason(class_obj: Class, problem: Problem, *, ignore_pause: bool = False) -> str | None:
    """이 클래스·이 문제의 시도가 지금 채점될 수 없는 이유(있으면 하나만).

    이미 `ClassroomScore`가 있는지는 이 함수의 책임이 아니다 — 부르는 쪽이
    먼저 본다(스캔 후보 쿼리는 `classroom_score__isnull=True`로 이미 걸러
    부르고, `pending_reason`은 `score is not None`이면 이 함수를 부르지도
    않는다).

    `ignore_pause`는 채점 태스크가 멈춘 클래스(크레딧 소진·서버 연결 불가)를 다시 쳐 볼 차례를
    잡았을 때만 참이다(`classroom.scoring._claim_pause_recheck`, #586, #603) — 화면은 언제나
    거짓으로 본다."""

    if class_obj.scoring_key_unusable(ignore_pause=ignore_pause):
        return NO_API_KEY
    if problem.scoring_model_rejected_at is not None:
        return MODEL_REJECTED
    if class_obj.token_budget_exhausted():
        return BUDGET_EXHAUSTED
    return None


def can_be_scored(class_obj: Class, problem: Problem) -> bool:
    """지금 이 시도가 채점 후보인가 — `blocking_reason`이 아무것도 없을 때."""

    return blocking_reason(class_obj, problem) is None


def pending_reason(score, class_obj: Class, problem: Problem) -> str | None:
    """참여자용 `.../mine`·강사용 제출 현황이 읽는 값(#346, #295, #403) — 이미
    채점됐으면(`score`가 있으면) 언제나 `None`이다."""

    if score is not None:
        return None
    return blocking_reason(class_obj, problem)


def needs_setup(class_obj: Class, problem: Problem) -> bool:
    """강사 참여자별 격자의 칸이 「설정 필요」로 보여야 하는가(#290, #434) — 키
    문제와 모델 거부를 합친다. 예산 소진은 포함하지 않는다: 예산을 채우면
    강사가 따로 손대지 않아도 저절로 풀리는 "채점 중"이라, 강사가 지금
    당장 무언가 해야 하는 나머지 둘과 다르다."""

    return class_obj.scoring_key_unusable() or problem.scoring_model_rejected_at is not None


#: 크레딧이 바닥난 클래스를 다시 쳐 보는 간격(#586) — `classroom.scoring`이 같은 값을
#: 쓴다(후보 질의가 이 모듈에 있어 여기 둔다).
QUOTA_RECHECK_INTERVAL = timedelta(minutes=10)


def pending_submissions(as_of, ctx) -> QuerySet[ClassroomSubmission]:
    """아직 `ClassroomScore`가 없고 `blocking_reason`이 없는(=지금 채점될 수
    있는) 시도(#287, #295, #355, #403). `classroom.scoring`의 스캔이 이
    쿼리를 그대로 쓴다 — 후보 조건과 화면의 판정 기준(`blocking_reason`)이
    같은 자리에 있어야 둘이 어긋나지 않는다.

    키 없는 클래스·키가 거부된 클래스·모델이 거부된 문제·예산이 바닥난
    클래스의 시도는 애초에 후보가 아니다 — "아직 시도하지 않았다"를
    `ClassroomScoringAttempt` 이력 없이 유지한다(`classroom.scoring` 모듈
    docstring). 강사가 새 키를 저장하면(#354의 검증 결과로 상태가 덮인다)
    또는 그 문제의 모델을 바꾸면(`classroom.api`가 `scoring_model_rejected_at`
    을 지운다) 다음 tick부터 저절로 후보에 다시 들어온다 — 예산이 다시
    찼을 때와 같은 원리로, 별도의 "재개" 신호가 필요 없다. 시도 횟수
    오름차순으로 정렬한다(한 번도 시도되지 않은 것이 재시도 중인 것보다
    항상 앞선다, ADR-0031) — 예산이 차서 쌓인 시도부터 다시 도는 것도 이
    정렬 하나로 이미 "쌓인 순서대로"가 된다.

    크레딧이 바닥났거나 호환 서버에 닿지 않는 클래스(#586, #603)는 마지막 확인에서
    `QUOTA_RECHECK_INTERVAL`이 지나기 전까지만 뺀다 — 지나면 후보에 들어 그중 하나가 다시 쳐
    본다(`classroom.scoring.score_classroom_attempt`). 화면의 대기 사유는 그 사이에도 「키」다(`blocking_reason`).
    `attempt_count`는 빈도 제한으로 세지 않은 시도를 빼고 센다 — 실패 한도와 같은 기준이다.
    """

    attempt_count = (
        ClassroomScoringAttempt.objects.filter(submission=models.OuterRef("pk"), rate_limited=False)
        .order_by()
        .values("submission")
        .annotate(count=Count("id"))
        .values("count")
    )

    return (
        ClassroomSubmission.objects.filter(
            classroom_score__isnull=True,
        )
        # 채점 연결이 없는 클래스 — `Class.has_scoring_key` 와 같은 기준(호환 서버는 주소로, #601).
        .exclude(
            models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.COMPATIBLE_SERVER)
            & models.Q(problem__classroom__scoring_server_url="")
        )
        .exclude(
            ~models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.COMPATIBLE_SERVER)
            & models.Q(problem__classroom__openai_api_key_encrypted="")
        )
        .exclude(problem__classroom__openai_api_key_status=Class.ScoringKeyStatus.REJECTED)
        .exclude(problem__scoring_model_rejected_at__isnull=False)
        .exclude(problem__classroom__scoring_quota_exhausted_at__gt=as_of - QUOTA_RECHECK_INTERVAL)
        .exclude(problem__classroom__scoring_server_unreachable_at__gt=as_of - QUOTA_RECHECK_INTERVAL)
        .exclude(
            models.Q(problem__classroom__token_budget__isnull=False)
            & models.Q(
                problem__classroom__token_usage_total__gte=models.F(
                    "problem__classroom__token_budget"
                )
            )
        )
        .annotate(attempt_count=models.functions.Coalesce(models.Subquery(attempt_count), 0))
        .select_related("problem", "problem__classroom", "member")
    )
