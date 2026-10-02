"""연결된 앱이 클래스를 다룬다 — 화면과 같은 규칙, 쓰기마다 기록, OpenAI 키는 없다
(#516, spec #511, ADR-0052).

`/mcp` 에 JSON-RPC 를 보내 도구를 부르고, 같은 일을 화면 API 로도 해 본다 — 두 표면이
같은 서비스 함수(`classroom.class_authoring`)를 부르므로 거절 문장이 글자 하나까지 같아야
한다. 쓰기 기록(`ConnectedAppWrite`)은 아직 그것을 보여 주는 화면이 없어 행을 직접 센다.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches

from classroom.models import ConnectedAppWrite
from tests.classroom_scenarios import (
    CLASSES_URL,
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    get_class,
    join_code,
    list_problems,
    login,
    set_key,
)
from tests.test_classroom_connected_apps import _rpc
from tests.test_classroom_mcp_problem_tools import _ok, _refused, _screen_detail, _setup

CLASS_TOOLS = [
    "create_class",
    "copy_class",
    "archive_class",
    "unarchive_class",
    "update_class_settings",
    "regenerate_join_link",
    "import_problem_template",
    "import_class_template",
]


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _tools(client, token: str) -> dict:
    return {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}


def _records() -> list[tuple[str, int | None]]:
    return list(ConnectedAppWrite.objects.order_by("id").values_list("tool", "target_class_id"))


def _publish_problem_template(client, access: str, class_id: int, problem_id: int) -> str:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["share_code"]


def _publish_class_template(client, access: str, class_id: int) -> str:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["share_code"]


# --- 목록 ----------------------------------------------------------------------


def test_the_class_tools_are_listed_as_reversible_writes(client, db):
    _, _, token = _setup(client)
    tools = _tools(client, token)
    assert set(CLASS_TOOLS) <= set(tools)
    # 삭제·공개는 두 단계 확인과 함께 따로 연다(#515).
    assert not {"delete_class", "publish_class_template", "publish_problem_template"} & set(tools)
    for name in CLASS_TOOLS:
        annotations = tools[name]["annotations"]
        assert annotations["readOnlyHint"] is False, name
        assert annotations["destructiveHint"] is False, name
        assert tools[name]["inputSchema"]["additionalProperties"] is False, name


def test_no_tool_touches_the_openai_key(client, db):
    _, _, token = _setup(client)
    tools = _tools(client, token)
    for name, tool in tools.items():
        assert "key" not in name, name
        for prop in tool["inputSchema"].get("properties", {}):
            assert "key" not in prop and "openai" not in prop, (name, prop)


def test_settings_refuse_a_key_argument_and_leave_the_key_and_records_alone(client, db):
    instructor, class_id, token = _setup(client)
    set_key(client, instructor["access"], class_id, "sk-test-original-key-1111")
    before = get_class(client, instructor["access"], class_id)

    for argument in ("api_key", "openai_api_key", "openai_key"):
        refusal = _refused(
            client, token, "update_class_settings", {"class_id": class_id, "name": "새 이름", argument: "sk-leak-2222"}
        )
        assert refusal == f"알 수 없는 인자입니다: {argument}"

    after = get_class(client, instructor["access"], class_id)
    assert after["openai_key_masked"] == before["openai_key_masked"]
    assert after["name"] == before["name"]  # 거절이면 다른 칸도 바뀌지 않는다
    assert not ConnectedAppWrite.objects.exists()


def test_results_never_carry_any_piece_of_the_key(client, db):
    instructor, class_id, token = _setup(client)
    set_key(client, instructor["access"], class_id, "sk-test-original-key-9876")
    updated = _ok(client, token, "update_class_settings", {"class_id": class_id, "name": "바꾼 이름"})["class"]
    assert updated["has_openai_key"] is True
    assert "openai_key_masked" not in updated
    assert "9876" not in str(updated)


# --- 만들기·설정 ------------------------------------------------------------------


def test_a_class_made_by_the_app_is_what_the_screen_shows_and_leaves_one_record(client, db):
    instructor, _, token = _setup(client)

    made = _ok(client, token, "create_class", {"name": "알고리즘 1기", "instructor_display_name": "박강사"})["class"]

    screen = get_class(client, instructor["access"], made["id"])
    assert made["name"] == screen["name"] == "알고리즘 1기"
    assert made["instructor_display_name"] == screen["instructor_display_name"] == "박강사"
    assert made["join_code"] == screen["join_code"]
    assert made["has_openai_key"] is False
    (record,) = ConnectedAppWrite.objects.all()
    assert (record.tool, record.target_class_id) == ("create_class", made["id"])
    assert "알고리즘 1기" in record.summary


def test_settings_change_only_what_was_sent_and_refuse_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)

    updated = _ok(
        client,
        token,
        "update_class_settings",
        {
            "class_id": class_id,
            "instructor_display_name": "새 강사 이름",
            "default_model": "gpt-4o",
            "default_reasoning_effort": "high",
            "token_budget": 50000,
            "token_budget_warning_threshold_percent": 70,
        },
    )["class"]
    screen = get_class(client, instructor["access"], class_id)
    for field in (
        "name",
        "instructor_display_name",
        "default_model",
        "default_reasoning_effort",
        "token_budget",
        "token_budget_warning_threshold_percent",
    ):
        assert updated[field] == screen[field], field
    assert screen["name"] == "웹 스터디"  # 보내지 않은 칸은 그대로
    assert (screen["default_model"], screen["token_budget"]) == ("gpt-4o", 50000)

    def screen_patch(payload: dict) -> str:
        return _screen_detail(
            client.patch(
                f"{CLASSES_URL}/{class_id}", data=payload, content_type="application/json", **auth_header(instructor["access"])
            )
        )

    for payload in (
        {"default_model": "not-a-real-model"},
        {"instructor_display_name": "관리자"},
        {"name": "씨발 스터디"},
    ):
        assert _refused(client, token, "update_class_settings", {"class_id": class_id, **payload}) == screen_patch(
            payload
        ), payload

    assert _records() == [("update_class_settings", class_id)]
    assert "token_budget" in ConnectedAppWrite.objects.get().summary


def test_create_refuses_banned_names_like_the_screen(client, db):
    instructor, _, token = _setup(client)
    for payload in (
        {"name": "새 클래스", "instructor_display_name": "관리자"},
        {"name": "씨발 클래스", "instructor_display_name": "강사"},
    ):
        screen = _screen_detail(
            client.post(CLASSES_URL, data=payload, content_type="application/json", **auth_header(instructor["access"]))
        )
        assert _refused(client, token, "create_class", payload) == screen
    assert not ConnectedAppWrite.objects.exists()


def test_misshapen_arguments_are_refused_without_writing(client, db):
    _, class_id, token = _setup(client)
    assert _refused(client, token, "create_class", {"name": "이름만"}) == "빠진 인자가 있습니다: instructor_display_name"
    assert _refused(client, token, "update_class_settings", {"class_id": "1"}) == "class_id 는 정수여야 합니다."
    assert "token_budget" in _refused(client, token, "update_class_settings", {"class_id": class_id, "token_budget": 0})
    assert _refused(client, token, "import_class_template", {"share_code": "", "name": "x"}).startswith("share_code")
    assert not ConnectedAppWrite.objects.exists()


# --- 보관·복사·가입 링크 ---------------------------------------------------------------


def test_archive_unarchive_copy_and_join_link_stay_open_on_an_archived_class(client, db):
    instructor, class_id, token = _setup(client)
    create_open_problem(client, instructor["access"], class_id, title="1주차")
    old_code = join_code(client, instructor["access"], class_id)

    archived = _ok(client, token, "archive_class", {"class_id": class_id})["class"]
    assert archived["archived"] is True
    assert _ok(client, token, "archive_class", {"class_id": class_id})["class"]["archived"] is True  # 멱등

    # 보관된 클래스에서도 화면처럼 열려 있는 것들 — 설정·복사·링크 재발급.
    assert _ok(client, token, "update_class_settings", {"class_id": class_id, "name": "지난 학기"})["class"]["name"] == "지난 학기"
    copied = _ok(client, token, "copy_class", {"class_id": class_id})["class"]
    assert copied["name"] == "지난 학기 사본"
    assert copied["archived"] is False
    assert [p["title"] for p in list_problems(client, instructor["access"], copied["id"])] == ["1주차"]
    new_code = _ok(client, token, "regenerate_join_link", {"class_id": class_id})["join_code"]
    assert new_code != old_code
    assert join_code(client, instructor["access"], class_id) == new_code
    assert client.get(f"/api/classroom/join/{old_code}", **auth_header(instructor["access"])).status_code == 404

    # 보관된 클래스의 문제는 여전히 바꿀 수 없다 — 화면과 같은 문장으로.
    blocked = _refused(client, token, "create_problem", {"class_id": class_id, "title": "x", "submission_formats": ["source"]})
    assert blocked == _screen_detail(
        client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data={"title": "x", "submission_formats": ["source"]},
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
    )

    assert _ok(client, token, "unarchive_class", {"class_id": class_id})["class"]["archived"] is False
    assert get_class(client, instructor["access"], class_id)["archived"] is False

    assert _records() == [
        ("archive_class", class_id),
        ("archive_class", class_id),
        ("update_class_settings", class_id),
        ("copy_class", copied["id"]),
        ("regenerate_join_link", class_id),
        ("unarchive_class", class_id),
    ]
    assert new_code not in "".join(ConnectedAppWrite.objects.values_list("summary", flat=True))


def test_someone_elses_class_is_not_there(client, db):
    instructor, _, token = _setup(client)
    other = login(client, uid="mcp-class-other")
    theirs = create_class(client, other["access"], name="남의 클래스", with_key=False)
    screen = _screen_detail(client.get(f"{CLASSES_URL}/{theirs}", **auth_header(instructor["access"])))

    for name, arguments in (
        ("copy_class", {"class_id": theirs}),
        ("archive_class", {"class_id": theirs}),
        ("unarchive_class", {"class_id": theirs}),
        ("update_class_settings", {"class_id": theirs, "name": "빼앗은 이름"}),
        ("regenerate_join_link", {"class_id": theirs}),
    ):
        assert _refused(client, token, name, arguments) == screen, name
    assert get_class(client, other["access"], theirs)["name"] == "남의 클래스"
    assert not ConnectedAppWrite.objects.exists()


# --- 템플릿 가져오기 ------------------------------------------------------------


def test_importing_templates_matches_the_screen(client, db):
    instructor, class_id, token = _setup(client)
    publisher = login(client, uid="mcp-template-publisher")
    source_class = create_class(client, publisher["access"], name="공개한 수업", with_key=False)
    problem = create_open_problem(client, publisher["access"], source_class, title="두 수의 합")
    problem_code = _publish_problem_template(client, publisher["access"], source_class, problem.id)
    class_code = _publish_class_template(client, publisher["access"], source_class)

    imported = _ok(
        client, token, "import_problem_template", {"share_code": problem_code, "target_class_id": class_id}
    )["problem"]
    assert imported["status"] == "draft"
    assert imported["title"] == "두 수의 합"
    assert [p["id"] for p in list_problems(client, instructor["access"], class_id)] == [imported["id"]]

    new_class = _ok(client, token, "import_class_template", {"share_code": class_code, "name": "가져온 수업"})["class"]
    assert new_class["name"] == "가져온 수업"
    assert new_class["has_openai_key"] is False
    assert [p["title"] for p in list_problems(client, instructor["access"], new_class["id"])] == ["두 수의 합"]

    assert _records() == [("import_problem_template", class_id), ("import_class_template", new_class["id"])]
    record = ConnectedAppWrite.objects.get(tool="import_problem_template")
    assert record.target_problem_id == imported["id"]


def test_template_imports_refuse_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)
    publisher = login(client, uid="mcp-template-publisher")
    source_class = create_class(client, publisher["access"], name="공개한 수업", with_key=False)
    problem = create_open_problem(client, publisher["access"], source_class, title="두 수의 합")
    problem_code = _publish_problem_template(client, publisher["access"], source_class, problem.id)
    class_code = _publish_class_template(client, publisher["access"], source_class)
    access = instructor["access"]

    # 없는(내려진) 템플릿
    gone = _screen_detail(
        client.post(
            "/api/classroom/problem-templates/nope/import",
            data={"target_class_id": class_id},
            content_type="application/json",
            **auth_header(access),
        )
    )
    assert _refused(client, token, "import_problem_template", {"share_code": "nope", "target_class_id": class_id}) == gone
    assert _refused(client, token, "import_class_template", {"share_code": "nope", "name": "x"}) == gone

    # 금칙어 이름
    banned = _screen_detail(
        client.post(
            f"/api/classroom/class-templates/{class_code}/import",
            data={"name": "씨발 수업"},
            content_type="application/json",
            **auth_header(access),
        )
    )
    assert _refused(client, token, "import_class_template", {"share_code": class_code, "name": "씨발 수업"}) == banned

    # 보관된 클래스로는 가져올 수 없다
    archive_class(client, access, class_id)
    archived = _screen_detail(
        client.post(
            f"/api/classroom/problem-templates/{problem_code}/import",
            data={"target_class_id": class_id},
            content_type="application/json",
            **auth_header(access),
        )
    )
    assert (
        _refused(client, token, "import_problem_template", {"share_code": problem_code, "target_class_id": class_id})
        == archived
    )
    assert list_problems(client, access, class_id) == []
    assert not ConnectedAppWrite.objects.exists()
