"""Classroom API (#278/#279/#280/#282/#283, ADR-0037).

**Class·Problem·체크리스트 엔드포인트는 여전히 강사 전용이다.** 참여자가
가입 링크로 들어와 문제를 실제로 보는 표면(진도·문제 열람)은 아직 없다 —
`ClassMember`가 이번 티켓(#280)으로 생겼지만, 강사가 아닌 요청은 여전히 그
클래스가 아예 없는 것처럼 404를 받는다. `Problem.status`(초안/열림)는 이미
저장되고 응답에 실려 있어, 참여자 열람이 붙을 때 필터 조건만 더하면 된다.

**`/join/{join_code}` 둘만 예외다.** 미리보기(GET)는 누구나 인증 없이 보고,
가입(POST)은 로그인만 되어 있으면 강사 전용 규칙과 무관하게 누구든(강사
본인 포함) 참여자가 된다 — 가입 링크가 하는 일 자체가 그 규칙 밖의 문이기
때문이다.

**라우트 등록 순서에 규칙이 있다.** 정적 세그먼트(`reorder`)를 가진 라우트는
전부 그 바로 위 동적 세그먼트(`{problem_id}`·`{item_id}`) 라우트보다 먼저
등록한다 — 나중이면 django-ninja가 정적 세그먼트를 동적 파라미터 값으로 먼저
매치해 405가 난다.
"""

from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from .models import ChecklistItem, Class, ClassMember, Problem, _generate_join_code
from .schemas import (
    ChecklistItemIn,
    ChecklistItemOut,
    ChecklistItemPatchIn,
    ChecklistReorderIn,
    ClassIn,
    ClassOut,
    ErrorOut,
    JoinIn,
    JoinLinkOut,
    JoinPreviewOut,
    JoinResultOut,
    ProblemIn,
    ProblemOut,
    ProblemPatchIn,
    ProblemReorderIn,
)

router = Router(tags=["classroom"])

_SUBMISSION_FORMATS = {choice for choice, _label in Problem.SubmissionFormat.choices}


def _serialize_class(class_obj: Class) -> ClassOut:
    return ClassOut(
        id=class_obj.id,
        name=class_obj.name,
        join_code=class_obj.join_code,
        created_at=class_obj.created_at,
    )


def _serialize_checklist_item(item: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(id=item.id, label=item.label, required=item.required, order=item.order)


def _serialize_problem(problem: Problem) -> ProblemOut:
    return ProblemOut(
        id=problem.id,
        classroom_id=problem.classroom_id,
        title=problem.title,
        description=problem.description,
        submission_format=problem.submission_format,
        status=problem.status,
        order=problem.order,
        checklist_items=[_serialize_checklist_item(i) for i in problem.checklist_items.all()],
    )


def _get_owned_class_or_404(class_id: int, user_id: int) -> Class:
    """강사 본인의 클래스만 돌려준다. 남의 것은 「없다」로 답한다 — 목록에도
    상세에도 나오지 않아야 한다는 AC(#278)를 403이 아니라 404로 지킨다."""

    try:
        return Class.objects.get(id=class_id, instructor_id=user_id)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "클래스를 찾을 수 없습니다.") from exc


def _get_owned_problem_or_404(classroom_obj: Class, problem_id: int) -> Problem:
    try:
        return classroom_obj.problems.get(id=problem_id)
    except Problem.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


# --- Class -------------------------------------------------------------------


@router.post("/classes", response={201: ClassOut}, auth=jwt_auth)
def create_class(request: HttpRequest, payload: ClassIn):
    class_obj = Class.objects.create(instructor_id=request.auth_user.id, name=payload.name)
    return 201, _serialize_class(class_obj)


@router.get("/classes", response={200: list[ClassOut]}, auth=jwt_auth)
def list_my_classes(request: HttpRequest):
    """「내 클래스」— 본인이 강사인 것만. 남의 클래스는 여기 나오지 않는다."""

    classes = Class.objects.filter(instructor_id=request.auth_user.id)
    return 200, [_serialize_class(c) for c in classes]


@router.get("/classes/{class_id}", response={200: ClassOut, 404: ErrorOut}, auth=jwt_auth)
def get_class(request: HttpRequest, class_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    return 200, _serialize_class(class_obj)


@router.post(
    "/classes/{class_id}/join-link/regenerate",
    response={200: JoinLinkOut, 404: ErrorOut},
    auth=jwt_auth,
)
def regenerate_join_link(request: HttpRequest, class_id: int):
    """가입 링크를 다시 뽑는다(#279). 새 코드로 덮어쓰므로 이전 코드는 그
    순간부터 어떤 클래스도 가리키지 않는다 — 링크가 새어 나갔을 때 강사가
    쓸 수 있는 유일한 조치다."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    class_obj.join_code = _generate_join_code()
    class_obj.save(update_fields=["join_code"])
    return 200, JoinLinkOut(join_code=class_obj.join_code)


# --- Join (#280) -----------------------------------------------------------------


def _get_class_by_join_code_or_404(join_code: str) -> Class:
    """코드가 없거나(오타) 재발급으로 죽었거나 — 이유를 구별하지 않는다.
    둘 다 "이 링크는 더 이상 쓸 수 없다"로 같게 답하는 것이 곧 #279가 정한
    재발급의 효과다."""

    try:
        return Class.objects.get(join_code=join_code)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "이 가입 링크는 더 이상 사용할 수 없습니다.") from exc


@router.get("/join/{join_code}", response={200: JoinPreviewOut, 404: ErrorOut}, auth=None)
def preview_join(request: HttpRequest, join_code: str):
    """가입 여부와 무관하게 누구나 본다 — 계정이 없는 사람이 가입할지 먼저
    판단할 수 있어야 한다(#280 AC)."""

    class_obj = _get_class_by_join_code_or_404(join_code)
    return 200, JoinPreviewOut(
        class_name=class_obj.name,
        instructor_email=class_obj.instructor.email,
        problem_count=class_obj.problems.count(),
        participant_count=class_obj.members.count(),
    )


@router.post(
    "/join/{join_code}", response={200: JoinResultOut, 404: ErrorOut, 422: ErrorOut}, auth=jwt_auth
)
def join_class(request: HttpRequest, join_code: str, payload: JoinIn):
    """가입과 클래스 가입이 한 흐름이다 — 계정이 있으면(로그인 되어 있으면)
    이 요청 하나로 끝난다. 이미 참여자면 새로 만들지 않고 그 행을 그대로
    돌려준다(#280 AC "같은 사람이 같은 클래스에 두 번 들어가지 않는다") —
    두 번째 이름은 버려진다, 첫 가입 때 정한 이름이 그 클래스에서의 정체성이기
    때문이다."""

    class_obj = _get_class_by_join_code_or_404(join_code)
    member, _created = ClassMember.objects.get_or_create(
        classroom=class_obj,
        user_id=request.auth_user.id,
        defaults={"display_name": payload.display_name},
    )
    return 200, JoinResultOut(
        class_id=class_obj.id, class_name=class_obj.name, display_name=member.display_name
    )


# --- Problem -------------------------------------------------------------------


@router.post(
    "/classes/{class_id}/problems",
    response={201: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def create_problem(request: HttpRequest, class_id: int, payload: ProblemIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)

    if payload.submission_format not in _SUBMISSION_FORMATS:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {payload.submission_format}")

    next_order = class_obj.problems.count()
    problem = Problem.objects.create(
        classroom=class_obj,
        title=payload.title,
        description=payload.description,
        submission_format=payload.submission_format,
        order=next_order,
    )
    return 201, _serialize_problem(problem)


@router.get(
    "/classes/{class_id}/problems", response={200: list[ProblemOut], 404: ErrorOut}, auth=jwt_auth
)
def list_problems(request: HttpRequest, class_id: int):
    """강사 본인의 클래스 문제 전부(초안 + 열림), 순서대로."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problems = class_obj.problems.prefetch_related("checklist_items").all()
    return 200, [_serialize_problem(p) for p in problems]


@router.post(
    "/classes/{class_id}/problems/reorder",
    response={200: list[ProblemOut], 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def reorder_problems(request: HttpRequest, class_id: int, payload: ProblemReorderIn):
    """정적 세그먼트("reorder")를 가진 라우트는 전부 `/{problem_id}` 동적
    라우트보다 **먼저** 등록해야 한다 — 나중이면 django-ninja가 "reorder"를
    `problem_id` 값으로 먼저 매치해, 이 라우트가 그 동적 라우트 중 하나(메서드가
    다른)에서 405로 막힌다. 이 파일의 라우트 등록 순서가 그래서 이렇다: 정적
    세그먼트 전부 → 동적 `{problem_id}` 전부."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problems = {p.id: p for p in class_obj.problems.all()}

    if set(payload.problem_ids) != set(problems):
        raise HttpError(422, "이 클래스의 문제 목록과 일치하지 않습니다.")

    with transaction.atomic():
        for index, problem_id in enumerate(payload.problem_ids):
            problem = problems[problem_id]
            problem.order = index
        Problem.objects.bulk_update(problems.values(), ["order"])

    ordered = sorted(problems.values(), key=lambda p: p.order)
    return 200, [_serialize_problem(p) for p in ordered]


@router.get(
    "/classes/{class_id}/problems/{problem_id}",
    response={200: ProblemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_problem(request: HttpRequest, class_id: int, problem_id: int):
    """문제 편집 화면이 초기값을 채우는 자리."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    return 200, _serialize_problem(problem)


@router.patch(
    "/classes/{class_id}/problems/{problem_id}",
    response={200: ProblemOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def update_problem(request: HttpRequest, class_id: int, problem_id: int, payload: ProblemPatchIn):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)

    if payload.submission_format is not None and payload.submission_format not in _SUBMISSION_FORMATS:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {payload.submission_format}")

    update_fields = []
    if payload.title is not None:
        problem.title = payload.title
        update_fields.append("title")
    if payload.description is not None:
        problem.description = payload.description
        update_fields.append("description")
    if payload.submission_format is not None:
        problem.submission_format = payload.submission_format
        update_fields.append("submission_format")
    if update_fields:
        problem.save(update_fields=[*update_fields, "updated_at"])
    return 200, _serialize_problem(problem)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/open",
    response={200: ProblemOut, 404: ErrorOut, 400: ErrorOut},
    auth=jwt_auth,
)
def open_problem(request: HttpRequest, class_id: int, problem_id: int):
    """초안을 연다. 필수 체크리스트 항목이 하나도 없으면 통과가 정의되지
    않아 막는다(#283 AC)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)

    if not problem.checklist_items.filter(required=True).exists():
        raise HttpError(400, "필수 항목이 하나도 없는 문제는 열 수 없습니다.")

    problem.status = Problem.Status.OPEN
    problem.save(update_fields=["status", "updated_at"])
    return 200, _serialize_problem(problem)


# --- ChecklistItem -------------------------------------------------------------


def _get_owned_checklist_item_or_404(problem: Problem, item_id: int) -> ChecklistItem:
    try:
        return problem.checklist_items.get(id=item_id)
    except ChecklistItem.DoesNotExist as exc:
        raise HttpError(404, "체크리스트 항목을 찾을 수 없습니다.") from exc


@router.post(
    "/classes/{class_id}/problems/{problem_id}/checklist-items",
    response={201: ChecklistItemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def create_checklist_item(
    request: HttpRequest, class_id: int, problem_id: int, payload: ChecklistItemIn
):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)

    next_order = problem.checklist_items.count()
    item = ChecklistItem.objects.create(
        problem=problem, label=payload.label, required=payload.required, order=next_order
    )
    return 201, _serialize_checklist_item(item)


@router.post(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/reorder",
    response={200: list[ChecklistItemOut], 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def reorder_checklist_items(
    request: HttpRequest, class_id: int, problem_id: int, payload: ChecklistReorderIn
):
    """정적 세그먼트("reorder")라 `{item_id}` 동적 라우트보다 먼저 등록한다
    (파일 상단 docstring 참고)."""

    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    items = {i.id: i for i in problem.checklist_items.all()}

    if set(payload.item_ids) != set(items):
        raise HttpError(422, "이 문제의 체크리스트 항목과 일치하지 않습니다.")

    with transaction.atomic():
        for index, item_id in enumerate(payload.item_ids):
            items[item_id].order = index
        ChecklistItem.objects.bulk_update(items.values(), ["order"])

    ordered = sorted(items.values(), key=lambda i: i.order)
    return 200, [_serialize_checklist_item(i) for i in ordered]


@router.patch(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={200: ChecklistItemOut, 404: ErrorOut},
    auth=jwt_auth,
)
def update_checklist_item(
    request: HttpRequest,
    class_id: int,
    problem_id: int,
    item_id: int,
    payload: ChecklistItemPatchIn,
):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)

    update_fields = []
    if payload.label is not None:
        item.label = payload.label
        update_fields.append("label")
    if payload.required is not None:
        item.required = payload.required
        update_fields.append("required")
    if update_fields:
        item.save(update_fields=update_fields)
    return 200, _serialize_checklist_item(item)


@router.delete(
    "/classes/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
    response={204: None, 404: ErrorOut},
    auth=jwt_auth,
)
def delete_checklist_item(request: HttpRequest, class_id: int, problem_id: int, item_id: int):
    class_obj = _get_owned_class_or_404(class_id, request.auth_user.id)
    problem = _get_owned_problem_or_404(class_obj, problem_id)
    item = _get_owned_checklist_item_or_404(problem, item_id)
    item.delete()
    return 204, None
