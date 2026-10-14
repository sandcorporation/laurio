"""쓰기 라우트는 전부 쓰기 범위를 지난다 (#463, spec #461).

`classroom.instructor_scope`가 소유권 → 존재 → 보관을 한 번의 호출로 묶었다
(`class_scope`/`problem_scope`, `write=True`일 때만 보관까지 확인한다). 그
호출을 실제로 부르는지는 사람의 리뷰가 아니라 이 정적 스캔이 지킨다 —
`tests/test_app_boundaries.py`·`tests/test_contest_status_writes_are_declared.py`
와 같은 관용구(AST로 `backend/` 소스를 훑는 것)를 이 저장소의 두 라우터
파일(`classroom/api.py`·`classroom/template_api.py`)에 적용한다.

**무엇을 잡는가.** `@router.post`/`patch`/`put`/`delete`로 등록된 함수(=
쓰기 라우트) 전부를 훑어, `class_scope(...)`/`problem_scope(...)` 호출에
`write=True`가 리터럴로 박혀 있는지 본다. 없으면 `ALLOWLIST`에 이유와 함께
올라 있지 않은 한 실패한다 — `tests/test_app_boundaries.py`의
`APP-BOUNDARY-EXCEPTION`과 같은 원칙으로, 이유 없는 예외는 통과하지 못한다
(아래 `test_every_allowlist_entry_has_a_reason`).

**`ALLOWLIST`가 필요한 이유.** 모든 쓰기 라우트가 보관 확인을 요구하지는
않는다 — `classroom.participation` 모듈 docstring의 「열어 두는 것」
(클래스 설정·보관 되돌리기·복사해서 새로 열기·클래스 삭제·클래스 템플릿
공개 등)이 그 목록이다. 그런 라우트도 `class_scope`/`problem_scope`는
부르되(소유권·존재는 여전히 확인해야 한다) `write=False`로 부른다 — 이
스캔은 그 자리를 실패로 잡지 않고 이유와 함께 허용한다. 새 자원을 만드는
라우트(`create_class`·`import_class_template_view` 등, 아직 없는 클래스에는
열 문이 없다)와 클래스 기준이 아닌 다른 소유권(자기 템플릿 등)으로 여는
라우트도 같은 이유로 올라 있다.

**이 스캔이 실제로 무는지는 손으로도 확인했다(#463 AC)** — `open_problem`
에서 `problem_scope(...)` 호출을 잠깐 지워 이 테스트가 빨개지는 것을 보고
되돌렸다(작업 보고에 남긴다)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.ast_scan_support import BACKEND_ROOT

_SCOPE_CALL_NAMES = {"class_scope", "problem_scope"}

#: (파일, 함수 이름) → 이유. 이유가 비면 `test_every_allowlist_entry_has_a_reason`
#: 이 실패한다.
ALLOWLIST: dict[Path, dict[str, str]] = {
    Path("classroom/api.py"): {
        "create_class": "아직 없는 클래스를 만드는 라우트다 — 열 문이 없다(생성은 범위 밖, contests.transitions의 CREATION_STATES와 같은 경계).",
        "update_class": "클래스 설정은 보관 뒤에도 고친다(participation 모듈 docstring 「열어 두는 것」) — class_scope(write=False)만 부른다.",
        "set_class_openai_key": "update_class와 같은 이유 — 클래스 설정, class_scope(write=False)만 부른다.",
        "set_class_compatible_server": "set_class_openai_key와 같은 이유 — 채점 연결은 클래스 설정이다(#601).",
        "copy_class_view": "원본을 바꾸지 않고 복사해 새로 여는 것이다(participation 「복사해서 새로 열기」) — class_scope(write=False)만 부른다.",
        "regenerate_join_link": "보관된 클래스라도 링크 재발급은 막지 않는다(가입 자체는 join_class가 따로 막는다) — class_scope(write=False)만 부른다.",
        "archive_class": "보관을 여는 동작 자신이라 보관 여부로 스스로를 막을 수 없다 — class_scope(write=False)만 부른다.",
        "unarchive_class": "보관을 되돌리는 동작이다(participation 「열어 두는 것」의 '보관 되돌리기') — class_scope(write=False)만 부른다.",
        "delete_class": "클래스 삭제 자체다(participation 「열어 두는 것」) — 제출이 있으면 따로 403, class_scope(write=False)만 부른다.",
        "join_class": "참여자가 여는 문이다 — 강사 전용 범위 밖, class_scope/problem_scope를 부르지 않는다.",
        "expel_member": "보관된 클래스에서도 명단 정리는 연다(새 활동을 만들지 않는다) — class_scope(write=False)만 부른다.",
        "rename_myself": "참여자 본인이 여는 문이다 — 강사 전용 범위 밖(_get_member_or_404를 쓴다).",
        "create_classroom_submission": "참여자와 강사가 같은 주소를 걷는 혼합 라우트다 — 강사 분기도 class_scope/problem_scope가 아니라 .filter(...).first()로 존재를 숨기지 않는다(get_my_problem과 같은 이유).",
        "create_co_instructor_invite": "사람을 들이는 일은 클래스의 존폐 쪽이라 보관된 클래스에서도 연다(CONTEXT.md 「공동 강사」, #561) — class_scope(write=False)만 부른다.",
        "cancel_co_instructor_invite": "초대 만들기와 같은 이유 — 사람을 들이는 일은 보관과 무관하다(CONTEXT.md 「공동 강사」, #562). 강사 누구나 취소한다 — class_scope(write=False, owner=False)만 부른다.",
        "rename_my_instructor_name": "강사 이름은 클래스 설정과 같은 쪽이라 보관된 클래스에서도 바꾼다(#565, update_class 와 같은 이유) — class_scope(write=False, owner=False)만 부르고, 쓰는 자리는 부른 사람 자신의 자리뿐이다(classroom.co_instructors.rename_myself).",
        "leave_class": "사람이 드나드는 일은 보관과 무관하다 — 공동 강사는 보관된 클래스에서도 떠난다(CONTEXT.md 「공동 강사」, #563). class_scope(write=False, owner=False)만 부르고, 소유자의 떠나기는 classroom.co_instructors.leave 가 409 로 거절한다.",
        "request_ownership_transfer": "소유권 이전은 사람의 자리를 바꾸는 일이라 보관과 무관하다 — 보관된 클래스도 넘긴다(CONTEXT.md 「소유권 이전」, #564). 소유자 전용이라 class_scope(write=False, owner=True).",
        "cancel_ownership_transfer": "request_ownership_transfer 와 같은 이유 — class_scope(write=False, owner=True).",
        "accept_ownership_transfer": "request_ownership_transfer 와 같은 이유. 받는 사람은 공동 강사라 class_scope(write=False, owner=False) 뒤 classroom.ownership_transfers 가 받는 사람인지 본다(403).",
        "decline_ownership_transfer": "accept_ownership_transfer 와 같다.",
        "remove_co_instructor": "떠나기와 같은 이유 — 보관된 클래스에서도 공동 강사를 내보낸다(#563). 소유자 전용이라 class_scope(write=False, owner=True)를 부른다.",
        "accept_co_instructor_invite": "초대받은 사람이 여는 문이다 — 아직 강사가 아니므로 강사 전용 범위 밖이고, 보관된 클래스에서도 수락한다(#561). 초대 토큰과 행 잠금이 문이다(classroom.co_instructors).",
        "copy_problem": "원본(problem_scope write=False)과 대상(class_scope write=True) 둘을 부른다 — write=True 호출이 있어 이 표에 없어도 통과하지만, 원본 쪽 write=False 호출이 있다는 것을 여기 남겨 둔다.",
    },
    Path("classroom/template_api.py"): {
        "publish_template": "공개는 원본 문제를 바꾸지 않는 사본을 뜨는 것이다(participation 「열어 두는 것」의 '클래스 템플릿 공개'와 같은 이유) — problem_scope(write=False)만 부른다.",
        "takedown_own_template": "자기 템플릿을 내리는 것이다 — 클래스가 아니라 ProblemTemplate.published_by_id로 소유권을 확인해 class_scope/problem_scope를 부르지 않는다.",
        "report_template": "신고는 강사 전용 문이 아니다 — 템플릿을 볼 수 있는 로그인 사용자 누구나 연다.",
        "publish_class_template": "공개는 원본 클래스를 바꾸지 않는다(participation 「열어 두는 것」의 '클래스 템플릿 공개') — class_scope(write=False)만 부른다.",
        "import_class_template_view": "새 클래스를 만드는 라우트다(create_class와 같은 이유) — 열 문이 없다.",
        "takedown_own_class_template": "takedown_own_template과 같은 이유 — ClassTemplate.published_by_id로 소유권을 확인한다.",
    },
}


def _write_route_defs(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in ("post", "patch", "put", "delete")
            for dec in node.decorator_list
        )
    ]


def _has_write_true_scope_call(node: ast.AST) -> bool:
    """`class_scope(...)`/`problem_scope(...)` 호출 중 `write=True`가 리터럴로
    박힌 것이 몸통 어딘가에 있으면 참이다. `write=` 없이 부르거나 변수를
    넘기면(`write=some_flag`) 이 함수는 이를 "쓰기 범위를 지났다"로 보지
    않는다 — 리터럴이 아니면 정적으로 True인지 알 수 없기 때문이다(의도한
    한계, 아래 `test_the_known_bypass_shapes_are_caught` 참고)."""

    for call in ast.walk(node):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            continue
        if call.func.id not in _SCOPE_CALL_NAMES:
            continue
        for kw in call.keywords:
            if kw.arg == "write" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                return True
    return False


def test_every_write_route_passes_through_write_scope_or_is_allowlisted():
    offenders = []
    for relative_path, allowlist in ALLOWLIST.items():
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        route_names = {node.name for node in _write_route_defs(tree)}
        stale = set(allowlist) - route_names
        assert not stale, (
            f"{relative_path}의 ALLOWLIST에 더 이상 쓰기 라우트가 아닌 이름이 남아 있다: {stale}"
        )
        for node in _write_route_defs(tree):
            if node.name in allowlist:
                continue
            if not _has_write_true_scope_call(node):
                offenders.append(f"{relative_path}:{node.lineno} — {node.name}")

    assert not offenders, (
        "쓰기 라우트가 강사 범위(instructor_scope.class_scope/problem_scope)를 write=True로 "
        f"부르지 않는다: {offenders}. 보관 확인이 필요한 쓰기라면 write=True로 부르고, 정말 "
        "필요 없다면(participation 모듈의 「열어 두는 것」에 해당하면) 이 파일의 ALLOWLIST에 "
        "이유와 함께 올린다."
    )


def test_every_allowlist_entry_has_a_reason():
    empty = [
        f"{path}:{name}"
        for path, allowlist in ALLOWLIST.items()
        for name, reason in allowlist.items()
        if not reason.strip()
    ]
    assert not empty, f"이유 없는 ALLOWLIST 항목: {empty}"


# ---------------------------------------------------------------------------
# `_has_write_true_scope_call` 자체의 경계 — 스캔 로직이 옳은지는 실제
# 저장소가 우연히 깨끗해서가 아니라 이 표로 보장돼야 한다
# (`test_contest_status_writes_are_declared.py`와 같은 관용구).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source",
    [
        "def f(request, class_id, problem_id):\n"
        "    scope = problem_scope(class_id, problem_id, request.auth_user.id, write=True)\n",
        "def f(request, class_id):\n"
        "    class_obj = class_scope(class_id, request.auth_user.id, write=True).class_obj\n",
    ],
)
def test_the_known_good_shapes_are_recognized(source: str):
    tree = ast.parse(source)
    (func,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert _has_write_true_scope_call(func)


@pytest.mark.parametrize(
    "source",
    [
        # write 인자 자체가 없다 — 새 쓰기 라우트가 그대로 빠뜨린 모양.
        "def f(request, class_id, problem_id):\n"
        "    scope = problem_scope(class_id, problem_id, request.auth_user.id)\n",
        # write=False — 보관 확인을 켜지 않은 채 부른 모양.
        "def f(request, class_id):\n"
        "    class_obj = class_scope(class_id, request.auth_user.id, write=False).class_obj\n",
        # 범위 호출 자체가 없다 — Class를 직접 두드린 모양.
        "def f(request, class_id):\n"
        "    class_obj = Class.objects.get(id=class_id, instructor_id=request.auth_user.id)\n",
        # write=some_flag — 리터럴이 아니면 정적으로 True인지 알 수 없다.
        "def f(request, class_id, write_flag):\n"
        "    class_obj = class_scope(class_id, request.auth_user.id, write=write_flag).class_obj\n",
    ],
)
def test_the_known_bypass_shapes_are_caught(source: str):
    tree = ast.parse(source)
    (func,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert not _has_write_true_scope_call(func)


# ---------------------------------------------------------------------------
# 「강사인가」와 「소유자인가」 (#559, spec #558, ADR-0055)
#
# 강사 전용 범위는 `write`와 같은 관용구로 `owner`도 키워드 전용·기본값 없이
# 받는다 — 호출부가 "이 라우트가 소유자 전용인가"를 매번 답한다. 소유자 전용은
# `CONTEXT.md` 「공동 강사」가 말하는 넷뿐이다: 채점 키, 클래스 삭제,
# (앞으로 생길) 소유권 이전·공동 강사 내보내기. 이 표 밖의 라우트는 공동 강사(#561)에게도
# 열리고 이 표 안의 라우트만 403 을 낸다 — 그 경계를 사람의 주의가 아니라 이 스캔이 지킨다.
# 실제 응답은 `tests/test_classroom_co_instructor_permissions.py`가 HTTP 로 본다.
# ---------------------------------------------------------------------------

#: 강사 범위를 부르는 라우트 파일 전부 — 연결된 앱(MCP) 도구도 같은 함수를 부른다.
_SCOPE_CALLER_FILES = sorted(
    path.relative_to(BACKEND_ROOT)
    for path in (BACKEND_ROOT / "classroom").glob("*.py")
    if path.name != "instructor_scope.py"
)

#: (파일, 라우트 이름) → 어떻게 소유자를 확인하는가. 이 표 밖의 라우트는 소유자
#: 확인을 하면 안 된다(공동 강사에게 막히는 강사 전용 라우트가 남지 않게).
OWNER_ONLY_ROUTES: dict[Path, dict[str, str]] = {
    Path("classroom/api.py"): {
        "set_class_openai_key": "채점 키는 소유자의 비용이다 — class_scope(owner=True).",
        "set_class_compatible_server": "채점 연결(호환 서버)도 소유자의 비용과 신뢰다 — class_scope(owner=True).",
        "delete_class": "클래스의 존폐는 소유자 몫이다 — class_scope(owner=True).",
        "request_ownership_transfer": "소유권 이전은 소유자 몫이다(CONTEXT.md 「소유권 이전」, #564) — class_scope(owner=True).",
        "cancel_ownership_transfer": "이전 요청 취소도 소유자 몫이다(#564) — class_scope(owner=True).",
        "remove_co_instructor": "공동 강사 내보내기는 소유자 몫이다(CONTEXT.md 「공동 강사」, #563) — class_scope(owner=True).",
        "update_class": (
            "클래스 설정 전체는 강사 누구나 고치지만 소유자의 "
            "강사 이름 칸(#561)을 보낼 때만 소유자 전용이다 — class_scope(owner=False) 뒤 scope.require_owner()."
        ),
    },
    Path("classroom/template_api.py"): {},
}


def _scope_calls(node: ast.AST) -> list[ast.Call]:
    return [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in _SCOPE_CALL_NAMES
    ]


def _literal_kw(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value.value if isinstance(kw.value, ast.Constant) else ...
    return None


def _checks_owner(node: ast.AST) -> bool:
    """`owner=True` 리터럴 범위 호출이나 `.require_owner()` 호출이 몸통에 있으면 참."""

    if any(_literal_kw(call, "owner") is True for call in _scope_calls(node)):
        return True
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "require_owner"
        for call in ast.walk(node)
    )


def _route_defs(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in ("get", "post", "patch", "put", "delete")
            for dec in node.decorator_list
        )
    ]


def test_every_scope_call_states_owner_explicitly_as_a_literal():
    """`write` 와 같다 — 안 적어서(또는 변수로 넘겨서) 소유자 전용 여부가 흐려지는 경로를 없앤다."""

    offenders = []
    for relative_path in _SCOPE_CALLER_FILES:
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        for call in _scope_calls(tree):
            if _literal_kw(call, "owner") not in (True, False):
                offenders.append(f"{relative_path}:{call.lineno}")
    assert not offenders, f"owner=True/False 를 리터럴로 적지 않은 강사 범위 호출: {offenders}"


def test_owner_only_routes_pass_through_the_owner_scope():
    """키·삭제 라우트는 소유자 범위를 지난다."""

    missing = []
    for relative_path, owner_only in OWNER_ONLY_ROUTES.items():
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        routes = {node.name: node for node in _route_defs(tree)}
        stale = set(owner_only) - set(routes)
        assert not stale, f"{relative_path}의 OWNER_ONLY_ROUTES에 라우트가 아닌 이름이 남아 있다: {stale}"
        missing += [f"{relative_path} — {name}" for name in owner_only if not _checks_owner(routes[name])]
    assert not missing, f"소유자 전용 라우트가 소유자를 확인하지 않는다: {missing}"


def test_routes_outside_the_owner_only_table_do_not_check_owner():
    """표 밖의 강사 전용 라우트는 공동 강사에게도 열려야 한다 — 소유자 확인이 숨어 들면 빨개진다."""

    extra = []
    for relative_path, owner_only in OWNER_ONLY_ROUTES.items():
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        extra += [
            f"{relative_path} — {node.name}"
            for node in _route_defs(tree)
            if node.name not in owner_only and _checks_owner(node)
        ]
    assert not extra, f"OWNER_ONLY_ROUTES 밖에서 소유자를 확인한다(표에 이유와 함께 올리거나 걷는다): {extra}"


def test_every_owner_only_entry_has_a_reason():
    empty = [f"{p}:{n}" for p, table in OWNER_ONLY_ROUTES.items() for n, r in table.items() if not r.strip()]
    assert not empty, f"이유 없는 OWNER_ONLY_ROUTES 항목: {empty}"


# ---------------------------------------------------------------------------
# `Class.instructor` 를 직접 두드리는 자리 (#559)
#
# 「이 사람이 이 클래스의 강사인가」·「소유자인가」는 `classroom.instructors` 한 곳이
# 답한다. 공동 강사가 생기면 그 모듈의 「강사인가」만 넓히면 되도록, 화면 API·서비스·
# 이벤트·채점 알림·제출 해석기·탈퇴는 `instructor`/`instructor_id` 를 직접 비교·필터하지
# 않는다. 남는 자리는 **소유자 자체**를 뜻하는 곳뿐이고 아래 표에 이유가 있다.
#
# 연결된 앱(`mcp*`·`oauth*`·`connected_app*`)도 같은 스캔을 받는다(#560). 그쪽에는 Class 가
# 아닌 `instructor` 가 하나 더 있다 — **연결된 앱(`ConnectedApp`)의 주인(계정)**이다. 도구
# 처리기가 받는 `grant` 가 그 ConnectedApp 이라 `grant.instructor_id` 는 「누가 부르는가」이지
# 「이 클래스의 강사인가」가 아니다 — 그래서 `grant` 위의 속성은 잡지 않는다
# (`_CONNECTED_APP_RECEIVERS`). OAuth·쓰기 기록이 ConnectedApp 을 주인으로 고르는 자리는
# 아래 표에 함수별로 이유가 있다.
# ---------------------------------------------------------------------------

_DIRECT_REFERENCE_SKIPPED = {"instructors.py", "models.py"}

_DIRECT_REFERENCE_FILES = sorted(
    [
        path.relative_to(BACKEND_ROOT)
        for path in (BACKEND_ROOT / "classroom").glob("*.py")
        if path.name not in _DIRECT_REFERENCE_SKIPPED
    ]
    + [Path("submissions/resolvers.py"), Path("accounts/withdrawal.py")]
)

#: 이 이름의 변수는 ConnectedApp 이다 — 그 `instructor`/`instructor_id` 는 연결된 앱의 주인(계정)이다.
_CONNECTED_APP_RECEIVERS = {"grant"}

_CONNECTED_APP_OWNER = "ConnectedApp 의 주인(계정)을 고른다 — Class 의 강사가 아니다(연결된 앱의 주인은 계정, #560)."

#: (파일, 함수 이름) → 왜 소유자 자체를 뜻하는가.
DIRECT_INSTRUCTOR_ALLOWLIST: dict[Path, dict[str, str]] = {
    Path("classroom/class_authoring.py"): {
        "create_class": "새 클래스의 소유자를 정한다 — 만드는 사람이 소유자다.",
        "import_class_template_as": "템플릿을 가져온 사람이 새 클래스의 소유자다(services.import_class_template 로 넘긴다).",
    },
    Path("classroom/services.py"): {
        "copy_class": "복사한 사람이 새 클래스의 소유자다 — 공동 강사는 따라가지 않는다(CONTEXT.md 「공동 강사 초대」).",
        "import_class_template": "copy_class 와 같다 — 가져온 사람이 새 클래스의 소유자다.",
    },
    Path("classroom/scoring.py"): {
        "_mark_scoring_key_rejected": "키 거부 알림의 수신자 — 키 알림은 소유자에게만 간다(비용이 그 사람의 몫, ADR-0055).",
        "_mark_scoring_paused": "크레딧 소진·서버 연결 불가 알림의 수신자 — 크레딧도 서버도 소유자의 것이다(#586, #603).",
    },
    Path("classroom/ownership_transfers.py"): {
        "accept": "소유권 이전 수락이 소유자 자체를 바꾼다(CONTEXT.md 「소유권 이전」, #564) — 넘긴 사람을 읽어 공동 강사로 남기고 받는 사람을 소유자로 쓴다.",
    },
    Path("accounts/withdrawal.py"): {
        "_instructor_has_class_in_progress": "탈퇴 차단은 **소유한** 클래스만 센다(CONTEXT.md 「공동 강사」) — 공동 강사 자리는 탈퇴로 빠진다.",
    },
    Path("classroom/oauth.py"): {
        "issue_code": _CONNECTED_APP_OWNER,
        "refresh": _CONNECTED_APP_OWNER,
        "authenticate_access_token": _CONNECTED_APP_OWNER,
        "disconnect": _CONNECTED_APP_OWNER,
        "revoke_all_for_user": _CONNECTED_APP_OWNER,
        "active_connected_apps": _CONNECTED_APP_OWNER,
    },
    Path("classroom/connected_app_writes.py"): {
        "record_write": "쓰기 기록의 주인은 연결된 앱의 주인(계정)이다 — 어느 클래스의 강사인가와 무관하다.",
    },
}

_INSTRUCTOR_LOOKUP = re.compile(r"(^|__)instructor(_id)?$")


def _direct_instructor_references(tree: ast.AST) -> list[tuple[str, int]]:
    """`x.instructor`·`x.instructor_id`·`instructor=`/`classroom__instructor_id=` 키워드·
    `F("instructor_id")` 꼴 문자열을, 그것을 품은 가장 안쪽 함수 이름과 함께 돌려준다."""

    found: list[tuple[str, int]] = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            hit = (
                (
                    isinstance(child, ast.Attribute)
                    and child.attr in ("instructor", "instructor_id")
                    and not (isinstance(child.value, ast.Name) and child.value.id in _CONNECTED_APP_RECEIVERS)
                )
                or (isinstance(child, ast.keyword) and child.arg and _INSTRUCTOR_LOOKUP.search(child.arg))
                or (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                    and _INSTRUCTOR_LOOKUP.search(child.value)
                )
            )
            if hit:
                found.append((name, getattr(child, "lineno", getattr(node, "lineno", 0))))
            visit(child, name)

    visit(tree, "<module>")
    return found


def test_class_instructor_is_read_only_through_the_two_predicates():
    offenders = []
    for relative_path in _DIRECT_REFERENCE_FILES:
        allow = DIRECT_INSTRUCTOR_ALLOWLIST.get(relative_path, {})
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        offenders += [
            f"{relative_path}:{line} — {func}"
            for func, line in _direct_instructor_references(tree)
            if func not in allow
        ]
    assert not offenders, (
        "Class.instructor 를 직접 비교·필터한다 — classroom.instructors 의 「강사인가」"
        "(is_instructor·classes_taught_by·instructor_user_ids·is_instructor_q)나 「소유자인가」"
        f"(is_owner·classes_owned_by)를 거치거나, 소유자 자체를 뜻하면 표에 이유와 함께 올린다: {offenders}"
    )


def test_direct_instructor_allowlist_is_not_stale():
    stale = []
    for relative_path, allow in DIRECT_INSTRUCTOR_ALLOWLIST.items():
        assert relative_path in _DIRECT_REFERENCE_FILES, relative_path
        tree = ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8"))
        hits = {func for func, _ in _direct_instructor_references(tree)}
        stale += [f"{relative_path}:{name}" for name, reason in allow.items() if name not in hits or not reason.strip()]
    assert not stale, f"더 이상 직접 참조하지 않거나 이유가 빈 항목: {stale}"


@pytest.mark.parametrize(
    "source",
    [
        "def f(c, u):\n    return c.instructor_id == u\n",
        "def f(u):\n    return Class.objects.filter(instructor_id=u)\n",
        "def f(u):\n    return Class.objects.filter(instructor=u)\n",
        "def f(u):\n    return Problem.objects.filter(classroom__instructor_id=u)\n",
        "def f():\n    return ClassMember.objects.exclude(user_id=F('classroom__instructor_id'))\n",
        "def f(c):\n    return c.instructor\n",
    ],
)
def test_the_direct_reference_shapes_are_caught(source: str):
    assert _direct_instructor_references(ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "def f(c):\n    return c.instructor_display_name\n",
        "def f(m, c):\n    return MemberOut(is_instructor=is_instructor(c, m.user_id))\n",
        "def f(r, p, m, x):\n    return _create_submission_row(r, p, m, x, as_instructor=True)\n",
        # 연결된 앱의 주인(계정) — 도구가 「누가 부르는가」를 범위에 넘기는 모양.
        "def f(grant, a):\n    return class_scope(a, grant.instructor_id, write=False, owner=False)\n",
    ],
)
def test_the_lookalikes_are_not_caught(source: str):
    assert not _direct_instructor_references(ast.parse(source))


def test_a_class_instructor_reached_through_the_grant_is_still_caught():
    """`grant` 를 건너뛰는 것은 그 위의 속성 하나뿐이다 — 거기서 Class 로 내려가면 잡힌다."""

    source = "def f(grant, c):\n    return Problem.objects.filter(classroom__instructor_id=grant.instructor_id)\n"
    assert _direct_instructor_references(ast.parse(source))


# ---------------------------------------------------------------------------
# 연결된 앱의 소유자 전용 도구 (#560, spec #558)
#
# 연결된 앱은 화면과 같은 일을 하되 소유자 전용 일은 소유자일 때만이다. 도구 처리기는
# 라우트가 아니라 `_<도구 이름>` 함수라 `OWNER_ONLY_ROUTES` 와 같은 표를 처리기 이름으로 둔다.
# ---------------------------------------------------------------------------

_MCP_TOOL_FILES = sorted(
    path.relative_to(BACKEND_ROOT) for path in (BACKEND_ROOT / "classroom").glob("mcp*_tools.py")
)

#: (파일, 처리기 이름) → 어떻게 소유자를 확인하는가. 표 밖의 처리기는 소유자를 확인하지 않는다.
OWNER_ONLY_MCP_TOOLS: dict[Path, dict[str, str]] = {
    Path("classroom/mcp_destructive_tools.py"): {
        "_delete_class": "화면의 delete_class 와 같다 — class_scope(owner=True).",
    },
    Path("classroom/mcp_class_tools.py"): {
        "_update_class_settings": "화면의 update_class 와 같다 — 소유자의 강사 이름 칸을 보낼 때만 scope.require_owner().",
    },
}


def _top_level_defs(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def test_mcp_owner_only_tools_pass_through_the_owner_scope():
    missing = []
    for relative_path, owner_only in OWNER_ONLY_MCP_TOOLS.items():
        defs = _top_level_defs(ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8")))
        stale = set(owner_only) - set(defs)
        assert not stale, f"{relative_path}의 OWNER_ONLY_MCP_TOOLS에 없는 함수가 남아 있다: {stale}"
        missing += [f"{relative_path} — {name}" for name, reason in owner_only.items() if not reason.strip() or not _checks_owner(defs[name])]
    assert not missing, f"소유자 전용 도구가 소유자를 확인하지 않는다(또는 이유가 비었다): {missing}"


def test_mcp_tools_outside_the_owner_only_table_do_not_check_owner():
    extra = []
    for relative_path in _MCP_TOOL_FILES:
        owner_only = OWNER_ONLY_MCP_TOOLS.get(relative_path, {})
        defs = _top_level_defs(ast.parse((BACKEND_ROOT / relative_path).read_text(encoding="utf-8")))
        extra += [f"{relative_path} — {name}" for name, node in defs.items() if name not in owner_only and _checks_owner(node)]
    assert not extra, f"OWNER_ONLY_MCP_TOOLS 밖에서 소유자를 확인한다(표에 이유와 함께 올리거나 걷는다): {extra}"
