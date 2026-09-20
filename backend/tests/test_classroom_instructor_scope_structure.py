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
        "copy_class_view": "원본을 바꾸지 않고 복사해 새로 여는 것이다(participation 「복사해서 새로 열기」) — class_scope(write=False)만 부른다.",
        "regenerate_join_link": "보관된 클래스라도 링크 재발급은 막지 않는다(가입 자체는 join_class가 따로 막는다) — class_scope(write=False)만 부른다.",
        "archive_class": "보관을 여는 동작 자신이라 보관 여부로 스스로를 막을 수 없다 — class_scope(write=False)만 부른다.",
        "unarchive_class": "보관을 되돌리는 동작이다(participation 「열어 두는 것」의 '보관 되돌리기') — class_scope(write=False)만 부른다.",
        "delete_class": "클래스 삭제 자체다(participation 「열어 두는 것」) — 제출이 있으면 따로 403, class_scope(write=False)만 부른다.",
        "join_class": "참여자가 여는 문이다 — 강사 전용 범위 밖, class_scope/problem_scope를 부르지 않는다.",
        "expel_member": "보관된 클래스에서도 명단 정리는 연다(새 활동을 만들지 않는다) — class_scope(write=False)만 부른다.",
        "rename_myself": "참여자 본인이 여는 문이다 — 강사 전용 범위 밖(_get_member_or_404를 쓴다).",
        "create_classroom_submission": "참여자와 강사가 같은 주소를 걷는 혼합 라우트다 — 강사 분기도 class_scope/problem_scope가 아니라 .filter(...).first()로 존재를 숨기지 않는다(get_my_problem과 같은 이유).",
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
