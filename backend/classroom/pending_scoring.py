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
from django.db.models.functions import Concat

from .models import Class, ClassroomScoringAttempt, ClassroomSubmission, Problem

#: 참여자·강사 화면의 `pending_reason` 값(#346, #403) — 순서가 곧 우선순위다.
NO_API_KEY = "no_api_key"

#: 에이전트 채점 보류 표식(#1036) — 공모전(`scoring.services.AGENT_SCORING_HOLD_ERROR_PREFIX`)과 같은 값. 이 머리를
#: 단 시도 기록(`ClassroomScoringAttempt.error`)이 있는 시도는 채점 대기에서 빠지고, 그 기록은 실패 상한에
#: 세지 않는다 — 받아들이는 조건이 두 번 다 어긋났다는 것이지 제출물이 실패한 것이 아니다. 0% 로 굳히지 않는다.
AGENT_SCORING_HOLD_ERROR_PREFIX = "AgentScoringHold:"

#: 「크기 초과」 보류 표식(#989) — 공모전(`scoring.services.SCORING_HOLD_ERROR_PREFIX`)과 같은 값. 채점 요청이 그 모델
#: 컨텍스트에 들어가지 않았다. 기록은 `size_hold_error` 꼴(머리 뒤에 ` model=<모델> `)이라, 그 시도는 **같은 모델**인
#: 동안만 채점 대기에서 빠진다 — 강사가 문제·클래스 모델을 바꾸면 다음 스캔이 다시 집는다. 실패 상한에 세지 않는다.
SIZE_HOLD_ERROR_PREFIX = "SourceOverBudgetHold:"

#: 실패 상한·시도 횟수에 세지 않는 보류 표식.
HOLD_PREFIXES = (AGENT_SCORING_HOLD_ERROR_PREFIX, SIZE_HOLD_ERROR_PREFIX)


def size_hold_error(model: str, detail: str) -> str:
    """「크기 초과」 보류 기록의 `error` — 머리와 모델을 앞에 둔다(`pending_submissions` 가 머리로 거른다)."""

    return f"{SIZE_HOLD_ERROR_PREFIX} model={model} {detail}"


def exclude_holds(queryset: QuerySet) -> QuerySet:
    """`error` 가 보류 표식으로 시작하는 시도 기록을 뺀다 — 실패 상한·시도 횟수가 쓴다."""

    for prefix in HOLD_PREFIXES:
        queryset = queryset.exclude(error__startswith=prefix)
    return queryset
MODEL_REJECTED = "model_rejected"
#: 이 시도의 채점 요청이 지금 채점 모델의 컨텍스트를 넘어 보류됐다(#989) — 시도마다 다르다(위 둘은 클래스·문제 단위).
SIZE_HELD = "size_held"
REASONS = (NO_API_KEY, MODEL_REJECTED, SIZE_HELD)


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


def pending_reason(score, class_obj: Class, problem: Problem, *, size_held: bool = False) -> str | None:
    """참여자용 `.../mine`·강사용 제출 현황이 읽는 값(#346, #403) — 이미
    채점됐으면(`score`가 있으면) 언제나 `None`이다. `size_held` 는 그 시도가 「크기 초과」로 보류됐는가
    (`with_size_held` 가 단 값, #989) — 키·모델 사유가 먼저다."""

    if score is not None:
        return None
    return blocking_reason(class_obj, problem) or (SIZE_HELD if size_held else None)


def _size_held_exists() -> models.Exists:
    """바깥 행(`ClassroomSubmission`, `held_scoring_model` 을 단)에 지금 채점 모델의 「크기 초과」 보류 기록이 있는가."""

    return models.Exists(
        ClassroomScoringAttempt.objects.filter(
            submission=models.OuterRef("pk"),
            error__startswith=Concat(
                models.Value(f"{SIZE_HOLD_ERROR_PREFIX} model="),
                models.OuterRef("held_scoring_model"),
                models.Value(" "),
                output_field=models.TextField(),
            ),
        )
    )


def with_size_held(queryset: QuerySet[ClassroomSubmission]) -> QuerySet[ClassroomSubmission]:
    """시도마다 `size_held`(지금 채점 모델 — 문제 모델, 비면 클래스 기본 모델 — 로 「크기 초과」 보류됐는가)를
    단다(#989). 스캔 후보(`pending_submissions`)와 화면(`pending_reason`)이 같은 식을 쓴다."""

    return queryset.annotate(
        held_scoring_model=models.Case(
            models.When(problem__model="", then=models.F("problem__classroom__default_model")),
            default=models.F("problem__model"),
        )
    ).annotate(size_held=_size_held_exists())


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
        with_size_held(ClassroomSubmission.objects.filter(classroom_score__isnull=True))
        # 「크기 초과」 보류(#989) — 그 모델이 지금도 이 문제의 채점 모델이면 다시 돌리지 않는다.
        .exclude(size_held=True)
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
