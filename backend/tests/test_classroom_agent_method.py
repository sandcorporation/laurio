"""#1036: 강의실 채점·완성도 검사의 방식(한 번 호출/에이전트) — 클래스 키로 agent-grader·llm-proxy 를 탄다.

시임은 HTTP(클래스 설정·채점 스캔·완성도 버튼)다. 실행기 서비스 호출(`core.agent_scoring.request_run`)만
가짜로 바꾼다. 채점 시험의 가짜 실행기는 에이전트 CLI 가 하듯 **받은 실행 토큰으로 진짜 프록시 앱**
(`core.llm_proxy`)에 요청을 보내고, 프록시 뒤에는 가짜 벤더가 선다 — 벤더가 받은 키가 그 클래스의 키인지,
플랫폼 키가 아닌지, 키가 실행기·기록 어디에도 없는지를 본다.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from aiohttp.test_utils import TestClient
from asgiref.sync import async_to_sync
from django.test import override_settings

from classroom.models import ClassroomScore
from core.agent_run_tokens import spent_today_usd
from core.models import AgentRunToken
from core import agent_scoring
from classroom.models import ClassroomAgentRun as AgentRun
from tests.classroom_scenarios import (
    CLASSES_URL,
    REAL_SCORING_ADAPTER,
    auth_header,
    create_class,
    create_open_problem,
    get_class,
    join_class,
    login,
    mine,
    run_scan,
    set_anthropic_key,
    submit_repository,
)
from tests.test_classroom_anthropic_key import _anthropic_vendor
from tests.test_classroom_compatible_server import _class_with_compatible_server
from tests.test_classroom_quality import OPTIONAL, REQUIRED, _board, _run, _submit, _world
from tests.test_llm_proxy import FakeVendor, _claude, _stack

CLASS_KEY = "sk-ant-test-instructor-key"  # leak-guard:allow — `set_anthropic_key` 의 가짜 키
PLATFORM_KEY = "sk-ant-platform-key-must-not-be-used-0000"  # leak-guard:allow — 가짜 키
HAIKU = "claude-haiku-5-5"


@pytest.fixture(autouse=True)
def _platform(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", PLATFORM_KEY)
    # 플랫폼 하루 상한이 0 이어도 클래스 키 실행은 막히지 않는다(#1036).
    monkeypatch.setenv("AGENT_SCORING_DAILY_LIMIT_USD", "0")


def _patch_class(client, access: str, class_id: int, payload: dict):
    return client.patch(
        f"{CLASSES_URL}/{class_id}", data=payload, content_type="application/json", **auth_header(access)
    )


def _claude_stream(output: dict | None) -> str:
    events = [
        {"type": "system", "subtype": "init", "tools": ["Read", "Grep", "Glob"], "apiKeySource": "ANTHROPIC_API_KEY"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": {}} for n in ("Glob", "Read", "Grep")]}},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "structured_output": output},
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


def _codex_stream(output: dict) -> str:
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "rg -n 테스트", "exit_code": 0, "aggregated_output": ""}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(output, ensure_ascii=False)}},
        {"type": "turn.completed", "usage": {"input_tokens": 500, "output_tokens": 50}},
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


class _Runner:
    """`request_run` 자리. `through_proxy` 면 받은 실행 토큰으로 프록시를 한 번 지나간다(CLI 의 첫 요청처럼)."""

    def __init__(self, stdout: Callable[[], str], *, vendor: FakeVendor | None = None) -> None:
        self.stdout = stdout
        self.vendor = vendor
        self.specs: list[dict] = []
        self.proxy_statuses: list[int] = []

    def __call__(self, spec, repo_zip: bytes, **_kwargs):
        self.specs.append(dict(spec))
        if self.vendor is not None:

            async def body(client: TestClient) -> None:
                response = await client.post("/v1/messages", **_claude(spec["run_token"], model=spec["model"]))
                await response.read()
                self.proxy_statuses.append(response.status)

            async def main() -> None:
                async with _stack(self.vendor) as client:
                    await body(client)

            async_to_sync(main)()
        return {
            "run_id": f"run-{len(self.specs)}",
            "vendor": spec["vendor"],
            "cli_version": "fake",
            "exit_code": 0,
            "timed_out": False,
            "duration_seconds": 1.0,
            "repo_root_prefix": "",
            "stdout": self.stdout(),
            "stdout_truncated": False,
            "stderr_tail": "",
        }


def _claude_key_class(client, monkeypatch, *, method: str | None = "agent"):
    _anthropic_vendor(monkeypatch)
    owner = login(client, uid="owner")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"], with_key=False)
    assert set_anthropic_key(client, owner["access"], class_id).status_code == 200
    if method is not None:
        response = _patch_class(client, owner["access"], class_id, {"scoring_method": method})
        assert response.status_code == 200, response.content
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    return owner, participant, class_id, problem


# --- 설정 ---------------------------------------------------------------------------------------


def test_methods_default_to_single_and_agent_is_open_for_a_key_connection(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    body = get_class(client, owner["access"], class_id)

    assert (body["scoring_method"], body["quality_method"]) == ("single", "single")
    assert body["grading_method_options"] == [
        {"value": "single", "selectable": True, "unavailable_reason": None},
        {"value": "agent", "selectable": True, "unavailable_reason": None},
    ]
    saved = _patch_class(client, owner["access"], class_id, {"scoring_method": "agent", "quality_method": "agent"})
    assert saved.status_code == 200, saved.content
    assert (saved.json()["scoring_method"], saved.json()["quality_method"]) == ("agent", "agent")


def test_a_compatible_server_class_cannot_pick_agent(client, db, monkeypatch):
    _fake, instructor, class_id, saved = _class_with_compatible_server(client, monkeypatch, model_ids=["llama-3"])

    assert saved["grading_method_options"][1] == {
        "value": "agent",
        "selectable": False,
        "unavailable_reason": "compatible_server",
    }
    for field in ("scoring_method", "quality_method"):
        response = _patch_class(client, instructor["access"], class_id, {field: "agent"})
        assert response.status_code == 422, response.content
        assert "compatible_server" in response.json()["detail"]
    assert get_class(client, instructor["access"], class_id)["scoring_method"] == "single"


# --- 채점 ---------------------------------------------------------------------------------------


@override_settings(CLASSROOM_SCORING_ADAPTER_MODE=REAL_SCORING_ADAPTER)
def test_agent_scoring_of_a_claude_key_class_uses_the_class_key_through_the_proxy(client, db, monkeypatch):
    owner, participant, class_id, problem = _claude_key_class(client, monkeypatch)
    calls = _anthropic_vendor(monkeypatch, post=lambda body: pytest.fail("한 번 호출 길로 나갔다"))
    vendor = FakeVendor()
    verdicts = {"verdicts": [{"requirement_id": problem.item_id, "met": True, "reason": "있다.", "evidence": ["app.py:1"]}]}
    runner = _Runner(lambda: _claude_stream(verdicts), vendor=vendor)
    monkeypatch.setattr(agent_scoring, "request_run", runner)

    submit_repository(client, participant["access"], class_id, problem.id)
    run_scan(client)

    # 프록시를 지났고, 벤더가 받은 키는 그 클래스의 키다 — 플랫폼 키가 아니다. 플랫폼 하루 상한(0)에 막히지 않았다.
    assert runner.proxy_statuses == [200]
    (_path, headers, sent), = vendor.requests
    assert headers["x-api-key"] == CLASS_KEY
    assert sent["model"] == HAIKU
    assert [c for c in calls if c[0] == "POST"] == []
    # 실행기는 실행 토큰만 받았다.
    (spec,) = runner.specs
    assert (spec["vendor"], spec["model"]) == ("anthropic", HAIKU)
    assert spec["run_token"].startswith("cmrt_")
    token = AgentRunToken.objects.get()
    assert token.key_class_id == class_id
    # 클래스 키 실행의 비용은 플랫폼 하루 합계에 들어가지 않고 그 클래스 몫으로 따로 센다.
    assert token.spent_usd > 0
    assert spent_today_usd() == 0
    assert spent_today_usd(key_class_id=class_id) == token.spent_usd
    # 판정이 그대로 점수가 되고, 실행 기록이 남는다.
    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["status"] == "scored", attempt
    score = ClassroomScore.objects.get()
    assert score.model_version == f"agent:anthropic:{HAIKU}"
    assert "app.py:1" in score.reasoning[0]["reasoning"]
    run = AgentRun.objects.get()
    assert (run.purpose, run.outcome, run.record["key_source"]) == ("scoring", AgentRun.Outcome.ACCEPTED, "class")
    for text in (json.dumps(spec), json.dumps(run.record), score.prompt):
        assert CLASS_KEY not in text
        assert PLATFORM_KEY not in text
    assert get_class(client, owner["access"], class_id)["token_usage_total"] > 0


def test_single_stays_the_default_path(client, db, monkeypatch):
    _owner, participant, class_id, problem = _claude_key_class(client, monkeypatch, method=None)
    monkeypatch.setattr(agent_scoring, "request_run", lambda *a, **k: pytest.fail("에이전트를 불렀다"))

    submit_repository(client, participant["access"], class_id, problem.id)
    run_scan(client)

    assert ClassroomScore.objects.count() == 1
    assert not AgentRun.objects.exists()


def test_held_agent_scoring_is_not_a_failure_and_leaves_the_queue(client, db, monkeypatch):
    _owner, participant, class_id, problem = _claude_key_class(client, monkeypatch)
    # 근거가 박제본에 없다 — 두 번 다 받아들이는 조건을 어긴다.
    bad = {"verdicts": [{"requirement_id": problem.item_id, "met": True, "reason": "있다.", "evidence": ["nope.py:9"]}]}
    runner = _Runner(lambda: _claude_stream(bad))
    monkeypatch.setattr(agent_scoring, "request_run", runner)

    submit_repository(client, participant["access"], class_id, problem.id)
    run_scan(client)
    run_scan(client)

    assert len(runner.specs) == agent_scoring.MAX_ATTEMPTS  # 다음 스캔이 다시 돌리지 않는다
    assert not ClassroomScore.objects.exists()  # 0% 로 굳히지 않는다
    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["status"] == "pending"
    run = AgentRun.objects.get()
    assert (run.purpose, run.outcome) == ("scoring", AgentRun.Outcome.HELD)
    assert any("evidence" in r or "근거" in r for r in run.reasons), run.reasons


# --- 완성도 검사 -------------------------------------------------------------------------------


def test_agent_quality_check_reads_the_snapshot_with_the_class_key_and_records_the_run(client, db, monkeypatch):
    world = _world(client)
    instructor = world["instructor"]["access"]
    response = _patch_class(client, instructor, world["class_id"], {"quality_method": "agent"})
    assert response.status_code == 200, response.content
    _submit(client, world, "p-a", f"# {REQUIRED}\n# {OPTIONAL}\n")
    required_id, optional_id = world["item_ids"]
    scores = {
        "scores": [
            {"requirement_id": required_id, "score": 5, "reasoning": "있다.", "evidence": ["main.py:1"]},
            {"requirement_id": optional_id, "score": 0, "reasoning": "없다.", "evidence": []},
        ]
    }
    runner = _Runner(lambda: _codex_stream(scores))
    monkeypatch.setattr(agent_scoring, "request_run", runner)

    assert _run(client, world) == {"queued_count": 1}

    (spec,) = runner.specs
    assert spec["vendor"] == "openai"
    assert AgentRunToken.objects.get().key_class_id == world["class_id"]
    [row] = _board(client, world)["rows"]
    assert [i["score"] for i in row["items"]] == [5, 0]
    assert "main.py:1" in row["items"][0]["reasoning"]
    run = AgentRun.objects.get()
    assert (run.purpose, run.outcome, run.record["key_source"]) == ("quality", AgentRun.Outcome.ACCEPTED, "class")
