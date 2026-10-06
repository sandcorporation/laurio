"""공동 강사는 강사 전용 라우트 전부에서 소유자와 같은 답을 받는다 — 소유자 전용만 403
(#561, spec #558, ADR-0055).

표 하나(`ROUTES`)가 강사 전용 라우트(와 강사 분기가 있는 혼합 라우트) 전부를 든다. 같은
표를 세 사람이 걷는다:

- **소유자** — 표의 기대 응답 그대로.
- **공동 강사** — 소유자와 같다. 소유자 전용 줄만 403(`OWNER_ONLY_MESSAGE`) — 클래스는
  보이므로 404 가 아니다.
- **남** — 전부 404. 남의 클래스는 여전히 「없다」.

표가 빠뜨린 라우트가 없는지는 `test_the_table_covers_every_instructor_route`가 AST 로
지킨다 — 강사 범위(`class_scope`/`problem_scope`)나 「강사인가」(`classes_taught_by`)를
부르는 라우트가 표에 없으면 빨갛다. 공동 강사에게 404 를 내는 라우트가 숨어 남지 않게 하는
그물이다(spec #558 Further Notes).

준비는 전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`). 시험마다 새 세계를
만든다 — 쓰기 라우트가 세계를 바꾸므로 함께 쓸 수 없다. 준비는 픽스처라 CPU 한도(시험
본문)에 들지 않는다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable

import pytest

from classroom.instructor_scope import OWNER_ONLY_MESSAGE
from tests.ast_scan_support import BACKEND_ROOT
from tests.classroom_scenarios import (
    CLASSES_URL,
    OpenProblem,
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    login,
)


@dataclass
class World:
    access: dict[str, str]
    class_id: int
    problem: OpenProblem
    draft_problem_id: int
    draft_item_id: int
    hidden_problem_id: int
    member_id: int
    share_code: str
    invite_id: int
    co_instructor_id: int
    transfer_id: int


def _post(client, access, url, body=None):
    response = client.post(url, data=body or {}, content_type="application/json", **auth_header(access))
    assert response.status_code in (200, 201), response.content
    return response.json()


@pytest.fixture
def world(client, db) -> World:
    owner = login(client, "owner")
    co = login(client, "co")
    stranger = login(client, "stranger")
    learner = login(client, "learner")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    problem = create_open_problem(client, owner["access"], class_id, optional_labels=["README 가 있다"])
    draft = create_open_problem(client, owner["access"], class_id, title="초안", open=False)
    hidden = create_open_problem(client, owner["access"], class_id, title="숨길 것")
    _post(client, owner["access"], f"{CLASSES_URL}/{class_id}/problems/{hidden.id}/hide")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"])
    members = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(owner["access"])).json()
    member_id = next(m["id"] for m in members if not m["is_instructor"])
    published = _post(
        client,
        owner["access"],
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/publish-template",
        {"publisher_display_name": "강사"},
    )
    invite = _post(client, owner["access"], f"{CLASSES_URL}/{class_id}/co-instructor-invites")
    instructors = client.get(f"{CLASSES_URL}/{class_id}/instructors", **auth_header(owner["access"])).json()
    co_instructor_id = next(row["co_instructor_id"] for row in instructors if row["role"] == "co_instructor")
    # 공동 강사에게 온 대기 중 소유권 이전 요청(#564) — 수락·거절·취소 줄이 이것을 쓴다.
    transfer = _post(
        client, owner["access"], f"{CLASSES_URL}/{class_id}/ownership-transfers", {"co_instructor_id": co_instructor_id}
    )
    return World(
        access={"owner": owner["access"], "co_instructor": co["access"], "stranger": stranger["access"]},
        class_id=class_id,
        problem=problem,
        draft_problem_id=draft.id,
        draft_item_id=draft.item_id,
        hidden_problem_id=hidden.id,
        member_id=member_id,
        share_code=published["share_code"],
        invite_id=invite["id"],
        co_instructor_id=co_instructor_id,
        transfer_id=transfer["id"],
    )


@dataclass(frozen=True)
class Route:
    """`name` 은 라우트 함수 이름 — 같은 라우트의 다른 몸통은 `[...]` 를 붙인다."""

    name: str
    method: str
    path: Callable[[World], str]
    body: Callable[[World], dict] | None
    #: 소유자가 받는 응답 코드 — 공동 강사도 같다(소유자 전용 줄이 아니면).
    status: int
    owner_only: bool = False
    #: 공동 강사가 받는 응답이 소유자와 다른 줄(떠나기 — 소유자는 떠날 수 없다). 비면 `status`.
    co_status: int | None = None


def _c(w: World) -> str:
    return f"{CLASSES_URL}/{w.class_id}"


def _p(w: World, problem_id: int | None = None) -> str:
    return f"{_c(w)}/problems/{problem_id or w.problem.id}"


ROUTES: list[Route] = [
    # 클래스
    Route("get_class", "get", _c, None, 200),
    Route("update_class[name]", "patch", _c, lambda w: {"name": "새 이름", "default_reasoning_effort": "low"}, 200),
    Route("update_class[budget]", "patch", _c, lambda w: {"token_budget": 1000}, 200, owner_only=True),
    Route(
        "update_class[instructor_display_name]",
        "patch",
        _c,
        lambda w: {"instructor_display_name": "새 강사 이름"},
        200,
        owner_only=True,
    ),
    Route("set_class_openai_key", "put", lambda w: f"{_c(w)}/openai-key", lambda w: {"api_key": "sk-new"}, 200, owner_only=True),
    Route("copy_class_view", "post", lambda w: f"{_c(w)}/copy", None, 201),
    Route("list_class_scoring_models", "get", lambda w: f"{_c(w)}/scoring-models", None, 200),
    Route("regenerate_join_link", "post", lambda w: f"{_c(w)}/join-link/regenerate", None, 200),
    Route("archive_class", "post", lambda w: f"{_c(w)}/archive", None, 200),
    Route("unarchive_class", "post", lambda w: f"{_c(w)}/unarchive", None, 200),
    Route("delete_class", "delete", _c, None, 204, owner_only=True),
    Route("create_co_instructor_invite", "post", lambda w: f"{_c(w)}/co-instructor-invites", None, 201),
    Route("list_class_instructors", "get", lambda w: f"{_c(w)}/instructors", None, 200),
    Route("list_pending_co_instructor_invites", "get", lambda w: f"{_c(w)}/co-instructor-invites", None, 200),
    Route(
        "cancel_co_instructor_invite",
        "post",
        lambda w: f"{_c(w)}/co-instructor-invites/{w.invite_id}/cancel",
        None,
        204,
    ),
    # 떠나기(#563) — 소유자는 떠날 수 없어 409, 공동 강사는 떠난다.
    Route("leave_class", "post", lambda w: f"{_c(w)}/instructors/me/leave", None, 409, co_status=204),
    Route(
        "remove_co_instructor",
        "post",
        lambda w: f"{_c(w)}/co-instructors/{w.co_instructor_id}/remove",
        None,
        204,
        owner_only=True,
    ),
    # 소유권 이전(#564) — 요청·취소는 소유자 전용. 세계에 이미 대기 요청이 있어 소유자의 새 요청은 409.
    Route(
        "request_ownership_transfer",
        "post",
        lambda w: f"{_c(w)}/ownership-transfers",
        lambda w: {"co_instructor_id": w.co_instructor_id},
        409,
        owner_only=True,
    ),
    Route(
        "cancel_ownership_transfer",
        "post",
        lambda w: f"{_c(w)}/ownership-transfers/{w.transfer_id}/cancel",
        None,
        204,
        owner_only=True,
    ),
    # 수락·거절은 받는 사람(이 세계의 공동 강사) 본인만 — 소유자는 받는 사람이 아니라 403.
    Route("accept_ownership_transfer", "post", lambda w: f"{_c(w)}/ownership-transfers/{w.transfer_id}/accept", None, 403, co_status=200),
    Route("decline_ownership_transfer", "post", lambda w: f"{_c(w)}/ownership-transfers/{w.transfer_id}/decline", None, 403, co_status=204),
    Route("publish_class_template", "post", lambda w: f"{_c(w)}/publish-template", lambda w: {"publisher_display_name": "강사"}, 201),
    # 명단
    Route("list_members", "get", lambda w: f"{_c(w)}/members", None, 200),
    Route("expel_member", "post", lambda w: f"{_c(w)}/members/{w.member_id}/expel", None, 200),
    Route("get_roster_grid", "get", lambda w: f"{_c(w)}/roster-grid", None, 200),
    # 문제
    Route("create_problem", "post", lambda w: f"{_c(w)}/problems", lambda w: {"title": "새 문제", "submission_formats": ["repository"]}, 201),
    Route("list_problems", "get", lambda w: f"{_c(w)}/problems", None, 200),
    Route(
        "reorder_problems",
        "post",
        lambda w: f"{_c(w)}/problems/reorder",
        lambda w: {"problem_ids": [w.hidden_problem_id, w.draft_problem_id, w.problem.id]},
        200,
    ),
    Route("list_importable_contests", "get", lambda w: f"{_c(w)}/importable-contests", None, 200),
    Route("import_contest_as_problem", "post", lambda w: f"{_c(w)}/problems/from-contest", lambda w: {"contest_id": 987654321}, 422),
    Route("list_importable_problems", "get", lambda w: f"{_c(w)}/problems/from-other-classes", None, 200),
    Route("get_problem", "get", _p, None, 200),
    Route("update_problem", "patch", _p, lambda w: {"title": "고친 제목"}, 200),
    Route("delete_problem", "delete", _p, None, 204),
    Route("open_problem", "post", lambda w: f"{_p(w, w.draft_problem_id)}/open", None, 200),
    Route("hide_problem", "post", lambda w: f"{_p(w)}/hide", None, 200),
    Route("reopen_problem", "post", lambda w: f"{_p(w, w.hidden_problem_id)}/reopen", None, 200),
    Route("list_problem_submissions", "get", lambda w: f"{_p(w)}/submissions", None, 200),
    Route("copy_problem", "post", lambda w: f"{_p(w)}/copy", lambda w: {"target_class_id": w.class_id}, 201),
    # 이미 공개된 문제라(세계를 만들 때 공개했다) 살아 있는 템플릿을 그대로 돌려준다 — 200.
    Route("publish_template", "post", lambda w: f"{_p(w)}/publish-template", lambda w: {"publisher_display_name": "강사"}, 200),
    Route(
        "import_template",
        "post",
        lambda w: f"/api/classroom/problem-templates/{w.share_code}/import",
        lambda w: {"target_class_id": w.class_id},
        201,
    ),
    # 체크리스트
    Route("create_checklist_item", "post", lambda w: f"{_p(w)}/checklist-items", lambda w: {"label": "새 항목"}, 201),
    Route(
        "reorder_checklist_items",
        "post",
        lambda w: f"{_p(w)}/checklist-items/reorder",
        lambda w: {"item_ids": list(reversed(w.problem.item_ids))},
        200,
    ),
    Route("update_checklist_item", "patch", lambda w: f"{_p(w)}/checklist-items/{w.problem.item_id}", lambda w: {"label": "고친 항목"}, 200),
    # 열린 문제는 필수 항목을 하나 이상 지녀야 한다 — 초안의 항목을 지운다.
    Route(
        "delete_checklist_item",
        "delete",
        lambda w: f"{_p(w, w.draft_problem_id)}/checklist-items/{w.draft_item_id}",
        None,
        204,
    ),
    # 참여자와 강사가 같은 주소를 걷는 혼합 라우트 — 강사 분기를 탄다.
    Route("get_my_problem", "get", lambda w: f"{_p(w)}/mine", None, 200),
    Route(
        "create_classroom_submission",
        "post",
        lambda w: f"{_p(w)}/submissions",
        lambda w: {"value": "https://github.com/octocat/hello-world", "submission_format": "repository"},
        201,
    ),
    Route("get_contest_entry_form", "get", lambda w: f"{_p(w)}/contest-entry", None, 403),
]


def _call(client, world: World, route: Route, who: str):
    method = getattr(client, route.method)
    kwargs = auth_header(world.access[who])
    if route.body is not None:
        return method(route.path(world), data=route.body(world), content_type="application/json", **kwargs)
    if route.method in ("post", "put", "patch"):
        return method(route.path(world), content_type="application/json", **kwargs)
    return method(route.path(world), **kwargs)


def _detail(response) -> str | None:
    try:
        return response.json().get("detail")
    except (ValueError, AttributeError):
        return None


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
@pytest.mark.parametrize("who", ["owner", "co_instructor"])
def test_instructors_get_the_owners_answer_and_only_owner_only_routes_refuse_a_co_instructor(
    client, world, route, who
):
    response = _call(client, world, route, who)

    if who == "co_instructor" and route.owner_only:
        assert response.status_code == 403, response.content
        assert _detail(response) == OWNER_ONLY_MESSAGE
    else:
        expected = route.co_status if who == "co_instructor" and route.co_status is not None else route.status
        assert response.status_code == expected, response.content
        assert _detail(response) != OWNER_ONLY_MESSAGE


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_someone_elses_class_is_still_404(client, world, route):
    assert _call(client, world, route, "stranger").status_code == 404


# --- 표가 라우트 전부를 덮는가 --------------------------------------------------------

_ROUTE_FILES = [BACKEND_ROOT / "classroom/api.py", BACKEND_ROOT / "classroom/template_api.py"]
_INSTRUCTOR_GATES = {"class_scope", "problem_scope", "classes_taught_by"}


def _instructor_route_names() -> set[str]:
    names: set[str] = set()
    for path in _ROUTE_FILES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "patch", "put", "delete")
                for d in node.decorator_list
            )
            calls_gate = any(
                isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in _INSTRUCTOR_GATES
                for c in ast.walk(node)
            )
            if is_route and calls_gate:
                names.add(node.name)
    return names


#: 강사 판정을 부르지만 클래스 하나의 강사 라우트가 아닌 것 — 표 밖에 둔다.
_NOT_A_CLASS_ROUTE = {
    "list_joined_classes": "참여자 목록에서 가르치는 클래스를 빼려고 부른다 — 클래스 하나를 여는 문이 아니다.",
}


def test_the_table_covers_every_instructor_route():
    in_table = {route.name.split("[")[0] for route in ROUTES}
    missing = _instructor_route_names() - in_table - set(_NOT_A_CLASS_ROUTE)
    assert not missing, f"강사 라우트가 공동 강사 권한 표에 없다: {sorted(missing)}"
