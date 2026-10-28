"""강의실 판정의 세 번째 값 「확인 불가」(#811, ADR-0067).

판정은 met·unmet·unverifiable 이고 `is_met` 은 그대로다(확인 불가면 false). 확인 불가는 충족이 아니라
필수 항목이 확인 불가면 통과하지 못한다. 준비와 확인은 마운트된 HTTP API 로 하고(`tests.classroom_scenarios`),
벤더 응답만 녹화본으로 흉내 낸다 — 바깥에 나가지 않는다.
"""

from __future__ import annotations

import json

import pytest
from django.core.cache import caches

from classroom.gradability_hint import GRADABILITY_GUIDE, UNVERIFIABLE_THINGS, UNVERIFIABLE_VERDICT_RULE
from classroom.mcp_report_tools import _VERDICT
from classroom.models import ClassroomScore
from classroom.verdicts import verdict_of
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    mine,
    respond_with_verdicts,
    run_scan,
    submit_repository,
)
from tests.test_classroom_anthropic_key import _anthropic_vendor
from tests.test_classroom_connected_apps import _connect, _rpc


@pytest.fixture(autouse=True)
def _real_scoring():
    caches["rate_limits"].clear()
    with force_real_scoring_adapter():
        yield
    caches["rate_limits"].clear()


def _setup(client, *, required: list[str], optional: list[str] | None = None, anthropic: bool = False):
    owner = login(client, uid="verdict-owner")
    participant = login(client, uid="verdict-participant")
    if anthropic:
        from tests.classroom_scenarios import set_anthropic_key

        class_id = create_class(client, owner["access"], with_key=False)
        assert set_anthropic_key(client, owner["access"], class_id).status_code == 200
    else:
        class_id = create_class(client, owner["access"])
    problem = create_open_problem(
        client,
        owner["access"],
        class_id,
        required_labels=required,
        optional_labels=optional or [],
        syntax_check_enabled=False,
    )
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    return owner, participant, class_id, problem


def _report_verdicts(client, owner_access: str, class_id: int) -> list[dict]:
    token = _connect(client, owner_access)["access_token"]
    response = _rpc(client, token, "tools/call", {"name": "get_participant_report", "arguments": {"class_id": class_id}})
    result = response.json()["result"]
    assert result["isError"] is False, result
    [member] = [m for m in result["structuredContent"]["participants"] if not m["is_instructor"]]
    [cell] = member["problems"]
    return cell["latest"]


def test_an_unverifiable_required_item_does_not_pass_and_both_surfaces_say_unverifiable(client, db, monkeypatch):
    owner, participant, class_id, problem = _setup(
        client, required=["리디렉션 코드가 있다", "/숫자 주소가 실제로 이동한다"], optional=["주석이 있다"]
    )
    static, live, comment = problem.item_ids
    sent: list = []
    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": static, "verdict": "met", "reasoning": "302 로 보내는 코드가 있다."},
            {"requirement_id": live, "verdict": "unverifiable", "reasoning": "배포 주소에 접속해야 알 수 있다."},
            {"requirement_id": comment, "verdict": "unmet", "reasoning": "주석이 없다."},
        ],
        capture=sent,
    )

    run_scan(client)

    # 요청: 강의실 스키마는 verdict 세 값을 받고 is_met 을 받지 않는다. 프롬프트에 판정 규칙이 실린다.
    [body] = sent
    item = body["response_format"]["json_schema"]["schema"]["properties"]["verdicts"]["items"]
    assert item["properties"]["verdict"] == {"type": "string", "enum": ["met", "unmet", "unverifiable"]}
    assert item["required"] == ["requirement_id", "verdict", "reasoning"] and "is_met" not in item["properties"]
    prompt = body["messages"][1]["content"]
    assert UNVERIFIABLE_VERDICT_RULE in prompt
    # 실제 동작을 말하는 항목은 코드가 있어도 확인 불가, 존재를 말하는 항목은 정적 판정 — 판정 예시 두 줄(#816).
    assert "그 동작을 하는 코드가 있어도" in prompt and "어느 파일·함수" in prompt
    assert "→ unverifiable(근거: app.py 의 follow() 가 302 로 보내는 코드는 있다)" in prompt
    assert "리디렉션 응답으로 처리하는 코드가 있다」 → met." in prompt

    # REST: 필수 항목 하나가 확인 불가라 통과가 아니다. is_met 은 확인 불가에서 false.
    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["passed"] is False
    assert [(r["checklist_item_id"], r["is_met"], r["verdict"]) for r in attempt["score"]["reasoning"]] == [
        (static, True, "met"),
        (live, False, "unverifiable"),
        (comment, False, "unmet"),
    ]

    # MCP: 같은 세 값, met_count 는 충족만 센다.
    latest = _report_verdicts(client, owner["access"], class_id)
    assert [(v["is_met"], v["verdict"]) for v in latest["verdicts"]] == [
        (True, "met"),
        (False, "unverifiable"),
        (False, "unmet"),
    ]
    assert (latest["passed"], latest["met_count"]) == (False, 1)


def test_an_unverifiable_optional_item_does_not_block_passing(client, db, monkeypatch):
    _, participant, class_id, problem = _setup(client, required=["리디렉션 코드가 있다"], optional=["실제로 이동한다"])
    required, optional = problem.item_ids
    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": required, "verdict": "met", "reasoning": "코드가 있다."},
            {"requirement_id": optional, "verdict": "unverifiable", "reasoning": "접속해야 안다."},
        ],
    )

    run_scan(client)

    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["passed"] is True


def test_a_record_without_verdict_reads_its_verdict_from_is_met(client, db, monkeypatch):
    owner, participant, class_id, problem = _setup(client, required=["테스트가 있다"], optional=["주석이 있다"])
    required, optional = problem.item_ids
    # 옛 모양의 응답(is_met 뿐)도 받는다 — 저장은 verdict 를 채워서 한다.
    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": required, "is_met": True, "reasoning": "있다."},
            {"requirement_id": optional, "is_met": False, "reasoning": "없다."},
        ],
    )
    run_scan(client)
    score = ClassroomScore.objects.get()
    assert [r["verdict"] for r in score.reasoning] == ["met", "unmet"]
    # #811 전에 쓴 기록 흉내 — 지금 API 로는 verdict 없는 기록을 만들 수 없어 저장값에서 키만 걷어낸다.
    ClassroomScore.objects.filter(pk=score.pk).update(
        reasoning=[{k: v for k, v in r.items() if k != "verdict"} for r in score.reasoning]
    )

    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert [(r["is_met"], r["verdict"]) for r in attempt["score"]["reasoning"]] == [(True, "met"), (False, "unmet")]
    latest = _report_verdicts(client, owner["access"], class_id)
    assert [v["verdict"] for v in latest["verdicts"]] == ["met", "unmet"]


def test_claude_scoring_asks_for_the_three_values_too(client, db, monkeypatch, settings):
    _anthropic_vendor(monkeypatch)
    _, participant, class_id, problem = _setup(client, required=["/숫자 주소가 실제로 이동한다"], anthropic=True)
    [item_id] = problem.item_ids
    text = json.dumps(
        {"verdicts": [{"requirement_id": item_id, "verdict": "unverifiable", "reasoning": "접속해야 안다."}]},
        ensure_ascii=False,
    )
    body = {
        "type": "message",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 900, "output_tokens": 100},
    }
    calls = _anthropic_vendor(monkeypatch, post=lambda sent: (200, body))

    run_scan(client)

    [(_, _, kwargs)] = [c for c in calls if c[0] == "POST"]
    schema = kwargs["json"]["output_config"]["format"]["schema"]
    assert "verdict" in schema["properties"]["verdicts"]["items"]["required"]
    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["passed"] is False
    assert [(r["is_met"], r["verdict"]) for r in attempt["score"]["reasoning"]] == [(False, "unverifiable")]


def test_the_report_output_schema_keeps_is_met_required_and_verdict_optional():
    assert "is_met" in _VERDICT["required"] and "verdict" not in _VERDICT["required"]
    assert _VERDICT["properties"]["verdict"]["enum"] == ["met", "unmet", "unverifiable"]


def test_the_prompt_rule_uses_the_same_list_as_the_authoring_guide():
    assert UNVERIFIABLE_THINGS in GRADABILITY_GUIDE and UNVERIFIABLE_THINGS in UNVERIFIABLE_VERDICT_RULE
    assert "미루지 말고" in UNVERIFIABLE_VERDICT_RULE


def test_the_contest_scoring_never_loads_the_classroom_verdict_rule():
    import core.llm_scoring as contest

    source = open(contest.__file__, encoding="utf-8").read()
    assert "UNVERIFIABLE_VERDICT_RULE" not in source.replace("`UNVERIFIABLE_VERDICT_RULE`", "")
    assert "import" not in "".join(line for line in source.splitlines() if "gradability_hint" in line)


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"is_met": True}, "met"),
        ({"is_met": False}, "unmet"),
        ({"is_met": False, "verdict": "unverifiable"}, "unverifiable"),
        ({"is_met": True, "verdict": "met"}, "met"),
    ],
)
def test_the_derivation_rule(entry, expected):
    assert verdict_of(entry) == expected
