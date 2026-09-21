"""문제 템플릿 API (#316/#318/#320, #312).

**공개 시점의 사본을 만든다.** `Problem`·`Class`를 가리키지 않으므로 원본을
고치거나 지워도 템플릿은 그대로다(`services.publish_problem_as_template`
docstring). 채점 모델은 애초에 템플릿에 필드가 없다.

**로그인한 사람만 닿는다.** 강의실 앱은 로그인한 사람만 보는 것을 전제로
지어져 있다(#312 Implementation Decisions) — `/join/{join_code}`의 GET과
달리 미리보기도 `auth=jwt_auth`다.

**라우트 등록 순서 규칙은 이 파일에도 적용된다**(`classroom/api.py` 상단
docstring과 같은 이유) — `/problem-templates/mine`처럼 정적 세그먼트를 가진
라우트는 `/problem-templates/{share_code}` 동적 라우트보다 먼저 등록한다.
"""

from __future__ import annotations

from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth

from .api import _reject_if_banned_name, _serialize_class, _serialize_problem
from .instructor_scope import class_scope, problem_scope
from .models import ClassTemplate, ProblemTemplate, ProblemTemplateReport
from .schemas import (
    ClassOut,
    ClassTemplateListItemOut,
    ClassTemplateOut,
    ClassTemplateProblemOut,
    ErrorOut,
    ImportClassTemplateIn,
    ImportTemplateIn,
    ProblemOut,
    ProblemTemplateChecklistItemOut,
    ProblemTemplateListItemOut,
    ProblemTemplateOut,
    PublishTemplateIn,
    ReportResultOut,
    ReportTemplateIn,
)
from .services import (
    import_class_template,
    import_problem_template,
    publish_class_as_template,
    publish_problem_as_template,
)

router = Router(tags=["classroom", "templates"])


def _serialize_template(template: ProblemTemplate, *, viewer_id: int | None = None) -> ProblemTemplateOut:
    return ProblemTemplateOut(
        id=template.id,
        share_code=template.share_code,
        title=template.title,
        description=template.description,
        submission_formats=template.submission_formats,
        grading_strictness=template.grading_strictness,
        grading_guideline_text=template.grading_guideline_text,
        syntax_check_enabled=template.syntax_check_enabled,
        publisher_display_name=template.publisher_display_name,
        created_at=template.created_at,
        taken_down=template.taken_down_at is not None,
        checklist_items=[
            ProblemTemplateChecklistItemOut(label=i.label, required=i.required, order=i.order)
            for i in template.checklist_items.all()
        ],
        is_mine=viewer_id is not None and template.published_by_id == viewer_id,
    )


def _get_visible_template_or_404(share_code: str) -> ProblemTemplate:
    """내려진 템플릿은 링크로도 열리지 않는다(#320 AC) — 가져오기·신고처럼
    「내려진 뒤에는 누구도 상호작용할 수 없다」가 성립해야 하는 엔드포인트가
    쓴다. 미리보기(`get_problem_template`)는 올린 사람 본인에게는 예외를
    두므로 이 함수를 쓰지 않는다."""

    try:
        return ProblemTemplate.objects.prefetch_related("checklist_items").get(
            share_code=share_code, taken_down_at__isnull=True
        )
    except ProblemTemplate.DoesNotExist as exc:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.") from exc


def _get_template_by_share_code_or_404(share_code: str) -> ProblemTemplate:
    try:
        return ProblemTemplate.objects.prefetch_related("checklist_items").get(
            share_code=share_code
        )
    except ProblemTemplate.DoesNotExist as exc:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.") from exc


@router.post(
    "/classes/{class_id}/problems/{problem_id}/publish-template",
    response={200: ProblemTemplateOut, 201: ProblemTemplateOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def publish_template(
    request, class_id: int, problem_id: int, payload: PublishTemplateIn
):
    """자기 문제를 템플릿으로 공개한다(#316). 원본 소유권 검사는 강사 전용
    엔드포인트와 같은 강사 범위(`instructor_scope.problem_scope`)를 그대로
    쓴다 — 남의 문제면 404다. 공개는 원본을 바꾸지 않는 사본을 뜨는 것이라
    `classroom.participation` 「열어 두는 것」의 "클래스 템플릿 공개"와 같은
    이유로 `write=False`다.

    **같은 문제에 살아 있는 템플릿이 이미 있으면 새로 만들지 않는다**(#333
    AC) — 그 템플릿을 200으로 그대로 돌려준다. 새로 만들었을 때만 201이다.

    공개자 이름은 템플릿 갤러리를 로그인한 모두가 보므로 금칙어 검사를
    받는다(spec #474, #477) — `publish_problem_as_template`이 사본을 뜨기
    전에 막는다."""

    problem = problem_scope(class_id, problem_id, request.auth_user.id, write=False).problem
    _reject_if_banned_name(payload.publisher_display_name)

    template, created = publish_problem_as_template(
        problem,
        published_by_id=request.auth_user.id,
        publisher_display_name=payload.publisher_display_name,
    )
    status = 201 if created else 200
    return status, _serialize_template(template, viewer_id=request.auth_user.id)


@router.get(
    "/problem-templates", response=list[ProblemTemplateListItemOut], auth=jwt_auth
)
@paginate(PageNumberPagination, page_size=20)
def list_problem_templates(request, q: str | None = None, **kwargs):
    """제목 검색 + 최신순뿐이다(#318 — 분류 체계를 만들지 않는다). 내려진
    템플릿은 나오지 않는다."""

    qs = ProblemTemplate.objects.filter(taken_down_at__isnull=True)
    if q:
        qs = qs.filter(title__icontains=q)
    return qs


@router.get(
    "/problem-templates/mine", response=list[ProblemTemplateOut], auth=jwt_auth
)
def list_my_problem_templates(request):
    """내가 올린 템플릿 전부(내린 것 포함) — 내리기 화면이 여기서 고른다.
    정적 세그먼트라 `/{share_code}`보다 먼저 등록한다(파일 상단 docstring)."""

    templates = ProblemTemplate.objects.filter(
        published_by_id=request.auth_user.id
    ).prefetch_related("checklist_items")
    return [_serialize_template(t, viewer_id=request.auth_user.id) for t in templates]


@router.get(
    "/problem-templates/{share_code}",
    response={200: ProblemTemplateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_problem_template(request, share_code: str):
    """가져오기 전 미리보기(#316 AC) — 제목·설명·체크리스트를 본다.

    **올린 사람 본인에게는 내려간 뒤에도 보인다** — 그러지 않으면 「내리기」
    버튼을 누른 직후 관리 화면 대신 「더 이상 사용할 수 없습니다」로 튕겨
    자기 것을 확인할 길이 사라진다(`/problem-templates/mine`과 같은 예외,
    코드리뷰 지적). 남에게는 그대로 404다."""

    template = _get_template_by_share_code_or_404(share_code)
    if template.taken_down_at is not None and template.published_by_id != request.auth_user.id:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.")
    return 200, _serialize_template(template, viewer_id=request.auth_user.id)


@router.post(
    "/problem-templates/{share_code}/import",
    response={201: ProblemOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def import_template(request, share_code: str, payload: ImportTemplateIn):
    """자기 클래스로 가져온다(#316) — 가져온 문제는 초안이고, 체크리스트는
    순서 그대로 따라오며, 채점 모델은 대상 클래스의 기본값을 따른다.

    **보관된 클래스로는 가져올 수 없다**(#438) — 보관은 읽기 전용이라는
    뜻이고, 가져오기는 그 클래스에 새 내용을 만드는 일이다
    (`instructor_scope.class_scope(..., write=True)`, `Class.archived_at`
    docstring)."""

    template = _get_visible_template_or_404(share_code)
    target_class = class_scope(payload.target_class_id, request.auth_user.id, write=True).class_obj

    problem = import_problem_template(template, target_class)
    return 201, _serialize_problem(problem, target_class)


@router.post(
    "/problem-templates/{share_code}/takedown",
    response={200: ProblemTemplateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def takedown_own_template(request, share_code: str):
    """올린 사람이 자기 템플릿을 내린다(#316 AC) — 남의 템플릿은 404다(존재를
    알려주지 않는다, 이 앱의 다른 소유권 검사와 같은 이유). 이미 가져간
    사람의 것은 그대로다 — 사본이기 때문이다. 이미 내려간 템플릿을 다시
    내려도 오류를 내지 않는다(멱등, `archive_class`와 같은 관용구)."""

    try:
        template = ProblemTemplate.objects.get(
            share_code=share_code, published_by_id=request.auth_user.id
        )
    except ProblemTemplate.DoesNotExist as exc:
        raise HttpError(404, "템플릿을 찾을 수 없습니다.") from exc

    if template.taken_down_at is None:
        template.taken_down_at = timezone.now()
        template.save(update_fields=["taken_down_at"])
    return 200, _serialize_template(template, viewer_id=request.auth_user.id)


@router.post(
    "/problem-templates/{share_code}/report",
    response={201: ReportResultOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def report_template(request, share_code: str, payload: ReportTemplateIn):
    """부적절한 템플릿을 신고한다(#320). 자기 템플릿은 신고 대상이 아니다 —
    내리면 된다(AC). 같은 사람이 같은 템플릿을 여러 번 신고해도 한 건으로
    센다 — 두 번째 신고는 첫 신고 행을 그대로 둔다(unique 제약, 모델
    docstring 참고)."""

    template = _get_visible_template_or_404(share_code)
    if template.published_by_id == request.auth_user.id:
        raise HttpError(403, "자기 템플릿은 신고할 수 없습니다. 내리려면 취소를 이용하세요.")

    ProblemTemplateReport.objects.get_or_create(
        template=template,
        reporter_id=request.auth_user.id,
        defaults={"reason": payload.reason},
    )
    return 201, ReportResultOut(reported=True)


# --- 클래스 템플릿 (#319) -----------------------------------------------------
#
# 문제 템플릿과 같은 규율이다(공개·내리기·미리보기·이름 적기는 #316 것을
# 그대로 쓴다, #319 body) — 새로 정한 것은 클래스 단위로 무엇이 담기고
# 무엇이 안 담기는가뿐이라, 아래 헬퍼·엔드포인트도 위 문제 템플릿의 짝을
# 그대로 옮긴 모양이다. 신고·운영자 모더레이션은 #319 AC에 없어 만들지
# 않는다.


def _serialize_class_template(template: ClassTemplate, *, viewer_id: int | None = None) -> ClassTemplateOut:
    problems = list(template.problems.all())
    return ClassTemplateOut(
        id=template.id,
        share_code=template.share_code,
        name=template.name,
        publisher_display_name=template.publisher_display_name,
        created_at=template.created_at,
        taken_down=template.taken_down_at is not None,
        problems=[
            ClassTemplateProblemOut(
                title=p.title,
                description=p.description,
                submission_formats=p.submission_formats,
                grading_strictness=p.grading_strictness,
                grading_guideline_text=p.grading_guideline_text,
                syntax_check_enabled=p.syntax_check_enabled,
                order=p.order,
                checklist_items=[
                    ProblemTemplateChecklistItemOut(label=i.label, required=i.required, order=i.order)
                    for i in p.checklist_items.all()
                ],
            )
            for p in problems
        ],
        problem_count=len(problems),
        is_mine=viewer_id is not None and template.published_by_id == viewer_id,
    )


def _get_visible_class_template_or_404(share_code: str) -> ClassTemplate:
    """`_get_visible_template_or_404`와 같은 이유 — 내려진 템플릿은 가져오기
    등에서 링크로도 열리지 않는다."""

    try:
        return ClassTemplate.objects.prefetch_related("problems__checklist_items").get(
            share_code=share_code, taken_down_at__isnull=True
        )
    except ClassTemplate.DoesNotExist as exc:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.") from exc


def _get_class_template_by_share_code_or_404(share_code: str) -> ClassTemplate:
    try:
        return ClassTemplate.objects.prefetch_related("problems__checklist_items").get(
            share_code=share_code
        )
    except ClassTemplate.DoesNotExist as exc:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.") from exc


@router.post(
    "/classes/{class_id}/publish-template",
    response={200: ClassTemplateOut, 201: ClassTemplateOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def publish_class_template(request, class_id: int, payload: PublishTemplateIn):
    """자기 클래스를 통째로 템플릿으로 공개한다(#319) — 문제들과 그 순서,
    각 문제의 체크리스트가 함께 담긴다. 소유권 검사는 문제 템플릿과 같은
    강사 범위(`instructor_scope.class_scope`)를 그대로 쓴다 — 남의 클래스면
    404다. 공개는 원본을 바꾸지 않으므로 `publish_template`과 같은 이유로
    `write=False`다.

    **같은 클래스에 살아 있는 템플릿이 이미 있으면 새로 만들지 않는다**(#333
    AC) — `publish_template`과 같은 규율, 200/201로 새로 만들었는지를 구별한다.

    공개자 이름 검사도 `publish_template`과 같다(spec #474, #477) —
    `PublishTemplateIn`을 그대로 공유하므로 규칙 표의 같은 줄이 두
    엔드포인트를 함께 막는다."""

    class_obj = class_scope(class_id, request.auth_user.id, write=False).class_obj
    _reject_if_banned_name(payload.publisher_display_name)
    template, created = publish_class_as_template(
        class_obj,
        published_by_id=request.auth_user.id,
        publisher_display_name=payload.publisher_display_name,
    )
    status = 201 if created else 200
    return status, _serialize_class_template(template, viewer_id=request.auth_user.id)


@router.get(
    "/class-templates", response=list[ClassTemplateListItemOut], auth=jwt_auth
)
@paginate(PageNumberPagination, page_size=20)
def list_class_templates(request, q: str | None = None, **kwargs):
    """제목(클래스 이름) 검색 + 최신순뿐이다 — `list_problem_templates`와 같은
    규율이다. 내려진 템플릿은 나오지 않는다."""

    qs = ClassTemplate.objects.filter(taken_down_at__isnull=True)
    if q:
        qs = qs.filter(name__icontains=q)
    return qs


@router.get(
    "/class-templates/mine", response=list[ClassTemplateOut], auth=jwt_auth
)
def list_my_class_templates(request):
    """내가 올린 클래스 템플릿 전부(내린 것 포함). 정적 세그먼트라
    `/{share_code}`보다 먼저 등록한다(파일 상단 docstring)."""

    templates = ClassTemplate.objects.filter(
        published_by_id=request.auth_user.id
    ).prefetch_related("problems__checklist_items")
    return [_serialize_class_template(t, viewer_id=request.auth_user.id) for t in templates]


@router.get(
    "/class-templates/{share_code}",
    response={200: ClassTemplateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_class_template(request, share_code: str):
    """가져오기 전 미리보기(#319 AC) — 몇 개의 문제가 들어 있는지와 그
    제목들, 각 문제의 체크리스트를 순서 그대로 본다.

    올린 사람 본인에게는 내려간 뒤에도 보인다 — `get_problem_template`과
    같은 예외."""

    template = _get_class_template_by_share_code_or_404(share_code)
    if template.taken_down_at is not None and template.published_by_id != request.auth_user.id:
        raise HttpError(404, "이 템플릿은 더 이상 사용할 수 없습니다.")
    return 200, _serialize_class_template(template, viewer_id=request.auth_user.id)


@router.post(
    "/class-templates/{share_code}/import",
    response={201: ClassOut, 404: ErrorOut},
    auth=jwt_auth,
)
def import_class_template_view(request, share_code: str, payload: ImportClassTemplateIn):
    """자기 계정에 새 클래스로 가져온다(#319) — 이름은 가져가는 사람이
    정하고, 문제들은 순서 그대로·체크리스트도 순서 그대로 따라오되 초안으로
    들어오며, 채점 모델은 대상(새 클래스)의 기본값을 따른다. 새 클래스는
    자기만의 새 가입 코드를 갖는다 — 원본의 것이 따라오지 않는다."""

    template = _get_visible_class_template_or_404(share_code)
    new_class = import_class_template(
        template, instructor_id=request.auth_user.id, name=payload.name
    )
    return 201, _serialize_class(new_class)


@router.post(
    "/class-templates/{share_code}/takedown",
    response={200: ClassTemplateOut, 404: ErrorOut},
    auth=jwt_auth,
)
def takedown_own_class_template(request, share_code: str):
    """올린 사람이 자기 클래스 템플릿을 내린다(#319) — 남의 템플릿은 404다.
    이미 가져간 사람의 클래스는 그대로다 — 사본이기 때문이다. 이미 내려간
    템플릿을 다시 내려도 오류를 내지 않는다(멱등, `takedown_own_template`과
    같은 관용구)."""

    try:
        template = ClassTemplate.objects.get(
            share_code=share_code, published_by_id=request.auth_user.id
        )
    except ClassTemplate.DoesNotExist as exc:
        raise HttpError(404, "템플릿을 찾을 수 없습니다.") from exc

    if template.taken_down_at is None:
        template.taken_down_at = timezone.now()
        template.save(update_fields=["taken_down_at"])
    return 200, _serialize_class_template(template, viewer_id=request.auth_user.id)
