"""채점 대기 판정을 한 곳에서 (#434, spec #432).

시도 하나가 지금 채점될 수 있는지, 아니라면 그 사유가 무엇인지를 이 모듈
하나가 답한다 — 스캔 후보 질의(`classroom.scoring`), 채점 직전 확인(같은
모듈), 참여자·강사 화면의 `pending_reason`, 강사 참여자별 격자의 칸 상태가
모두 이 답을 쓴다. 네 곳이 각자 판단하다 어긋난 것(모델이 거부된 시도가
격자에서만 "채점 중"으로 보이던 것)이 이 티켓의 출발점이다.

사유는 둘이고, 겹치면 이 순서로 하나만 돌려준다: 키(없음·거부) → 모델 거부.
`Class.scoring_key_unusable()`·`Problem.scoring_model_rejected_at`가 각 사유의
실제 판정 기준이다 — 이 모듈은 그 둘을 한 순서로 세울 뿐 새 판단을 만들지 않는다.
예전의 셋째 사유(누적 토큰 상한, #295)는 걷어냈다(#629, ADR-0060) — 누적 사용량은
채점을 멈추지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.db.models import Count, QuerySet

from .models import Class, ClassroomScoringAttempt, ClassroomSubmission, Problem

#: 참여자·강사 화면의 `pending_reason` 값(#346, #403) — 순서가 곧 우선순위다.
NO_API_KEY = "no_api_key"

#: 에이전트 채점 보류 표식(#1036) — 공모전(`scoring.services.AGENT_SCORING_HOLD_ERROR_PREFIX`)과 같은 값. 이 머리를
#: 단 시도 기록(`ClassroomScoringAttempt.error`)이 있는 시도는 채점 대기에서 빠지고, 그 기록은 실패 상한에
#: 세지 않는다 — 받아들이는 조건이 두 번 다 어긋났다는 것이지 제출물이 실패한 것이 아니다. 0% 로 굳히지 않는다.
AGENT_SCORING_HOLD_ERROR_PREFIX = "AgentScoringHold:"

#: 반려 표식(#1311, CONTEXT.md 「반려」) — 클래스가 「반려」를 고른 채 소스가 한 번 호출에 다 들어가지 않았다. 모델을
#: 부르지 않았고 점수도 없다. 그 시도는 다시 집지 않고(학생이 새로 낸다) 실패 상한·시도 횟수에 세지 않는다. 기록은
#: `rejection_error` 꼴(머리 뒤에 그때 잰 소스 글자 수와 한도)이다. 예전의 「크기 초과」 보류(#989)를 대신한다.
REJECTED_ERROR_PREFIX = "SourceOverBudgetRejected:"

#: 실패 상한·시도 횟수에 세지 않는 표식.
HOLD_PREFIXES = (AGENT_SCORING_HOLD_ERROR_PREFIX, REJECTED_ERROR_PREFIX)


def rejection_error(*, source_chars: int, limit_chars: int) -> str:
    """반려 기록의 `error` — 화면이 `parse_rejection` 으로 사유 한 줄을 다시 짓는다."""

    return f"{REJECTED_ERROR_PREFIX} source_chars={source_chars} limit_chars={limit_chars}"


def parse_rejection(error: str | None) -> tuple[int, int] | None:
    """반려 기록에서 (소스 글자 수, 한도 글자 수) — 반려 기록이 아니거나 읽을 수 없으면 `None`."""

    if not error or not error.startswith(REJECTED_ERROR_PREFIX):
        return None
    fields = dict(part.split("=", 1) for part in error[len(REJECTED_ERROR_PREFIX) :].split() if "=" in part)
    try:
        return int(fields["source_chars"]), int(fields["limit_chars"])
    except (KeyError, ValueError):
        return None


def exclude_holds(queryset: QuerySet) -> QuerySet:
    """`error` 가 보류·반려 표식으로 시작하는 시도 기록을 뺀다 — 실패 상한·시도 횟수가 쓴다."""

    for prefix in HOLD_PREFIXES:
        queryset = queryset.exclude(error__startswith=prefix)
    return queryset
MODEL_REJECTED = "model_rejected"
#: 이 시도가 반려됐다(#1311) — 시도마다다(위 둘은 클래스·문제 단위). 채점 대기가 아니라 끝난 시도다.
REJECTED = "rejected"
REASONS = (NO_API_KEY, MODEL_REJECTED, REJECTED)


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
    return None


def can_be_scored(class_obj: Class, problem: Problem) -> bool:
    """지금 이 시도가 채점 후보인가 — `blocking_reason`이 아무것도 없을 때."""

    return blocking_reason(class_obj, problem) is None


def pending_reason(score, class_obj: Class, problem: Problem, *, rejected: bool = False) -> str | None:
    """참여자용 `.../mine`·강사용 제출 현황이 읽는 값(#346, #403) — 이미
    채점됐으면(`score`가 있으면) 언제나 `None`이다. `rejected` 는 그 시도가 반려됐는가(`with_rejection` 이 단
    `rejection_error`, #1311) — 반려는 끝난 일이라 키·모델 사유보다 먼저다."""

    if score is not None:
        return None
    if rejected:
        return REJECTED
    return blocking_reason(class_obj, problem)


def _rejected_attempts() -> QuerySet[ClassroomScoringAttempt]:
    return ClassroomScoringAttempt.objects.filter(
        submission=models.OuterRef("pk"), error__startswith=REJECTED_ERROR_PREFIX
    )


def with_rejection(queryset: QuerySet[ClassroomSubmission]) -> QuerySet[ClassroomSubmission]:
    """시도마다 `rejection_error`(반려 기록의 `error`, 없으면 `None`)를 단다(#1311). 스캔 후보(`pending_submissions`)와
    화면(`pending_reason`·사유 한 줄)이 같은 식을 쓴다."""

    return queryset.annotate(rejection_error=models.Subquery(_rejected_attempts().values("error")[:1]))


def needs_setup(class_obj: Class, problem: Problem) -> bool:
    """강사 참여자별 격자의 칸이 「설정 필요」로 보여야 하는가(#290, #434) — 키
    문제와 모델 거부를 합친다 — 지금은 대기 사유가 그 둘뿐이라 `blocking_reason`이 있는가와
    같다(#629)."""

    return class_obj.scoring_key_unusable() or problem.scoring_model_rejected_at is not None


#: 크레딧이 바닥난 클래스를 다시 쳐 보는 간격(#586) — `classroom.scoring`이 같은 값을
#: 쓴다(후보 질의가 이 모듈에 있어 여기 둔다).
QUOTA_RECHECK_INTERVAL = timedelta(minutes=10)


def pending_submissions(as_of, ctx) -> QuerySet[ClassroomSubmission]:
    """아직 `ClassroomScore`가 없고 `blocking_reason`이 없는(=지금 채점될 수
    있는) 시도(#287, #355, #403). `classroom.scoring`의 스캔이 이
    쿼리를 그대로 쓴다 — 후보 조건과 화면의 판정 기준(`blocking_reason`)이
    같은 자리에 있어야 둘이 어긋나지 않는다.

    키 없는 클래스·키가 거부된 클래스·모델이 거부된 문제의 시도는 애초에 후보가 아니다 — "아직 시도하지 않았다"를
    `ClassroomScoringAttempt` 이력 없이 유지한다(`classroom.scoring` 모듈
    docstring). 강사가 새 키를 저장하면(#354의 검증 결과로 상태가 덮인다)
    또는 그 문제의 모델을 바꾸면(`classroom.api`가 `scoring_model_rejected_at`
    을 지운다) 다음 tick부터 저절로 후보에 다시 들어온다 — 별도의 "재개" 신호가
    필요 없다. 시도 횟수 오름차순으로 정렬한다(한 번도 시도되지 않은 것이
    재시도 중인 것보다 항상 앞선다, ADR-0031) — 멈췄다 풀린 클래스의 쌓인
    시도부터 다시 도는 것도 이 정렬 하나로 이미 "쌓인 순서대로"가 된다.

    크레딧이 바닥났거나 호환 서버에 닿지 않는 클래스(#586, #603)는 마지막 확인에서
    `QUOTA_RECHECK_INTERVAL`이 지나기 전까지만 뺀다 — 지나면 후보에 들어 그중 하나가 다시 쳐
    본다(`classroom.scoring.score_classroom_attempt`). 화면의 대기 사유는 그 사이에도 「키」다(`blocking_reason`).
    `attempt_count`는 빈도 제한으로 세지 않은 시도를 빼고 센다 — 실패 한도와 같은 기준이다.
    """

    attempt_count = (
        exclude_holds(ClassroomScoringAttempt.objects.filter(submission=models.OuterRef("pk"), rate_limited=False))
        .order_by()
        .values("submission")
        .annotate(count=Count("id"))
        .values("count")
    )

    return (
        ClassroomSubmission.objects.filter(classroom_score__isnull=True)
        # 반려(#1311) — 다시 돌리지 않는다. 학생이 새로 낸 시도가 채점된다.
        .exclude(models.Exists(_rejected_attempts()))
        # 채점 연결이 없는 클래스 — `Class.has_scoring_key` 와 같은 기준(호환 서버는 주소로, #601).
        .exclude(
            models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.COMPATIBLE_SERVER)
            & models.Q(problem__classroom__scoring_server_url="")
        )
        # 키 연결은 스위치가 고른 쪽 키 칸으로 가른다(#1269) — Claude 키 연결은 Claude 칸, 나머지는 OpenAI 칸.
        .exclude(
            models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.OPENAI_KEY)
            & models.Q(problem__classroom__openai_api_key_encrypted="")
        )
        .exclude(
            models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY)
            & models.Q(problem__classroom__anthropic_api_key_encrypted="")
        )
        .exclude(
            ~models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY)
            & models.Q(problem__classroom__openai_api_key_status=Class.ScoringKeyStatus.REJECTED)
        )
        .exclude(
            models.Q(problem__classroom__scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY)
            & models.Q(problem__classroom__anthropic_api_key_status=Class.ScoringKeyStatus.REJECTED)
        )
        .exclude(problem__scoring_model_rejected_at__isnull=False)
        .exclude(problem__classroom__scoring_quota_exhausted_at__gt=as_of - QUOTA_RECHECK_INTERVAL)
        .exclude(problem__classroom__scoring_server_unreachable_at__gt=as_of - QUOTA_RECHECK_INTERVAL)
        # 에이전트 채점 보류(#1036) — 다시 돌려 예산을 쓰지 않는다. 공모전 보류와 같다.
        .exclude(
            models.Exists(
                ClassroomScoringAttempt.objects.filter(
                    submission=models.OuterRef("pk"), error__startswith=AGENT_SCORING_HOLD_ERROR_PREFIX
                )
            )
        )
        .annotate(attempt_count=models.functions.Coalesce(models.Subquery(attempt_count), 0))
        .select_related("problem", "problem__classroom", "member")
    )
