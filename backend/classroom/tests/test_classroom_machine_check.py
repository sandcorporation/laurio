"""기계 판정과 staged 채점 갈래 (#1283, 스펙 #1282, CONTEXT.md 「기계 판정」).

- 판정기(`classroom.machine_check.judge`)는 순수 함수라 바이트(zip)만으로 시험한다 — 꼴 셋의 충족·미충족·판정 불가,
  나쁜 정규식(시간 한도)·큰 파일 한도.
- 규칙은 강사 HTTP API·MCP 로 읽고 쓴다(검증된 스키마만). 참여자 응답에는 싣지 않는다.
- staged 갈래는 스캔 HTTP 로 끝까지 돈다. 벤더 경계는 `respond_with_verdicts` 가 흉내 낸다(실제 호출 0, 돈 0) —
  기계만인 문제는 벤더 0회, 섞인 문제는 판단 항목만 프롬프트에 실린다. single_call 은 규칙을 보지 않는다.
"""

from __future__ import annotations

import pytest

from classroom import machine_check
from classroom.machine_check import MachineTree, judge
from classroom.models import ClassroomScore
from classroom.tests.test_classroom_mcp_problem_tools import _ok, _refused
from classroom.tests.test_classroom_connected_apps import _connect
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    instructor_submissions,
    join_class,
    login,
    mine,
    respond_with_verdicts,
    run_scan,
    submit_source,
    user_id,
    zip_bytes,
)

pytestmark = pytest.mark.usefixtures("reset_rate_limits")

TREE = {
    "repo-1a2b/src/app.py": "import os\n\ndef main():\n    print('hello')\n",
    "repo-1a2b/tests/test_app.py": "def test_main():\n    pass\n",
    "repo-1a2b/package.json": '{"name": "demo", "scripts": {"test": "vitest"}, "private": true}',
    "repo-1a2b/config.yaml": "server:\n  port: 8080\n",
    "repo-1a2b/pyproject.toml": '[tool.ruff]\nline-length = 120\n',
    "repo-1a2b/.env": "export DEBUG='false'\n# 주석\nPORT=3000\n",
    "repo-1a2b/broken.json": "{not json",
    "repo-1a2b/node_modules/left-pad/index.js": "module.exports = 1\n",
}


def _judge(rule: dict, files: dict[str, str] | None = None) -> machine_check.MachineVerdict:
    return judge(rule, MachineTree(zip_bytes(files if files is not None else TREE)))


# --- 판정기 --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "verdict", "evidence"),
    [
        ({"kind": "path_exists", "path": "src/app.py"}, "met", ("repo-1a2b/src/app.py",)),
        ({"kind": "path_exists", "path": "tests/**/test_*.py"}, "met", ("repo-1a2b/tests/test_app.py",)),
        ({"kind": "path_exists", "path": "*.py"}, "met", ("repo-1a2b/src/app.py",)),
        ({"kind": "path_exists", "path": "Dockerfile"}, "unmet", ()),
        # 벤더·빌드 폴더는 트리에 없다.
        ({"kind": "path_exists", "path": "node_modules/**"}, "unmet", ()),
        ({"kind": "file_contains", "path": "src/*.py", "text": "def main"}, "met", ("repo-1a2b/src/app.py:3",)),
        ({"kind": "file_contains", "path": "**/*.py", "pattern": r"^\s+print\("}, "met", ("repo-1a2b/src/app.py:4",)),
        ({"kind": "file_contains", "path": "src/*.py", "text": "argparse"}, "unmet", ("repo-1a2b/src/app.py",)),
        ({"kind": "file_contains", "path": "lib/*.py", "text": "x"}, "unmet", ()),
        ({"kind": "config_value", "path": "package.json", "key": "scripts.test", "value": "vitest"}, "met", ("repo-1a2b/package.json",)),
        ({"kind": "config_value", "path": "package.json", "key": "private", "value": "true"}, "met", ("repo-1a2b/package.json",)),
        ({"kind": "config_value", "path": "config.yaml", "key": "server.port", "value": "8080"}, "met", ("repo-1a2b/config.yaml",)),
        ({"kind": "config_value", "path": "pyproject.toml", "key": "tool.ruff.line-length", "value": "120"}, "met", ("repo-1a2b/pyproject.toml",)),
        ({"kind": "config_value", "path": ".env", "key": "DEBUG", "value": "false"}, "met", ("repo-1a2b/.env",)),
        ({"kind": "config_value", "path": ".env", "key": "PORT", "value": "8000"}, "unmet", ("repo-1a2b/.env",)),
        ({"kind": "config_value", "path": "package.json", "key": "scripts.lint", "value": "eslint"}, "unmet", ("repo-1a2b/package.json",)),
        ({"kind": "config_value", "path": "settings.json", "key": "a", "value": "b"}, "unmet", ()),
        # 파싱 실패는 미충족이 아니라 판정 불가다.
        ({"kind": "config_value", "path": "broken.json", "key": "a", "value": "b"}, "undetermined", ()),
    ],
)
def test_the_three_rule_kinds(rule, verdict, evidence):
    result = _judge(rule)

    assert (result.verdict, result.evidence) == (verdict, evidence)
    assert result.reasoning.startswith("기계 판정 — ")


def test_an_unreadable_file_is_undetermined_not_unmet(monkeypatch):
    monkeypatch.setattr(machine_check, "MAX_FILE_BYTES", 64)
    files = {"big.py": "x = 1\n" * 40, "small.py": "y = 2\n"}

    assert _judge({"kind": "file_contains", "path": "*.py", "text": "z = 3"}, files).verdict == "undetermined"
    # 읽을 수 있는 다른 파일에서 찾으면 충족이다.
    assert _judge({"kind": "file_contains", "path": "*.py", "text": "y = 2"}, files).verdict == "met"


def test_a_binary_file_is_undetermined():
    tree = MachineTree(zip_bytes({"a.txt": "a"}))
    binary = MachineTree(_zip_raw({"a.bin": b"\x00\x01\x02"}))

    assert judge({"kind": "file_contains", "path": "a.bin", "text": "x"}, binary).verdict == "undetermined"
    assert judge({"kind": "file_contains", "path": "a.txt", "text": "a"}, tree).verdict == "met"


def test_a_catastrophic_regex_hits_the_time_limit_and_is_undetermined(monkeypatch):
    monkeypatch.setattr(machine_check, "REGEX_TIMEOUT_SECONDS", 0.5)

    result = _judge({"kind": "file_contains", "path": "*.txt", "pattern": r"^(a+)+$"}, {"s.txt": "a" * 40 + "b"})

    assert result.verdict == "undetermined"
    assert "시간 한도" in result.reasoning


def test_a_non_zip_source_is_one_file_named_source():
    tree = MachineTree(b"print('hi')\n")

    assert judge({"kind": "file_contains", "path": "source", "text": "print"}, tree).evidence == ("source:1",)


def _zip_raw(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


# --- 강사 API·MCP --------------------------------------------------------------


def _item_url(class_id: int, problem_id: int, item_id: int | None = None) -> str:
    base = f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items"
    return base if item_id is None else f"{base}/{item_id}"


def _post_item(client, access, class_id, problem_id, **payload):
    return client.post(
        _item_url(class_id, problem_id), data=payload, content_type="application/json", **auth_header(access)
    )


def test_the_instructor_reads_and_writes_the_rule_and_participants_never_see_it(client, db):
    instructor = login(client, uid="instructor-1")
    access = instructor["access"]
    class_id = create_class(client, access)
    problem = create_open_problem(client, access, class_id, required_labels=["README 가 있다"])
    rule = {"kind": "file_contains", "path": "src/*.py", "text": "def main"}

    created = _post_item(client, access, class_id, problem.id, label="main 함수가 있다", machine_rule=rule)
    assert created.status_code == 201, created.content
    item = created.json()
    assert item["machine_rule"] == rule

    cleared = client.patch(
        _item_url(class_id, problem.id, item["id"]),
        data={"machine_rule": None},
        content_type="application/json",
        **auth_header(access),
    )
    assert cleared.status_code == 200, cleared.content
    assert cleared.json()["machine_rule"] is None
    relabeled = client.patch(
        _item_url(class_id, problem.id, problem.item_id),
        data={"machine_rule": {"kind": "path_exists", "path": "README.md"}},
        content_type="application/json",
        **auth_header(access),
    )
    assert relabeled.json()["machine_rule"] == {"kind": "path_exists", "path": "README.md"}
    # 규칙을 보내지 않은 고침은 규칙을 그대로 둔다.
    kept = client.patch(
        _item_url(class_id, problem.id, problem.item_id),
        data={"label": "README.md 가 있다"},
        content_type="application/json",
        **auth_header(access),
    )
    assert kept.json()["machine_rule"] == {"kind": "path_exists", "path": "README.md"}

    instructor_view = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(access)).json()
    assert [i["machine_rule"] for i in instructor_view["checklist_items"]] == [
        {"kind": "path_exists", "path": "README.md"},
        None,
    ]
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=access)
    participant_view = mine(client, participant["access"], class_id, problem.id)
    assert all(i["machine_rule"] is None for i in participant_view["problem"]["checklist_items"])


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "file_contains", "path": "*.py", "pattern": "(unclosed"},
        {"kind": "file_contains", "path": "*.py", "pattern": "a" * 201},
        {"kind": "file_contains", "path": "*.py", "text": "x", "pattern": "x"},
        {"kind": "file_contains", "path": "*.py"},
        {"kind": "config_value", "path": "a.json", "key": "k"},
        {"kind": "run_tests", "path": "."},
        {"kind": "path_exists", "path": ""},
    ],
)
def test_a_rule_outside_the_schema_is_refused(client, db, rule):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)

    response = _post_item(client, instructor["access"], class_id, problem.id, label="항목", machine_rule=rule)

    assert response.status_code == 422, response.content


def test_mcp_writes_the_rule_with_the_same_validation(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    token = _connect(client, instructor["access"])["access_token"]
    ref = {"class_id": class_id, "problem_id": problem.id}
    rule = {"kind": "config_value", "path": "package.json", "key": "scripts.test", "value": "vitest"}

    added = _ok(client, token, "add_checklist_item", {**ref, "label": "시험 명령이 있다", "machine_rule": rule})
    assert added["item"]["machine_rule"] == rule
    cleared = _ok(client, token, "update_checklist_item", {**ref, "item_id": added["item"]["id"], "machine_rule": None})
    assert cleared["item"]["machine_rule"] is None
    assert "pattern" in _refused(
        client, token, "add_checklist_item", {**ref, "label": "x", "machine_rule": {"kind": "file_contains", "path": "a"}}
    )


# --- staged 채점 갈래 ----------------------------------------------------------


def _world(client, items: list[tuple[str, dict | None]]) -> dict:
    instructor = login(client, uid="instructor-1")
    access = instructor["access"]
    class_id = create_class(client, access)
    problem = create_open_problem(client, access, class_id, required_labels=[], syntax_check_enabled=False, open=False, submission_formats=["source"])
    item_ids = []
    for label, rule in items:
        response = _post_item(client, access, class_id, problem.id, label=label, machine_rule=rule)
        assert response.status_code == 201, response.content
        item_ids.append(response.json()["id"])
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/open", content_type="application/json", **auth_header(access)
    )
    assert opened.status_code == 200, opened.content
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=access)
    submit_source(
        client, participant["access"], class_id, problem.id, participant_user_id=user_id("participant-1"), files=TREE
    )
    return {"class_id": class_id, "problem_id": problem.id, "item_ids": item_ids, "participant": participant, "access": access}


@pytest.fixture
def staged(monkeypatch):
    monkeypatch.setenv("CLASSROOM_SCORING_PIPELINE", "staged")


def test_a_machine_only_problem_calls_no_vendor(client, db, monkeypatch, staged):
    sent: list[dict] = []
    with force_real_scoring_adapter():
        respond_with_verdicts(monkeypatch, [], capture=sent)
        ctx = _world(
            client,
            [
                ("src/app.py 가 있다", {"kind": "path_exists", "path": "src/app.py"}),
                ("시험 폴더가 있다", {"kind": "path_exists", "path": "tests/*.py"}),
            ],
        )
        run_scan(client)

    assert sent == []
    score = ClassroomScore.objects.get()
    assert score.model_version == "machine-check-v1"
    assert [(r["checklist_item_id"], r["verdict"], r["source"]) for r in score.reasoning] == [
        (ctx["item_ids"][0], "met", "machine"),
        (ctx["item_ids"][1], "met", "machine"),
    ]
    shown = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0]
    assert all(v["reasoning"].startswith("기계 판정 — ") for v in shown["score"]["reasoning"])


def test_a_mixed_problem_sends_only_the_judgment_items(client, db, monkeypatch, staged):
    sent: list[dict] = []
    with force_real_scoring_adapter():
        ctx = _world(
            client,
            [
                ("README 의 설명이 친절하다", None),
                ("main 함수가 있다", {"kind": "file_contains", "path": "src/*.py", "text": "def main"}),
                # 판정 불가(파싱 실패)는 판단 항목처럼 모델에게 간다.
                ("설정이 올바르다", {"kind": "config_value", "path": "broken.json", "key": "a", "value": "b"}),
            ],
        )
        judged, machine, undetermined = ctx["item_ids"]
        respond_with_verdicts(
            monkeypatch,
            [
                {"requirement_id": judged, "is_met": True, "reasoning": "판정 근거"},
                {"requirement_id": undetermined, "is_met": False, "reasoning": "판정 근거"},
            ],
            capture=sent,
        )
        run_scan(client)

    assert len(sent) == 1
    prompt = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert f"requirement_id={judged} " in prompt
    assert f"requirement_id={undetermined} " in prompt
    # 확인하지 못함도 미충족처럼 메모와 함께 모델에게 간다(#1294).
    assert "설정이 올바르다 [기계 확인: " in prompt
    assert f"requirement_id={machine} " not in prompt
    score = ClassroomScore.objects.get()
    assert [(r["checklist_item_id"], r["verdict"], r["source"]) for r in score.reasoning] == [
        (judged, "met", "model"),
        (machine, "met", "machine"),
        (undetermined, "unmet", "model"),
    ]


def test_single_call_ignores_the_rules(client, db, monkeypatch):
    sent: list[dict] = []
    with force_real_scoring_adapter():
        ctx = _world(client, [("src/app.py 가 있다", {"kind": "path_exists", "path": "src/app.py"})])
        respond_with_verdicts(
            monkeypatch, [{"requirement_id": ctx["item_ids"][0], "is_met": True, "reasoning": "판정 근거"}], capture=sent
        )
        run_scan(client)

    assert len(sent) == 1
    score = ClassroomScore.objects.get()
    assert score.reasoning == [
        {"checklist_item_id": ctx["item_ids"][0], "is_met": True, "verdict": "met", "reasoning": "판정 근거"}
    ]


def test_reuse_takes_only_the_model_verdicts_and_judges_the_machine_items_again(client, db, monkeypatch, staged):
    monkeypatch.setenv("CLASSROOM_SCORE_REUSE", "on")
    sent: list[dict] = []
    with force_real_scoring_adapter():
        ctx = _world(
            client,
            [
                ("README 의 설명이 친절하다", None),
                ("src/app.py 가 있다", {"kind": "path_exists", "path": "src/app.py"}),
            ],
        )
        judged, machine = ctx["item_ids"]
        respond_with_verdicts(
            monkeypatch,
            [{"requirement_id": judged, "is_met": True, "reasoning": "판정 근거"}],
            model="gpt-4.1-mini",  # 재사용은 요청한 모델이 매긴 점수만 찾는다
            capture=sent,
        )
        run_scan(client)
        # 그 사이 강사가 기계 규칙을 바꾼다 — 판단 항목·소스가 같아 프롬프트는 같다.
        instructor = login(client, uid="instructor-1")
        changed = client.patch(
            _item_url(ctx["class_id"], ctx["problem_id"], machine),
            data={"machine_rule": {"kind": "file_contains", "path": "src/*.py", "text": "def main"}},
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
        assert changed.status_code == 200, changed.content
        second = login(client, uid="participant-2")
        join_class(client, second["access"], ctx["class_id"], instructor_access=instructor["access"])
        submit_source(
            client, second["access"], ctx["class_id"], ctx["problem_id"], participant_user_id=user_id("participant-2"), files=TREE
        )
        run_scan(client)

    assert len(sent) == 1
    first_score, reused = ClassroomScore.objects.order_by("id")
    assert [(r["checklist_item_id"], r["verdict"], r["source"]) for r in reused.reasoning] == [
        (judged, "met", "model"),
        (machine, "met", "machine"),
    ]
    assert "def main" in reused.reasoning[1]["reasoning"]
    assert reused.reasoning[0]["reused_from_score_id"] == first_score.id


def test_an_unmet_rule_is_not_final_and_goes_to_the_model_with_a_note(client, db, monkeypatch, staged):
    """#1294 — 기계 충족만 확정한다. 미충족은 「AI 판정 필요」로 메모와 함께 모델에게 가고, 모델 판정이 최종이다."""

    sent: list[dict] = []
    with force_real_scoring_adapter():
        ctx = _world(
            client,
            [
                ("src/app.py 가 있다", {"kind": "path_exists", "path": "src/app.py"}),
                ("README 가 있다", {"kind": "path_exists", "path": "README*"}),
            ],
        )
        confirmed, unmet = ctx["item_ids"]
        respond_with_verdicts(
            monkeypatch, [{"requirement_id": unmet, "is_met": True, "reasoning": "docs/readme.txt 에 설명이 있다"}], capture=sent
        )
        run_scan(client)

    assert len(sent) == 1
    prompt = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert f"requirement_id={confirmed} " not in prompt
    assert "기계 확인 완료" in prompt and "- src/app.py 가 있다" in prompt
    assert f"requirement_id={unmet} (필수): README 가 있다 [기계 확인: 경로 `README*` 에 맞는 파일이 소스에 없다.]" in prompt
    assert "판정이 아닙니다" in prompt
    score = ClassroomScore.objects.get()
    assert [(r["checklist_item_id"], r["verdict"], r["source"]) for r in score.reasoning] == [
        (confirmed, "met", "machine"),
        (unmet, "met", "model"),
    ]
    assert score.reasoning[1]["machine_note"] == "기계 확인: 경로 `README*` 에 맞는 파일이 소스에 없다."

    seen = instructor_submissions(client, ctx["access"], ctx["class_id"], ctx["problem_id"])[0]["score"]["reasoning"]
    assert [v.get("machine_note") for v in seen] == [None, "기계 확인: 경로 `README*` 에 맞는 파일이 소스에 없다."]
    shown = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0]
    assert all("machine_note" not in v for v in shown["score"]["reasoning"])
