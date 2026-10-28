"""채점이 확인할 수 없는 항목 — 만들기 전 안내와 저장 뒤 경고 (#805).

판정은 `classroom.gradability_hint` 의 어구 규칙 한 자리이고, 연결된 앱(MCP)의 만들기·고치기
응답이 그 결과를 싣는다. 경고는 저장을 막지 않는다. 픽스처는 2026-10-28 클래스 6 문제 59
(「Dioxus로 숫자형 단축 URL 서비스」)의 체크리스트 아홉 문장이다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from classroom.gradability_hint import (
    GRADABILITY_GUIDE,
    GRADABILITY_LABEL_NOTE,
    GRADABILITY_TOOL_NOTE,
    gradability_warnings,
    unverifiable_reason,
)
from classroom.mcp import INSTRUCTIONS, TOOLS
from tests.classroom_scenarios import create_class, login
from tests.test_classroom_connected_apps import _connect, _rpc

# 문제 59 의 아홉 문장 — 정적 셋은 경고하지 않고, 실행·접속형 여섯은 경고한다.
STATIC = [
    "Dioxus 로 작성되어 있다",
    "긴 주소를 받아 숫자 단축 주소를 만드는 기능이 구현되어 있다",
    "README 에 실행 방법과 배포 방법이 적혀 있다",
]
RUN_OR_ACCESS = [
    "새 브라우저에서 로그인 없이 동작한다",
    "동시에 여러 개를 생성해도 충돌이 없다",
    "공개 /숫자 주소가 실제로 리디렉션된다",
    "서버를 재시작하거나 재배포한 뒤에도 단축 주소가 유지된다",
    "Cloudflare·Railway 배포가 실제로 연결되어 있다",
    "단축 주소를 만드는 데 걸리는 응답 시간이 200ms 이내다",
]


def test_problem_59_flags_the_six_run_or_access_items_and_not_the_static_three():
    items = [SimpleNamespace(id=i, label=label) for i, label in enumerate(STATIC + RUN_OR_ACCESS, start=1)]

    flagged = gradability_warnings(items)

    assert [w["checklist_item_id"] for w in flagged] == [4, 5, 6, 7, 8, 9]
    assert [w["text"] for w in flagged] == RUN_OR_ACCESS
    assert all(w["reason"] for w in flagged)


@pytest.mark.parametrize(
    "label",
    [
        "/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다",
        "숫자 id 를 중복 없이 발급하도록 잠금을 거는 코드가 구현되어 있다",
        "배포 설정 파일이 있다",
        "재시작 뒤에도 남도록 저장소에 쓰는 코드가 있다",
        "Railway 설정이 설정되어 있다",
        "README 에 접속 주소가 적혀 있다",
        "합을 출력한다",
        "",
    ],
)
def test_static_wording_is_not_flagged(label):
    assert unverifiable_reason(label) is None


@pytest.mark.parametrize(
    "label",
    [
        "The page works in the browser",
        "Handles concurrent requests",
        "The app is deployed on Vercel",
        "Responds in 50 ms",
        "3초 안에 응답한다",
        "새로고침해도 유지된다",
        "서버가 떠 있다",
        "버튼을 클릭하면 복사된다",
    ],
)
def test_english_and_other_wordings_are_flagged(label):
    assert unverifiable_reason(label) is not None


def test_the_guide_is_in_the_instructions_the_four_tools_and_the_label_argument():
    assert GRADABILITY_GUIDE in INSTRUCTIONS
    for name in ["create_problem", "update_problem", "add_checklist_item", "update_checklist_item"]:
        assert GRADABILITY_TOOL_NOTE in TOOLS[name].description, name
    for text in [GRADABILITY_GUIDE, GRADABILITY_TOOL_NOTE, GRADABILITY_LABEL_NOTE]:
        assert "301/302/307/308" in text  # 각 자리에 예시 하나
    assert GRADABILITY_LABEL_NOTE in TOOLS["add_checklist_item"].input_schema["properties"]["label"]["description"]
    assert GRADABILITY_LABEL_NOTE in TOOLS["update_checklist_item"].input_schema["properties"]["label"]["description"]
    create_items = TOOLS["create_problem"].input_schema["properties"]["checklist_items"]
    assert GRADABILITY_LABEL_NOTE in create_items["description"]
    assert GRADABILITY_LABEL_NOTE in create_items["items"]["properties"]["label"]["description"]


def _tool(client, token: str, name: str, arguments: dict) -> dict:
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


def test_the_connected_app_hears_the_warning_after_saving(client, db):
    instructor = login(client, uid="gradable-mcp")["access"]
    class_id = create_class(client, instructor, with_key=False)
    token = _connect(client, instructor)["access_token"]

    created = _tool(
        client,
        token,
        "create_problem",
        {
            "class_id": class_id,
            "title": "Dioxus로 숫자형 단축 URL 서비스",
            "submission_formats": ["repository"],
            "checklist_items": [{"label": label} for label in STATIC + RUN_OR_ACCESS],
        },
    )["problem"]
    assert len(created["checklist_items"]) == 9  # 저장은 막지 않는다
    ids = [i["id"] for i in created["checklist_items"]]
    assert [w["checklist_item_id"] for w in created["gradability_warnings"]] == ids[3:]
    assert set(created["gradability_warnings"][0]) == {"checklist_item_id", "text", "reason"}
    assert all(str(i) in created["gradability_warning"] for i in ids[3:])
    assert not any(str(i) in created["gradability_warning"].split("—")[0] for i in ids[:3])

    ref = {"class_id": class_id, "problem_id": created["id"]}
    rewritten = _tool(
        client,
        token,
        "add_checklist_item",
        {**ref, "label": "/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다"},
    )
    assert "gradability_warnings" not in rewritten

    added = _tool(client, token, "add_checklist_item", {**ref, "label": "공개 주소로 접속하면 열린다"})
    assert [w["checklist_item_id"] for w in added["gradability_warnings"]] == [added["item"]["id"]]  # 방금 더한 것만

    fixed = _tool(
        client,
        token,
        "update_checklist_item",
        {**ref, "item_id": added["item"]["id"], "label": "공개 주소 안내가 README 에 적혀 있다"},
    )
    assert "gradability_warnings" not in fixed

    again = _tool(client, token, "update_problem", {**ref, "title": "Dioxus 단축 URL"})["problem"]
    assert len(again["gradability_warnings"]) == 6


def test_descriptions_stay_under_the_client_limit_of_2048_characters():
    # Claude Code 는 MCP 서버 instructions 와 도구 설명을 2048자에서 자른다 — 안내가 잘리면 예시가 사라진다.
    assert len(INSTRUCTIONS) <= 2048
    for name in ["create_problem", "update_problem", "add_checklist_item", "update_checklist_item"]:
        assert len(TOOLS[name].description) <= 2048, name


# --- 강의실 화면의 REST (#810) ---------------------------------------------------------------


def _post(client, access, url, data):
    from tests.classroom_scenarios import auth_header

    return client.post(url, data=data, content_type="application/json", **auth_header(access))


def _patch(client, access, url, data):
    from tests.classroom_scenarios import auth_header

    return client.patch(url, data=data, content_type="application/json", **auth_header(access))


def test_the_classroom_screen_hears_the_warning_for_the_item_it_just_saved(client, db):
    instructor = login(client, uid="gradable-rest")["access"]
    class_id = create_class(client, instructor, with_key=False)
    base = f"/api/classroom/classes/{class_id}/problems"

    created = _post(
        client,
        instructor,
        base,
        {
            "title": "Dioxus로 숫자형 단축 URL 서비스",
            "description": "",
            "submission_formats": ["repository"],
            "checklist_items": [{"label": label} for label in STATIC + RUN_OR_ACCESS],
        },
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert len(body["checklist_items"]) == 9  # 저장은 막지 않는다
    ids = [i["id"] for i in body["checklist_items"]]
    assert [w["checklist_item_id"] for w in body["gradability_warnings"]] == ids[3:]
    assert set(body["gradability_warnings"][0]) == {"checklist_item_id", "text", "reason"}

    items_url = f"{base}/{body['id']}/checklist-items"
    ok = _post(client, instructor, items_url, {"label": "/숫자 경로를 리디렉션 응답으로 처리하는 코드가 있다"})
    assert ok.status_code == 201 and ok.json()["gradability_warnings"] == []  # 정적 확인 어구가 함께 있으면 안 걸린다

    bad = _post(client, instructor, items_url, {"label": "공개 주소로 접속하면 열린다"})
    assert bad.status_code == 201
    assert [w["checklist_item_id"] for w in bad.json()["gradability_warnings"]] == [bad.json()["id"]]  # 방금 더한 것만

    item_url = f"{items_url}/{bad.json()['id']}"
    toggled = _patch(client, instructor, item_url, {"required": False})
    assert toggled.json()["gradability_warnings"] == []  # 문구를 안 고쳤으면 다시 나무라지 않는다
    still = _patch(client, instructor, item_url, {"label": "배포가 실제로 연결되어 있다"})
    assert len(still.json()["gradability_warnings"]) == 1
    fixed = _patch(client, instructor, item_url, {"label": "공개 주소 안내가 README 에 적혀 있다"})
    assert fixed.json()["gradability_warnings"] == []


def test_the_screen_note_is_the_same_sentence_in_python_and_the_classroom_app():
    from pathlib import Path

    from classroom.gradability_hint import GRADABILITY_FORM_NOTE

    ts = Path(__file__).resolve().parents[2] / "classroom" / "lib" / "problems" / "gradability.ts"
    assert f'"{GRADABILITY_FORM_NOTE}"' in ts.read_text(encoding="utf-8")
