"""강사 전용 라우트가 여는 문 — 소유권 → 존재 → 보관을 한 번의 호출로 판정한다
(#463, spec #461).

**문제였던 것.** 강사 전용 엔드포인트마다 "이 클래스가 내 것인가 → (문제를
다룬다면) 이 문제가 그 클래스 것인가 → 쓰기라면 보관되지 않았는가"를 2~4줄
주문으로 순서대로 붙여 왔다(`classroom.api`의 옛 `_get_owned_class_or_404`·
`_get_owned_problem_or_404`·`classroom.participation.assert_class_mutable`
세 조각). 순서가 뜻을 가지는데(존재를 먼저 확인해야 404가 403보다 앞서
나간다) 그것을 강제하는 것은 사람의 주의뿐이었다 — 새 쓰기 라우트가 마지막
`assert_class_mutable` 호출을 빠뜨려도 타입도 테스트도 알려주지 않았다.

**이 모듈이 하는 일.** `class_scope`/`problem_scope` 둘 다 그 순서 그대로를
한 번의 호출로 판정하고, 결과를 `InstructorScope` 객체 하나로 돌려준다.
`write` 인자는 키워드 전용이고 기본값이 없다 — 호출부가 "이 라우트가 쓰기인가"를
매번 명시적으로 답하게 만든다(그래야 안 적어서 빠뜨리는 경로 자체가 없다).
`write=True`일 때만 보관 확인을 건다 — 클래스 설정처럼 보관 뒤에도 열어 두는
자리는 `write=False`로 부르고, 그 이유는 호출부(`classroom.api`)에 남긴다
(`classroom.participation`의 "열어 두는 것" 목록과 같은 판단).

`tests/test_classroom_instructor_scope_structure.py`의 구조 검사가 「쓰기
라우트는 전부 쓰기 범위를 지난다」를 지킨다 — 새 쓰기 라우트가 `write=True`
호출을 빠뜨리면(또는 이 모듈을 거치지 않고 `Class.objects`를 직접 두드리면)
그 검사가 빨개진다. 명시적으로 보관을 확인하지 않기로 한 자리는 그 테스트의
`ALLOWLIST`에 이유와 함께 올라 있다 — `APP-BOUNDARY-EXCEPTION`과 같은 관용구다.

**이 모듈이 하지 않는 일 — ADR-0050.** 문제를 지금 지울 수 있는가
(`classroom.api._problem_deletable`)는 "이 문제 × 강사 자신의 시도"라는 전혀
다른 필터다 — 소유권·존재·보관과는 판정 축이 다르고, ADR-0050이 그 필터를
"넓히면 근거가 사라진다"고 못 박아 뒀다. 이 모듈은 그 필터를 참조하지도,
`InstructorScope`에 담지도 않는다 — 범위를 연 뒤에도 삭제 가능 여부는
`classroom.api`가 여전히 따로 묻는다.

**강사인가, 소유자인가 (#559, ADR-0055).** 문을 여는 것은 「이 클래스의 **강사**인가」
(`classroom.instructors.classes_taught_by`)다 — 강사가 아니면 404. 그 위에 `owner`
인자가 `write`와 같은 관용구(키워드 전용, 기본값 없음)로 「이 라우트가 **소유자** 전용인가」를
호출부마다 답하게 한다. 소유자 전용은 넷뿐이다(`CONTEXT.md` 「공동 강사」): 채점 키·예산,
클래스 삭제, 소유권 이전, 공동 강사 내보내기. 강사이지만 소유자가 아니면 403 이다 —
클래스는 보이므로 404 로 숨기지 않는다. 순서는 강사 확인(404) → 문제 존재(404) → 소유자
(403) → 보관(403)이다. 한 라우트 안에서 일부 칸만 소유자 전용이면(클래스 설정의 예산 칸·소유자의 강사 이름 칸)
`owner=False`로 연 뒤 그 칸에서 `InstructorScope.require_owner()`를 부른다. 공동 강사(#561)가
이 표시로 갈린다 — 강사 전용 라우트 전부를 공동 강사로 훑는 표는
`tests/test_classroom_co_instructor_permissions.py`에 있다.
`tests/test_classroom_instructor_scope_structure.py`의 `OWNER_ONLY_ROUTES`가 그 넷만
소유자를 확인하는지 지킨다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninja.errors import HttpError

from .instructors import classes_taught_by, is_owner
from .models import Class, Problem
from .participation import assert_class_mutable

#: 공동 강사가 소유자 전용 일을 부를 때의 거절 문구 — 화면과 연결된 앱이 같은 문장을 낸다.
OWNER_ONLY_MESSAGE = "클래스 소유자만 할 수 있습니다."


@dataclass(frozen=True)
class InstructorScope:
    """소유권·존재(·요청이 쓰기라면 보관 아님)까지 확인을 마친 결과 하나.

    `problem_scope`가 돌려줄 때만 `problem`이 채워진다 — `class_scope`가
    돌려주는 범위는 클래스 하나만 다루는 라우트(클래스 설정·명단 등)의 몫이다.
    """

    class_obj: Class
    #: 부른 사람이 이 클래스의 소유자인가(#559) — `require_owner`가 본다.
    is_owner: bool
    problem: Problem | None = None

    def require_owner(self) -> None:
        """소유자가 아니면 403. 클래스는 보이므로(강사다) 404 로 숨기지 않는다."""

        if not self.is_owner:
            raise HttpError(403, OWNER_ONLY_MESSAGE)


def _taught_class_or_404(class_id: int, user_id: int) -> Class:
    """부른 사람이 강사인 클래스만 돌려준다. 남의 것은 「없다」로 답한다 — 목록에도
    상세에도 나오지 않아야 한다는 AC(#278)를 403이 아니라 404로 지킨다."""

    try:
        return classes_taught_by(user_id).get(id=class_id)
    except Class.DoesNotExist as exc:
        raise HttpError(404, "클래스를 찾을 수 없습니다.") from exc


def _owned_problem_or_404(class_obj: Class, problem_id: int) -> Problem:
    try:
        return class_obj.problems.get(id=problem_id)
    except Problem.DoesNotExist as exc:
        raise HttpError(404, "문제를 찾을 수 없습니다.") from exc


def _open(
    class_obj: Class, user_id: int, *, write: bool, owner: bool, problem: Problem | None = None
) -> InstructorScope:
    scope = InstructorScope(
        class_obj=class_obj, is_owner=is_owner(class_obj, user_id), problem=problem
    )
    if owner:
        scope.require_owner()
    if write:
        assert_class_mutable(class_obj)
    return scope


def class_scope(class_id: int, user_id: int, *, write: bool, owner: bool) -> InstructorScope:
    """클래스 하나만 다루는 강사 전용 라우트가 첫 줄에서 부른다. `owner=True`면 강사
    확인 뒤에 소유자 확인(403)을, `write=True`면 그 뒤에 보관 확인까지 건다 —
    `assert_class_mutable`과 같은 거절 문구를 낸다."""

    return _open(_taught_class_or_404(class_id, user_id), user_id, write=write, owner=owner)


def problem_scope(class_id: int, problem_id: int, user_id: int, *, write: bool, owner: bool) -> InstructorScope:
    """클래스 밑의 문제 하나를 다루는 강사 전용 라우트가 첫 줄에서 부른다.
    순서는 강사 확인 → 문제 존재 → (소유자 전용이면) 소유자 → (쓰기라면) 보관
    아님이다 — 문제가 이 클래스의 것인지부터 확인해야 남의 클래스의 문제 id를
    넣어도 404로 막힌다."""

    class_obj = _taught_class_or_404(class_id, user_id)
    problem = _owned_problem_or_404(class_obj, problem_id)
    return _open(class_obj, user_id, write=write, owner=owner, problem=problem)


def owned_problem_or_404(class_obj: Class, problem_id: int) -> Problem:
    """`class_obj`가 이미 다른 방식으로 확인된 자리를 위한 좁은 재사용
    (`classroom.api.get_my_problem`·`create_classroom_submission`의 강사
    분기) — 그 두 라우트는 참여자와 같은 주소를 강사도 걷는 혼합 라우트라
    `class_scope`/`problem_scope`가 요구하는 "강사 전용"이 아니다(소유권
    확인이 404가 아니라 참여자 경로로 흘려보내는 `.filter(...).first()`
    이다). 존재 확인 하나만 이 모듈의 것을 그대로 빌려 쓴다."""

    return _owned_problem_or_404(class_obj, problem_id)
