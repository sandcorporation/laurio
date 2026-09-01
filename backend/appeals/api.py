"""Appeal API (#21, ADR-0004, ADR-0006).

- `POST /submissions/{submission_id}/appeal` — Developer 본인이 자신의 Score에
  이의를 제기한다. Score가 아직 없으면(채점 전) 거부한다 — 이의는 판정이 이미
  나온 것에 대한 것이다.
- `GET /submissions/{submission_id}/appeal` — Developer 본인이 자신의 이의제기
  상태·심판 결과를 조회한다.
- `GET /submissions/{submission_id}/source-readings` — Developer 본인이 자기
  Submission 의 소스 열람 기록(언제·몇 번)을 조회한다(#61, ADR-0022). 누가 봤는지는
  주지 않는다 — 운영자 신원을 참가자에게 흘리지 않는다.
- `GET /operator/appeals`, `GET /operator/appeals/{appeal_id}`,
  `POST /operator/appeals/{appeal_id}/rule` — Operator 표면(#44, ADR-0019).
- `POST /operator/appeals/{appeal_id}/source` — Operator 가 채점에 쓰인 소스를
  펼친다. 그 요청 자체가 `SourceReading` 을 남긴다(#60, ADR-0022) — **소스 원문**
  을 기록 없이 얻는 경로는 없다.

  경계를 정확히 적어둔다: 이의 상세가 여전히 돌려주는 `reasoning` 은 LLM 이 쓴
  판정 근거이지 소스가 아니지만, 실물 어댑터는 근거를 쓰며 소스를 **인용**할 수
  있다. 그 인용까지 막으려면 근거를 가리거나 상세 조회 자체를 기록해야 하는데,
  둘 다 심판을 다르게 만드는 결정이라 여기서 몰래 정하지 않는다.

**예전에는 이 셋이 `/internal/appeals*` 에 있었다.** `InternalAuth` 는 공유 시크릿이
맞는지만 확인하고 그 키를 그대로 돌려준다 — 호출자 신원이라는 개념 자체가 없었다.
그래서 시크릿을 아는 사람이면 누구나 이의를 인용해 돈을 움직일 수 있었고, 나중에
"누가 그랬느냐"에 답할 수 없었다(#24). 사람이 판단하는 행위는 이제 신원과 함께만
이루어진다. `InternalAuth` 는 Celery beat 가 부르는 자동 스캔 전용으로 남는다.

**재채점을 하지 않는다** — 이 라우터도, `appeals.services`도 `scoring` 앱을
import하지 않는다.
"""

# `from __future__ import annotations` 를 쓰지 않는다 — 이 모듈에는 `@paginate` 로
# 감싼 엔드포인트가 있고(list_own_source_readings, #72), 그 래퍼는 원본 함수의
# `__globals__` 를 가져갈 수 없어 문자열이 된 어노테이션을 해석하지 못한다.
# contests/api.py 가 같은 자리에서 `QueryParams is not fully defined` 500 을
# 겪고 같은 결론에 도달했다(#39).

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from core.clock import Clock
from core.operator_auth import OperatorAuth
from submissions.models import Submission
from submissions.participation import within_appeal_window

from .models import Appeal, SourceReading
from .schemas import (
    AppealCreateIn,
    AppealDetailOut,
    AppealOut,
    AppealRulingIn,
    ErrorOut,
    RulingOut,
    ScoreSnapshotOut,
    SourceReadingOut,
    SourceRevealOut,
)
from .services import reject_appeal, uphold_appeal

router = Router(tags=["appeals"])
# 라우터 전체가 기본 거부다 — 엔드포인트마다 인증을 붙이면 다음에 추가되는 것이
# 조용히 열린 채로 태어난다.
operator_router = Router(tags=["operator", "appeals"], auth=OperatorAuth())


def _ruling_of(appeal: Appeal):
    # 심판이 아직 없으면 None — Appeal.status 가 PENDING 인 것과 같은 사실이다.
    return getattr(appeal, "ruling", None)


def _serialize(appeal: Appeal) -> AppealOut:
    ruling = _ruling_of(appeal)
    return AppealOut(
        id=appeal.id,
        submission_id=appeal.submission_id,
        reason=appeal.reason,
        status=appeal.status,
        ruling_note=ruling.note if ruling else "",
        correction_amount=ruling.correction_amount if ruling else None,
        ruled_at=ruling.ruled_at if ruling else None,
        created_at=appeal.created_at,
    )


def _get_owned_submission(request: HttpRequest, submission_id: int) -> Submission:
    try:
        submission = Submission.objects.select_related("developer", "contest").get(
            id=submission_id
        )
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "Submission을 찾을 수 없습니다.") from exc

    if submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인의 Submission에만 접근할 수 있습니다.")
    return submission


@router.post(
    "/submissions/{submission_id}/appeal",
    response={201: AppealOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def create_appeal(request: HttpRequest, submission_id: int, payload: AppealCreateIn):
    submission = _get_owned_submission(request, submission_id)

    if not hasattr(submission, "score"):
        raise HttpError(409, "아직 채점되지 않은 Submission은 이의제기할 수 없습니다.")

    if Appeal.objects.filter(submission=submission).exists():
        raise HttpError(409, "이미 이 Submission에 대한 이의제기가 접수되어 있습니다.")

    # 기한은 심사기간 종료다(#74). `submissions.participation` 의 판정을 그대로
    # 쓴다 — 「내 참가 현황」의 `next_action` 도 같은 함수에서 나온다. 조건을 두
    # 벌로 쓰면 언젠가 갈라지고, 그때 화면은 이의를 권해놓고 API 는 거절한다.
    #
    # **화면이 버튼을 감추는 것과 여기서 거절하는 것은 둘 다 필요하다** — 앞은
    # 사고 예방, 뒤는 방어다(#67 이 심판에 대해 세운 것과 같은 구분). 응답의
    # 필드는 아무것도 강제하지 못한다.
    if not within_appeal_window(submission.contest, Clock.now()):
        raise HttpError(
            409,
            "이의제기 기한(심사기간 종료)이 지나 더 이상 접수할 수 없습니다.",
        )

    appeal = Appeal.objects.create(submission=submission, reason=payload.reason)
    return 201, _serialize(appeal)


@router.get(
    "/submissions/{submission_id}/appeal",
    response={200: AppealOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_own_appeal(request: HttpRequest, submission_id: int):
    submission = _get_owned_submission(request, submission_id)

    try:
        appeal = Appeal.objects.get(submission=submission)
    except Appeal.DoesNotExist as exc:
        raise HttpError(404, "이 Submission에 대한 이의제기가 없습니다.") from exc

    return 200, _serialize(appeal)


@router.get(
    "/submissions/{submission_id}/source-readings",
    response=list[SourceReadingOut],
    auth=jwt_auth,
)
@paginate(PageNumberPagination, page_size=20)
def list_own_source_readings(request: HttpRequest, submission_id: int, **kwargs):
    """Developer 가 본인 Submission 의 소스 열람 기록을 본다 (#61, ADR-0022).

    ADR-0022 는 열람 기록을 만들라고만 한 것이 아니라 "기록에는 읽는 사람이 있어야
    한다"고 요구했다 — 이 엔드포인트가 그 요구를 채운다. 열람이 없으면 빈 목록으로
    200 이다: "아직 아무도 안 봤다"는 정상적인 사실이지 없는 리소스가 아니다.

    **운영자의 이름은 주지 않는다.** `SourceReadingOut` 에 `read_at` 뿐이다 — 시각과
    횟수만으로 "내 소스가 심판 과정에서 몇 번 열렸다"는 약속을 검증할 수 있다.

    **상한이 있다(#72).** 열람은 의도적으로 중복 제거도 레이트리밋도 없다(#60 —
    열람은 상태가 아니라 사건이라, 두 번 봤으면 두 줄이 남아야 한다). 그래서 행이
    무제한 쌓일 수 있는데 전부를 한 배열로 직렬화하면 응답에 상한이 코드 어디에도
    없게 된다 — 이 저장소는 상한 없는 필드가 4xx 가 나야 할 자리에서 500 을 내는
    것을 이미 겪었다. `contests` 목록과 같은 페이지네이션 관용구를 쓴다.

    소유권 검사는 페이지네이션보다 **먼저** 일어난다 — 남의 Submission 이면 빈
    페이지가 아니라 403 이다.
    """

    submission = _get_owned_submission(request, submission_id)
    return SourceReading.objects.filter(submission=submission).order_by("-read_at")


def _get_appeal_or_404(appeal_id: int) -> Appeal:
    try:
        return Appeal.objects.select_related(
            "submission__score", "submission__contest", "ruling__ruled_by"
        ).get(id=appeal_id)
    except Appeal.DoesNotExist as exc:
        raise HttpError(404, "이의제기를 찾을 수 없습니다.") from exc


def _serialize_ruling(ruling) -> RulingOut | None:
    if ruling is None:
        return None
    return RulingOut(
        decision=ruling.decision,
        ruled_by_id=ruling.ruled_by_id,
        ruled_by_username=ruling.ruled_by.username,
        note=ruling.note,
        ruled_at=ruling.ruled_at,
        correction_amount=ruling.correction_amount,
        correction_journal_entry_id=ruling.correction_journal_entry_id,
    )


def _serialize_detail(appeal: Appeal) -> AppealDetailOut:
    score = appeal.submission.score
    ruling = _ruling_of(appeal)
    return AppealDetailOut(
        id=appeal.id,
        submission_id=appeal.submission_id,
        reason=appeal.reason,
        status=appeal.status,
        ruling_note=ruling.note if ruling else "",
        correction_amount=ruling.correction_amount if ruling else None,
        ruled_at=ruling.ruled_at if ruling else None,
        created_at=appeal.created_at,
        score=ScoreSnapshotOut(
            percentage=str(score.percentage),
            model_version=score.model_version,
            reasoning=score.reasoning,
            created_at=score.created_at,
        ),
        ruling=_serialize_ruling(ruling),
    )


@operator_router.get("/appeals", response=list[AppealOut])
def list_appeals(request, status: str | None = None):
    """Operator 가 검토할 이의제기 목록. `status` 쿼리로 pending/upheld/rejected를
    거를 수 있다(기본은 전체).
    """

    qs = Appeal.objects.select_related("ruling")
    if status:
        qs = qs.filter(status=status)
    return [_serialize(a) for a in qs]


@operator_router.get(
    "/appeals/{appeal_id}", response={200: AppealDetailOut, 404: ErrorOut}
)
def get_appeal_detail(request, appeal_id: int):
    """운영자가 Score 스냅샷(점수·근거·모델버전)과 함께 이의를 조회한다 (#21 AC).

    프롬프트(=채점에 쓰인 제출 소스)는 여기 없다 — #59, ADR-0022. 소스를 보려면
    별도의 명시적 펼침 요청이 필요하다(#60)."""

    appeal = _get_appeal_or_404(appeal_id)
    return 200, _serialize_detail(appeal)


@operator_router.post(
    "/appeals/{appeal_id}/rule",
    response={200: AppealOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
)
def rule_appeal(request, appeal_id: int, payload: AppealRulingIn):
    """Operator 가 이의를 인용하거나 기각한다 — 그 신원이 함께 남는다(#44).

    이미 심판이 끝난 이의제기를 다시 심판하려 하면 409 — 정정 분개가 두 번 남는
    사고를 API 레벨에서도 막는다(`appeals.services`의 조건부 UPDATE가 최후의
    방어선이다).
    """

    appeal = _get_appeal_or_404(appeal_id)

    if appeal.status != Appeal.Status.PENDING:
        raise HttpError(409, "이미 심판이 끝난 이의제기입니다.")

    # 인용이든 기각이든 이유를 반드시 남긴다. 돈을 움직이는(또는 움직이지 않기로
    # 하는) 판단에 근거가 없으면 감사 기록으로서 값이 없다 — 이 티켓이 세우려는
    # 것이 정확히 그 기록이다.
    if not payload.ruling_note.strip():
        raise HttpError(422, "심판 이유(ruling_note)를 남겨야 합니다.")

    if payload.decision == "uphold":
        if not payload.correction_amount:
            raise HttpError(422, "인용하려면 correction_amount가 필요합니다.")
        appeal = uphold_appeal(
            appeal,
            ruled_by=request.auth,
            correction_amount=payload.correction_amount,
            ruling_note=payload.ruling_note,
        )
    elif payload.decision == "reject":
        appeal = reject_appeal(appeal, ruled_by=request.auth, ruling_note=payload.ruling_note)
    else:
        raise HttpError(422, "decision은 uphold 또는 reject 여야 합니다.")

    return 200, _serialize(appeal)


@operator_router.post(
    "/appeals/{appeal_id}/source",
    response={200: SourceRevealOut, 404: ErrorOut},
)
def reveal_appeal_source(request, appeal_id: int):
    """Operator 가 이의 심판을 위해 채점에 쓰인 소스를 펼친다 (#60, ADR-0022).

    **이 요청 자체가 `SourceReading` 을 남긴다.** 기록과 소스는 같은 요청에서
    나온다 — 둘을 갈라놓으면 한쪽만 부르는(기록 없이 소스만 얻는) 경로가 생긴다.

    **`POST` 인 이유.** 읽기 전용 메서드가 기록을 남기는 것은 그 메서드에 대한
    거짓말이고, `OperatorOriginMiddleware` 는 변경 메서드에만 걸린다 — `GET` 으로
    두면 이 표면만 CSRF 방어 밖에 남는다.

    **열람은 상태가 아니라 사건이다.** 같은 Operator 가 같은 이의에서 다시 펼치면
    행이 하나 더 쌓인다 — 중복 제거를 하지 않는다.
    """

    appeal = _get_appeal_or_404(appeal_id)
    score = appeal.submission.score

    SourceReading.objects.create(
        submission_id=appeal.submission_id,
        appeal=appeal,
        read_by=request.auth,
        read_at=Clock.now(),
    )

    return 200, SourceRevealOut(prompt=score.prompt)
