"""#1326: 실행기가 모델 호출 프록시(`llm-proxy`)에 닿지 못한 강의실 채점도 플랫폼 탓이다.

실행기 CLI 의 실패는 결과(200)에 담겨 오므로 예전에는 받아들임 검사에서 보류(`AgentRunHeld`)로 갔다 — 멈춤·강사
알림·경보가 없었다. 이제 실행기가 결과에 단 표식(`proxy_unreachable`, 실행 전·실패한 실행 뒤에 프록시에 TCP 로
붙어 본 결과)을 보고 실행기에 닿지 못한 것(#1318)과 같은 길로 보낸다: 시도 기록 없음, 클래스 멈춤, 강사 알림 한 번,
WARNING·GlitchTip(지문 `proxy_unreachable`)·1분 집계 `grader_unreachable` 한 건. 표식이 없는 실패는 지금처럼 보류다.

시임은 HTTP(채점 스캔·알림 목록)다. 실행기 호출(`core.agent_scoring.request_run`)만 실행기가 돌려주는 결과로 바꾼다.
"""

from __future__ import annotations

import json
import logging

import pytest

from classroom import pending_scoring
from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt
from classroom.tests.test_classroom_agent_method import _claude_key_class, _patch_class
from classroom.tests.test_classroom_anthropic_key import _anthropic_vendor
from classroom.tests.test_classroom_quality import REQUIRED, _board, _run, _submit, _world
from classroom.tests.test_classroom_scoring_platform_unavailable import (  # noqa: F401 - fixture 등록
    PAUSED,
    _attempts,
    _clean_metrics,
    _metric_count,
    _types,
    captured,
    start,
)
from core import agent_scoring
from tests.classroom_scenarios import run_scan, set_anthropic_key, submit_repository

#: 프록시에 닿지 못한 Claude Code 가 내는 끝 — 오류 결과, 구조화 출력 없음(재시도 끝에 「Connection error」).
_CONNECTION_ERROR = json.dumps(
    {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "API Error: Connection error."}
)


class _Grader:
    """`request_run` 자리 — 실행기가 돌려주는 결과(200)를 낸다. `failure` 는 실행기가 단 `proxy_unreachable`."""

    def __init__(self, failure: str | None, *, started: bool = True) -> None:
        self.failure = failure
        self.started = started
        self.calls = 0

    def __call__(self, spec, repo_zip: bytes, **_kwargs):
        self.calls += 1
        return {
            "run_id": f"run-{self.calls}",
            "vendor": spec["vendor"],
            "cli_version": "fake",
            # 실행 전에 닿지 못하면 CLI 를 띄우지 않는다(종료 코드 없음·빈 출력), 도중이면 CLI 가 1 로 끝난다.
            "exit_code": 1 if self.started else None,
            "timed_out": False,
            "duration_seconds": 1.0,
            "repo_root_prefix": "",
            "stdout": _CONNECTION_ERROR if self.started else "",
            "stdout_truncated": False,
            "stderr_tail": "",
            "proxy_unreachable": self.failure,
        }


def _setup(client, monkeypatch, grader: _Grader):
    owner, participant, class_id, problem = _claude_key_class(client, monkeypatch)
    monkeypatch.setattr(agent_scoring, "request_run", grader)
    submit_repository(client, participant["access"], class_id, problem.id, "https://github.com/octocat/hello-world")
    return {"owner": owner, "participant": participant, "class_id": class_id, "problem": problem}


@pytest.mark.parametrize(
    ("failure", "started"),
    [
        ("connection_refused", True),
        ("name_resolution", True),
        ("timeout", True),
        ("connection_refused", False),
    ],
    ids=["refused-mid-run", "dns-mid-run", "timeout-mid-run", "refused-before-run"],
)
def test_an_unreachable_proxy_pauses_the_class_like_an_unreachable_grader(
    client, start, monkeypatch, captured, caplog, failure, started
):
    grader = _Grader(failure, started=started)
    ctx = _setup(client, monkeypatch, grader)

    with caplog.at_level(logging.WARNING, logger="classroom.platform_failures"):
        run_scan(client)

    # 다시 돌리지 않는다(같은 자리에 부딪힌다) — 시도 기록·점수 없이 멈춘다.
    assert grader.calls == 1
    assert not ClassroomScoringAttempt.objects.exists()
    assert not ClassroomScore.objects.exists()
    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is not None
    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "pending" and attempt["pending_reason"] is None
    assert _types(client, ctx["owner"]["access"]) == [PAUSED]
    assert _types(client, ctx["participant"]["access"]) == []
    [event] = captured
    assert event["fingerprint"] == ["agent-grader-unavailable", "proxy_unreachable"]
    assert "submission_id" not in event["tags"]
    assert _metric_count(start) == 1
    assert any(r.levelname == "WARNING" and "proxy_unreachable" in r.getMessage() for r in caplog.records)


def test_a_failed_run_with_the_proxy_up_stays_held(client, start, monkeypatch, captured):
    """실행기가 프록시에 닿았다면(표식 없음) CLI 실패는 받아들임 조건 위반 — 지금처럼 보류다."""

    grader = _Grader(None)
    ctx = _setup(client, monkeypatch, grader)

    run_scan(client)

    assert grader.calls == 2  # 받아들임 실패는 한 번 다시 돌린다
    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is None
    [row] = ClassroomScoringAttempt.objects.all()
    assert row.error.startswith(pending_scoring.AGENT_SCORING_HOLD_ERROR_PREFIX)
    assert captured == []
    assert _types(client, ctx["owner"]["access"]) == []


def test_the_quality_check_reports_an_unreachable_proxy_but_does_not_pause(client, start, monkeypatch, captured):
    _anthropic_vendor(monkeypatch)
    world = _world(client, with_key=False)
    instructor = world["instructor"]["access"]
    assert set_anthropic_key(client, instructor, world["class_id"]).status_code == 200
    assert _patch_class(client, instructor, world["class_id"], {"quality_method": "agent"}).status_code == 200
    _submit(client, world, "p-a", f"# {REQUIRED}\n")
    monkeypatch.setattr(agent_scoring, "request_run", _Grader("timeout"))

    assert _run(client, world) == {"queued_count": 1}

    assert _board(client, world)["failed_count"] == 1
    assert Class.objects.get(pk=world["class_id"]).scoring_platform_unavailable_at is None
    assert PAUSED not in _types(client, instructor)
    [event] = captured
    assert event["fingerprint"] == ["agent-grader-unavailable", "proxy_unreachable"]
    assert _metric_count(start) == 1
