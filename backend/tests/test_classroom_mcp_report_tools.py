"""연결된 앱의 참여자 리포트와 제출 소스 열기 (#518, 부모 #511, ADR-0052·ADR-0040).

리포트는 화면의 명단 격자·문제별 제출 목록을 **같은 HTTP 로** 나란히 불러 숫자를 대조한다 —
두 표면이 같은 함수를 부른다는 것을 결과로 고정한다(내보낸 참여자 포함). 소스 열기는 큰 zip 이
상한에서 잘리고 잘렸다고 말하는지, 바이너리는 목록에만 남는지, 남의 클래스 제출은 열리지
않는지, 도구 자신의 낮은 분당 상한을 받는지를 본다. 둘 다 아무것도 기록하지 않는다.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta

import pytest
from django.core.cache import caches
from django.test import override_settings
from django.utils import timezone

from tests.classroom_scenarios import (
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    instructor_submissions,
    join_class,
    login,
    respond_with_verdicts,
    roster_grid,
    run_scan,
    submit_repository,
    submit_source,
    table_row_counts,
    user_id,
)
from tests.test_classroom_connected_apps import _connect, _rpc, _set_clock

CLASSES_URL = "/api/classroom/classes"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _call(client, token: str, name: str, **arguments):
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    return response.json()["result"]


def _structured(client, token: str, name: str, **arguments) -> dict:
    result = _call(client, token, name, **arguments)
    assert result["isError"] is False, result
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def _expel(client, access: str, class_id: int, display_name: str) -> None:
    members = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access)).json()
    member_id = next(m["id"] for m in members if m["display_name"] == display_name)
    response = client.post(f"{CLASSES_URL}/{class_id}/members/{member_id}/expel", **auth_header(access))
    assert response.status_code == 200, response.content


def _a_scored_class(client, monkeypatch):
    """문제 둘(저장소·소스), 참여자 셋 — 김하나는 저장소 문제를 통과했다가 다음 시도에서 떨어지고,
    이둘은 한 번 떨어진 뒤 내보내졌고, 박셋은 아무것도 내지 않았다. 김하나의 소스 시도는 채점 대기."""

    instructor = login(client, uid="mcp-report-teacher", email="teacher@school.example")
    access = instructor["access"]
    class_id = create_class(client, access, name="알고리즘")
    repo_problem = create_open_problem(
        client, access, class_id, title="정렬", optional_labels=["주석이 있다"], syntax_check_enabled=False
    )
    source_problem = create_open_problem(
        client, access, class_id, title="탐색", submission_formats=["source"], syntax_check_enabled=False
    )
    people = {}
    for uid, name in [("mcp-report-p1", "김하나"), ("mcp-report-p2", "이둘"), ("mcp-report-p3", "박셋")]:
        person = login(client, uid=uid, email=f"{uid}@student.example")
        join_class(client, person["access"], class_id, instructor_access=access, display_name=name)
        people[name] = person

    required, optional = repo_problem.item_ids
    with force_real_scoring_adapter():
        submit_repository(client, people["김하나"]["access"], class_id, repo_problem.id)
        respond_with_verdicts(
            monkeypatch,
            [
                {"requirement_id": required, "is_met": True, "reasoning": "테스트가 있다."},
                {"requirement_id": optional, "is_met": False, "reasoning": "주석이 없다."},
            ],
        )
        run_scan(client)
        submit_repository(client, people["김하나"]["access"], class_id, repo_problem.id)
        submit_repository(client, people["이둘"]["access"], class_id, repo_problem.id)
        respond_with_verdicts(
            monkeypatch,
            [
                {"requirement_id": required, "is_met": False, "reasoning": "테스트가 없다. " * 100},
                {"requirement_id": optional, "is_met": True, "reasoning": "주석이 있다."},
            ],
        )
        run_scan(client)
    # 스캔을 다시 돌리지 않아 이 시도는 채점을 기다린다.
    submit_source(
        client,
        people["김하나"]["access"],
        class_id,
        source_problem.id,
        participant_user_id=user_id("mcp-report-p1"),
        files={"main.py": "print('hi')\n"},
    )
    _expel(client, access, class_id, "이둘")
    return instructor, class_id, repo_problem, source_problem


def test_both_tools_are_listed_as_read_only(client, db):
    instructor = login(client, uid="mcp-report-list")
    token = _connect(client, instructor["access"])["access_token"]

    tools = {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}

    assert tools["get_participant_report"]["title"] == "참여자 리포트"
    assert tools["open_submission_source"]["title"] == "제출 소스 열기"
    for name in ["get_participant_report", "open_submission_source"]:
        assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools[name]["annotations"]["destructiveHint"] is False
    assert tools["get_participant_report"]["inputSchema"]["required"] == ["class_id"]
    assert tools["open_submission_source"]["inputSchema"]["required"] == ["submission_id"]
    assert "학생" not in json.dumps([tools["get_participant_report"], tools["open_submission_source"]], ensure_ascii=False)


def test_the_report_gives_the_same_numbers_as_the_grid_and_the_submission_lists(client, db, monkeypatch):
    instructor, class_id, repo_problem, source_problem = _a_scored_class(client, monkeypatch)
    access = instructor["access"]
    token = _connect(client, access)["access_token"]

    report = _structured(client, token, "get_participant_report", class_id=class_id)
    grid = roster_grid(client, access, class_id)
    listed = {
        problem.id: instructor_submissions(client, access, class_id, problem.id)
        for problem in (repo_problem, source_problem)
    }

    # 문제 줄의 달성률은 격자의 것과 같다(격자 머리의 기한 두 칸(#774)은 보고서 줄에 없어 견주지 않는다).
    stats_keys = ("id", "title", "status", "passed_count", "member_count", "pass_rate")
    assert [{k: p[k] for k in stats_keys} for p in report["problems"]] == [
        {k: p[k] for k in stats_keys} for p in grid["problems"]
    ]
    # 참여자는 격자와 같은 사람들, 같은 순서 — 내보낸 이둘도 표시와 함께 있다.
    assert [(m["id"], m["display_name"], m["is_instructor"], m["expelled"]) for m in report["participants"]] == [
        (m["id"], m["display_name"], m["is_instructor"], m["expelled"]) for m in grid["members"]
    ]
    assert {m["display_name"]: m["expelled"] for m in report["participants"]} == {
        "김하나": False,
        "이둘": True,
        "박셋": False,
    }

    grid_cells = {(m["id"], c["problem_id"]): c["status"] for m in grid["members"] for c in m["cells"]}
    for member in report["participants"]:
        for cell in member["problems"]:
            assert cell["status"] == grid_cells[(member["id"], cell["problem_id"])]
            attempts = [s for s in listed[cell["problem_id"]] if s["member_id"] == member["id"]]
            assert cell["attempt_count"] == len(attempts)
            if not attempts:
                assert cell["latest"] is None and cell["latest_submission_id"] is None
                assert cell["last_submitted_at"] is None
                continue
            newest = attempts[0]  # 화면 목록은 참여자 안에서 최신 시도가 먼저다
            assert cell["latest_submission_id"] == newest["id"] == cell["latest"]["submission_id"]
            assert cell["last_submitted_at"] == newest["created_at"]
            assert cell["latest"]["attempt_number"] == newest["attempt_number"]
            assert cell["latest"]["passed"] == newest["passed"]
            assert cell["latest"]["status"] == newest["status"]
            assert cell["latest"]["pending_reason"] == newest["pending_reason"]
            if newest["score"] is None:
                assert cell["latest"]["verdicts"] == [] and cell["latest"]["met_count"] is None
            else:
                assert [(v["checklist_item_id"], v["is_met"]) for v in cell["latest"]["verdicts"]] == [
                    (r["checklist_item_id"], r["is_met"]) for r in newest["score"]["reasoning"]
                ]
                assert cell["latest"]["met_count"] == sum(r["is_met"] for r in newest["score"]["reasoning"])

    by_name = {m["display_name"]: {c["problem_id"]: c for c in m["problems"]} for m in report["participants"]}
    # 김하나: 통과 이력은 남고(격자와 같다) 최신 시도는 미통과, 시도 둘.
    first = by_name["김하나"][repo_problem.id]
    assert (first["status"], first["passed"], first["attempt_count"]) == ("passed", True, 2)
    assert (first["latest"]["passed"], first["latest"]["met_count"], first["latest"]["item_count"]) == (False, 1, 2)
    pending = by_name["김하나"][source_problem.id]
    assert (pending["status"], pending["latest"]["status"], pending["latest"]["pending_reason"]) == ("scoring", "pending", None)
    assert by_name["이둘"][repo_problem.id]["status"] == "attempted_not_passed"
    assert by_name["박셋"][repo_problem.id]["attempt_count"] == 0

    # problem_id 로 좁히면 그 문제 하나만, 같은 칸이다.
    narrowed = _structured(client, token, "get_participant_report", class_id=class_id, problem_id=repo_problem.id)
    assert [p["id"] for p in narrowed["problems"]] == [repo_problem.id]
    assert {m["display_name"]: m["problems"] for m in narrowed["participants"]}["김하나"] == [first]


def test_long_reasoning_is_cut_and_the_report_has_no_email_or_source(client, db, monkeypatch):
    instructor, class_id, repo_problem, _source_problem = _a_scored_class(client, monkeypatch)
    token = _connect(client, instructor["access"])["access_token"]
    from classroom.mcp_report_tools import REASONING_MAX_CHARS

    body = _rpc(
        client, token, "tools/call", {"name": "get_participant_report", "arguments": {"class_id": class_id}}
    ).content.decode("utf-8")
    assert "@" not in body and "example" not in body
    assert "print(" not in body  # 소스는 리포트에 없다

    report = _structured(client, token, "get_participant_report", class_id=class_id)
    latest = {m["display_name"]: {c["problem_id"]: c["latest"] for c in m["problems"]} for m in report["participants"]}
    verdicts = {v["checklist_item_id"]: v for v in latest["김하나"][repo_problem.id]["verdicts"]}
    required, optional = repo_problem.item_ids
    verdict = verdicts[required]
    assert verdict["reasoning_truncated"] is True
    assert verdict["reasoning"] == ("테스트가 없다. " * 100)[:REASONING_MAX_CHARS] + "…"
    short = verdicts[optional]
    assert (short["reasoning"], short["reasoning_truncated"]) == ("주석이 있다.", False)


def test_a_big_zip_is_cut_at_the_limits_and_says_so(client, db, monkeypatch):
    monkeypatch.setattr("classroom.mcp_report_tools.FILE_MAX_BYTES", 40)
    monkeypatch.setattr("classroom.mcp_report_tools.TOTAL_MAX_BYTES", 70)
    monkeypatch.setattr("classroom.mcp_report_tools.MAX_LISTED_FILES", 5)
    instructor = login(client, uid="mcp-source-teacher")
    access = instructor["access"]
    class_id = create_class(client, access, with_key=False)
    problem = create_open_problem(client, access, class_id, submission_formats=["source"])
    participant = login(client, uid="mcp-source-p1")
    join_class(client, participant["access"], class_id, instructor_access=access, display_name="김하나")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a_small.py", "x = 1\n")  # 6 바이트 — 다 실린다
        zf.writestr("b_long.py", "y" * 100)  # 파일 상한 40 에서 잘린다
        zf.writestr("c_data.bin", b"\x89PNG\r\n\x1a\n\x00\x00binary")  # 바이너리 — 목록에만
        zf.writestr("d_rest.py", "z" * 100)  # 전체 상한(70)의 남은 24 만
        zf.writestr("e_after.py", "w = 2\n")  # 예산이 다 떨어져 내용 없이
        zf.writestr("node_modules/lib/index.js", "module.exports = 1\n")  # 의존성 — 목록 뒤로
        zf.writestr("f_overflow.py", "v = 3\n")  # 목록 상한(5) 밖
    submitted = submit_source(
        client, participant["access"], class_id, problem.id, participant_user_id=user_id("mcp-source-p1"), raw_bytes=buf.getvalue()
    )
    token = _connect(client, access)["access_token"]

    opened = _structured(client, token, "open_submission_source", submission_id=submitted["id"])

    assert opened["submission_format"] == "source"
    assert opened["source_found"] is True
    assert opened["participant"]["display_name"] == "김하나"
    assert opened["file_count"] == 7
    assert opened["files_listed_truncated"] is True
    assert opened["truncated"] is True
    files = {f["path"]: f for f in opened["files"]}
    assert list(files) == ["a_small.py", "b_long.py", "c_data.bin", "d_rest.py", "e_after.py"]
    assert (files["a_small.py"]["content"], files["a_small.py"]["truncated"]) == ("x = 1\n", False)
    assert (files["b_long.py"]["content"], files["b_long.py"]["truncated"]) == ("y" * 40, True)
    assert files["c_data.bin"]["kind"] == "binary" and files["c_data.bin"]["content"] is None
    assert (files["d_rest.py"]["content"], files["d_rest.py"]["truncated"]) == ("z" * 24, True)
    assert (files["e_after.py"]["kind"], files["e_after.py"]["content"], files["e_after.py"]["truncated"]) == (
        "text",
        None,
        True,
    )
    assert opened["limits"] == {"file_max_bytes": 40, "total_max_bytes": 70, "max_listed_files": 5}


def test_dependency_folders_are_listed_without_content(client, db):
    instructor = login(client, uid="mcp-source-deps")
    access = instructor["access"]
    class_id = create_class(client, access, with_key=False)
    problem = create_open_problem(client, access, class_id, submission_formats=["source"])
    participant = login(client, uid="mcp-source-deps-p")
    join_class(client, participant["access"], class_id, instructor_access=access)
    submitted = submit_source(
        client,
        participant["access"],
        class_id,
        problem.id,
        participant_user_id=user_id("mcp-source-deps-p"),
        files={"node_modules/x/index.js": "module.exports = 1\n", "src/main.js": "console.log(1)\n"},
    )
    token = _connect(client, access)["access_token"]

    opened = _structured(client, token, "open_submission_source", submission_id=submitted["id"])

    assert [(f["path"], f["kind"], f["content"]) for f in opened["files"]] == [
        ("src/main.js", "text", "console.log(1)\n"),
        ("node_modules/x/index.js", "skipped", None),
    ]
    assert opened["truncated"] is False


@override_settings(GITHUB_FAKE_REPO_FILES={"https://github.com/kim/sort": {"sort.py": "def sort(xs):\n    return sorted(xs)\n"}})
def test_a_repository_submission_gives_the_url_and_what_scoring_saw(client, db, monkeypatch):
    instructor = login(client, uid="mcp-repo-teacher")
    access = instructor["access"]
    class_id = create_class(client, access)
    problem = create_open_problem(client, access, class_id, syntax_check_enabled=False)
    participant = login(client, uid="mcp-repo-p1")
    join_class(client, participant["access"], class_id, instructor_access=access)
    submitted = submit_repository(client, participant["access"], class_id, problem.id, url="https://github.com/kim/sort")
    token = _connect(client, access)["access_token"]

    before = _structured(client, token, "open_submission_source", submission_id=submitted["id"])
    assert before["repository_url"] == "https://github.com/kim/sort"
    assert before["scored_content"] is None  # 아직 채점되지 않았다 — 본 것이 없다
    assert before["files"] == [] and before["source_found"] is None

    with force_real_scoring_adapter():
        respond_with_verdicts(monkeypatch, [{"requirement_id": problem.item_id, "is_met": True, "reasoning": "됐다"}])
        run_scan(client)
    after = _structured(client, token, "open_submission_source", submission_id=submitted["id"])
    assert after["repository_url"] == "https://github.com/kim/sort"
    assert after["scored_content"] == "# sort.py\ndef sort(xs):\n    return sorted(xs)\n"
    assert after["scored_content_truncated"] is False

    monkeypatch.setattr("classroom.mcp_report_tools.TOTAL_MAX_BYTES", 10)
    cut = _structured(client, token, "open_submission_source", submission_id=submitted["id"])
    assert cut["scored_content"] == "# sort.py\n"
    assert cut["scored_content_truncated"] is True and cut["truncated"] is True


def test_someone_elses_submission_does_not_open(client, db):
    owner = login(client, uid="mcp-source-owner")
    class_id = create_class(client, owner["access"], with_key=False)
    problem = create_open_problem(client, owner["access"], class_id)
    participant = login(client, uid="mcp-source-their-p")
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    submitted = submit_repository(client, participant["access"], class_id, problem.id)

    stranger = login(client, uid="mcp-source-stranger")
    stranger_token = _connect(client, stranger["access"])["access_token"]
    for submission_id in (submitted["id"], submitted["id"] + 999):
        result = _call(client, stranger_token, "open_submission_source", submission_id=submission_id)
        assert result["isError"] is True
        assert result["content"][0]["text"] == "제출을 찾을 수 없습니다."
    report = _call(client, stranger_token, "get_participant_report", class_id=class_id)
    assert report["isError"] is True and report["content"][0]["text"] == "클래스를 찾을 수 없습니다."

    # 제출한 참여자 자신이 연결한 앱도 강사 도구로는 열지 못한다.
    participant_token = _connect(client, participant["access"])["access_token"]
    assert _call(client, participant_token, "open_submission_source", submission_id=submitted["id"])["isError"] is True

    bad = _call(client, stranger_token, "open_submission_source", submission_id="1")
    assert bad["isError"] is True and "submission_id" in bad["content"][0]["text"]


@override_settings(CLASSROOM_MCP_SOURCE_CALLS_PER_MINUTE=2)
def test_opening_sources_has_its_own_lower_per_minute_limit(client, db):
    instructor = login(client, uid="mcp-source-rate")
    access = instructor["access"]
    class_id = create_class(client, access, with_key=False)
    problem = create_open_problem(client, access, class_id)
    participant = login(client, uid="mcp-source-rate-p")
    join_class(client, participant["access"], class_id, instructor_access=access)
    submitted = submit_repository(client, participant["access"], class_id, problem.id)
    token = _connect(client, access)["access_token"]
    start = timezone.now().replace(second=5, microsecond=0) + timedelta(minutes=5)
    _set_clock(start)

    def _open():
        return _rpc(client, token, "tools/call", {"name": "open_submission_source", "arguments": {"submission_id": submitted["id"]}})

    assert _open().status_code == 200
    assert _open().status_code == 200
    limited = _open()
    assert limited.status_code == 429
    assert limited["Retry-After"] == "55"
    assert limited.json()["error"]["data"] == {"retryAfterSeconds": 55}
    # 다른 도구는 같은 분에도 그대로 불린다 — 전체 상한(120)은 아직 멀다.
    assert _call(client, token, "get_participant_report", class_id=class_id)["isError"] is False

    _set_clock(start + timedelta(minutes=1))
    assert _open().status_code == 200


def test_reading_reports_and_sources_leaves_no_record(client, db):
    """ADR-0040 — 연결된 앱이 누구의 리포트를 받고 어느 소스를 몇 번 열었는지는 어디에도 남지 않는다.

    채점은 필요 없다 — 저장소 제출 하나와 소스 제출 하나가 「열기」의 두 길(주소 · 파일 목록)을 다 밟는다.
    채점까지 도는 `_a_scored_class` 위에서는 이 시험 하나가 CPU 예산(1초)에 닿았다(부하 높은 머신에서 실제로 걸렸다).
    """

    instructor = login(client, uid="mcp-report-norecord-teacher", email="norecord-teacher@school.example")
    access = instructor["access"]
    class_id = create_class(client, access, name="알고리즘")
    repo_problem = create_open_problem(client, access, class_id, title="정렬", syntax_check_enabled=False)
    source_problem = create_open_problem(
        client, access, class_id, title="탐색", submission_formats=["source"], syntax_check_enabled=False
    )
    person = login(client, uid="mcp-report-norecord-p1", email="norecord-p1@student.example")
    join_class(client, person["access"], class_id, instructor_access=access, display_name="김하나")
    submit_repository(client, person["access"], class_id, repo_problem.id)
    submit_source(
        client,
        person["access"],
        class_id,
        source_problem.id,
        participant_user_id=user_id("mcp-report-norecord-p1"),
        files={"main.py": "print('hi')\n"},
    )
    token = _connect(client, access)["access_token"]
    submission_ids = [
        s["id"]
        for problem in (repo_problem, source_problem)
        for s in instructor_submissions(client, access, class_id, problem.id)
    ]
    assert len(submission_ids) == 2
    _call(client, token, "get_participant_report", class_id=class_id)  # 「마지막으로 쓴 날」은 첫 호출에 이미 적혔다

    before = table_row_counts()
    for _ in range(2):
        _structured(client, token, "get_participant_report", class_id=class_id)
        for submission_id in submission_ids:
            _structured(client, token, "open_submission_source", submission_id=submission_id)
    _call(client, token, "open_submission_source", submission_id=max(submission_ids) + 999)  # 거절된 열기도

    assert table_row_counts() == before
