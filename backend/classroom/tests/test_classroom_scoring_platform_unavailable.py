"""#1318: 강의실 채점이 플랫폼 탓으로 실패하면 학생 실패로 세지 않는다 — 클래스를 멈추고, 강사에게 한 번, 운영에 바로.

에이전트 실행기(`agent-grader`)에 닿지 못한 것(`AgentGraderError` — 연결 실패·시간 초과·503 이 아닌 HTTP·깨진 응답)은
제출 탓이 아니다. 예전에는 일반 실패 갈래로 가서 다섯 번이면 자동 미달이 됐고, 강사도 운영도 아무 신호를 받지 못했다.
크레딧 소진·서버 연결 불가(#586, #603)와 같은 모양으로 멈춘다: 시도 기록 없음, 다시 확인 간격마다 한 건만 다시
쳐 보고, 채점되면 저절로 풀린다. 실패마다 GlitchTip 이벤트 하나와 1분 집계 한 건(운영 경보 입력)을 남긴다.

그 밖의 까닭으로 실패 상한 점수가 찍히면 찍힐 때마다 소유자에게 알린다(문제·제출·까닭 한 줄).

시임은 HTTP(채점 스캔·알림 목록·클래스 응답)다. 실행기 호출(`core.agent_scoring.request_run`)만 가짜로 바꾼다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
import requests
import sentry_sdk
from django.utils import timezone

from classroom import pending_scoring
from classroom import scoring as classroom_scoring
from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt
from classroom.tests.test_classroom_agent_method import _claude_key_class, _claude_stream, _Runner
from core import agent_scoring
from core.models import ClockOverride
from notifications.models import NotificationType
from ops_metrics import alerts
from ops_metrics.store import memory_store
from scoring.agent_runner import AgentGraderBusy, AgentGraderError, RunRejected
from tests.classroom_scenarios import (
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    mine,
    raise_vendor_network_error,
    run_scan,
    submit_repository,
)

ME_URL = "/api/notifications/me"
PAUSED = NotificationType.CLASSROOM_SCORING_PLATFORM_UNAVAILABLE
CAPPED = NotificationType.CLASSROOM_SCORING_FAILURE_CAPPED


@pytest.fixture(autouse=True)
def _clean_metrics():
    memory_store().clear()
    yield
    memory_store().clear()


@pytest.fixture
def start(db):
    moment = timezone.now()
    _set_now(moment)
    return moment


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """GlitchTip 으로 간 이벤트 — 예외와 그때 범위의 지문·태그·문맥."""

    events: list[dict] = []

    def capture(exc, *args, **kwargs):
        scope = sentry_sdk.get_current_scope()
        events.append(
            {
                "exc": exc,
                "fingerprint": list(scope._fingerprint or []),
                "tags": dict(scope._tags),
                "contexts": dict(scope._contexts),
            }
        )

    monkeypatch.setattr(sentry_sdk, "capture_exception", capture)
    return events


def _set_now(moment) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": moment})


def _after_intervals(start, n: int):
    return start + n * (classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1))


class _Down:
    """닿지 않는 실행기 — `request_run` 이 그 자리에서 던질 예외를 고른다. `up` 이면 받아들이는 판정을 준다."""

    def __init__(self, problem, error: Exception) -> None:
        self.error = error
        self.calls = 0
        verdicts = {"verdicts": [{"requirement_id": problem.item_id, "met": True, "reason": "있다.", "evidence": ["app.py:1"]}]}
        self.healthy = _Runner(lambda: _claude_stream(verdicts))
        self.up = False

    def __call__(self, spec, repo_zip: bytes, **kwargs):
        self.calls += 1
        if self.up:
            return self.healthy(spec, repo_zip, **kwargs)
        raise self.error


def _setup(client, monkeypatch, error: Exception, *, submissions: int = 1):
    owner, participant, class_id, problem = _claude_key_class(client, monkeypatch)
    runner = _Down(problem, error)
    monkeypatch.setattr(agent_scoring, "request_run", runner)
    for n in range(submissions):
        submit_repository(client, participant["access"], class_id, problem.id, f"https://github.com/octocat/hello-world-{n}")
    return runner, {"owner": owner, "participant": participant, "class_id": class_id, "problem": problem}


def _notifications(client, access: str) -> list[dict]:
    response = client.get(f"{ME_URL}?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["items"]


def _types(client, access: str) -> list[str]:
    return [row["notification_type"] for row in _notifications(client, access)]


def _attempts(client, ctx) -> list[dict]:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["submissions"]


def _metric_count(moment) -> int:
    now = moment.timestamp()
    return alerts.gather(now).results(15)["grader_unreachable"]


# --- 멈춘다 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        AgentGraderError("URLError"),
        AgentGraderError("TimeoutError"),
        AgentGraderError("HTTP 500 boom"),
        AgentGraderError("JSONDecodeError"),
    ],
    ids=["unreachable", "timeout", "server_error", "bad_response"],
)
def test_an_unreachable_grader_pauses_the_class_without_a_failed_attempt(client, start, monkeypatch, captured, error):
    runner, ctx = _setup(client, monkeypatch, error)

    run_scan(client)

    assert runner.calls == 1
    assert not ClassroomScoringAttempt.objects.exists()
    assert not ClassroomScore.objects.exists()
    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is not None
    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "pending"
    # 강사의 키 문제가 아니다 — 채점 대기 사유(「키」)도, 키 쪽 멈춤 표시도 켜지 않는다.
    assert attempt["pending_reason"] is None
    detail = get_class(client, ctx["owner"]["access"], ctx["class_id"])
    assert detail["scoring_quota_exhausted"] is False and detail["scoring_server_unreachable"] is False
    assert _types(client, ctx["owner"]["access"]) == [PAUSED]
    assert _types(client, ctx["participant"]["access"]) == []
    # 운영: 오류 수집 한 건(지문은 갈래, 제출을 가리키는 값은 빠진다)과 1분 집계 한 건.
    [event] = captured
    assert event["fingerprint"][0] == "agent-grader-unavailable"
    assert event["fingerprint"][1] == {
        "URLError": "unreachable",
        "TimeoutError": "timeout",
        "HTTP 500 boom": "server_error",
        "JSONDecodeError": "bad_response",
    }[str(error)]
    assert "submission_id" not in event["tags"]
    assert "classroom_scoring" not in event["contexts"]
    assert _metric_count(start) == 1


def test_failures_never_turn_into_an_automatic_fail_and_the_owner_is_told_once(client, start, monkeypatch, captured):
    runner, ctx = _setup(client, monkeypatch, AgentGraderError("URLError"), submissions=2)

    for n in range(classroom_scoring.SCORING_FAILURE_LIMIT * 2):
        _set_now(_after_intervals(start, n))
        run_scan(client)
        run_scan(client)

    # 간격마다 한 건만 다시 쳐 봤다 — 시도 기록도 점수도 없고, 알림은 멈춘 순간의 한 번뿐이다.
    assert runner.calls == classroom_scoring.SCORING_FAILURE_LIMIT * 2
    assert not ClassroomScoringAttempt.objects.exists()
    assert not ClassroomScore.objects.exists()
    assert [a["status"] for a in _attempts(client, ctx)] == ["pending", "pending"]
    assert _types(client, ctx["owner"]["access"]) == [PAUSED]
    # 오류 수집은 실패마다 간다(지문이 같아 한 묶음).
    assert len(captured) == runner.calls
    assert {tuple(e["fingerprint"]) for e in captured} == {("agent-grader-unavailable", "unreachable")}


def test_once_the_grader_is_back_the_recheck_scores_and_the_pause_lifts(client, start, monkeypatch, captured):
    runner, ctx = _setup(client, monkeypatch, AgentGraderError("ConnectionRefusedError"), submissions=2)
    run_scan(client)
    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is not None

    runner.up = True
    run_scan(client)  # 간격 전 — 아직 멈춤
    assert runner.calls == 1
    _set_now(_after_intervals(start, 1))
    run_scan(client)  # 다시 확인 한 건이 채점되고 멈춤이 풀린다
    run_scan(client)  # 남은 대기 제출이 채점된다

    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is None
    assert [a["status"] for a in _attempts(client, ctx)] == ["scored", "scored"]
    assert not ClassroomScoringAttempt.objects.exists()
    # 풀릴 때 강사 알림은 없다.
    assert _types(client, ctx["owner"]["access"]) == [PAUSED]


def test_pausing_again_after_recovering_tells_the_owner_again(client, start, monkeypatch, captured):
    runner, ctx = _setup(client, monkeypatch, AgentGraderError("URLError"), submissions=2)
    run_scan(client)
    runner.up = True
    _set_now(_after_intervals(start, 1))
    run_scan(client)
    runner.up = False
    submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id, "https://github.com/octocat/again"
    )
    run_scan(client)

    assert _types(client, ctx["owner"]["access"]) == [PAUSED, PAUSED]


# --- 남기는 갈래 ---------------------------------------------------------------------------------


def test_a_busy_grader_stays_a_rate_limit_and_does_not_pause(client, start, monkeypatch, captured):
    _runner, ctx = _setup(client, monkeypatch, AgentGraderBusy("busy"))

    run_scan(client)

    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is None
    [row] = ClassroomScoringAttempt.objects.all()
    assert row.rate_limited is True
    assert captured == []
    assert PAUSED not in _types(client, ctx["owner"]["access"])


def test_a_rejected_run_stays_held_and_does_not_pause(client, start, monkeypatch, captured):
    _runner, ctx = _setup(client, monkeypatch, RunRejected("too large"))

    run_scan(client)

    assert Class.objects.get(pk=ctx["class_id"]).scoring_platform_unavailable_at is None
    assert not ClassroomScore.objects.exists()
    [row] = ClassroomScoringAttempt.objects.all()
    assert row.error.startswith(pending_scoring.AGENT_SCORING_HOLD_ERROR_PREFIX)
    assert captured == []
    assert _types(client, ctx["owner"]["access"]) == []


# --- 실패 상한 알림 ------------------------------------------------------------------------------


def test_every_failure_capped_score_tells_the_owner_which_attempt_and_why(client, db, monkeypatch):
    owner = login(client, uid="owner")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id, required_labels=["README 가 있다"])
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    first = submit_repository(client, participant["access"], class_id, problem.id)["id"]
    raise_vendor_network_error(monkeypatch, requests.ReadTimeout("read timed out (180)"))

    with force_real_scoring_adapter():
        for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT):
            run_scan(client)
        second = submit_repository(
            client, participant["access"], class_id, problem.id, "https://github.com/octocat/second"
        )["id"]
        for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT):
            run_scan(client)

    capped = [row for row in _notifications(client, owner["access"]) if row["notification_type"] == CAPPED]
    assert sorted(row["context"]["submission_id"] for row in capped) == sorted([first, second])
    for row in capped:
        context = row["context"]
        assert context["class_id"] == class_id
        assert context["problem_id"] == problem.id
        assert context["problem_title"]
        assert context["attempt_number"] in (1, 2)
        assert context["reason"] == "채점 모델이 제한 시간 안에 답하지 않았습니다"
        assert "read timed out" not in context["reason"]
    # 낸 사람에게는 늘 가던 채점 완료 알림만 간다.
    assert CAPPED not in _types(client, participant["access"])


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"rate_limited": True, "error": "429"}, "채점 모델 제공처가 요청 빈도를 거듭 제한했습니다"),
        ({"error": "알 수 없는 채점 모델: 'x'"}, "문제의 채점 모델을 알 수 없습니다"),
        ({"error": "에이전트 실행 토큰을 받지 못했다: unknown"}, "에이전트 채점을 시작하지 못했습니다"),
        ({"error": "저장소가 공개가 아니거나 아직 확인되지 않았다."}, "제출한 소스나 저장소를 읽지 못했습니다"),
        ({"error": "OpenAI 응답 시간 초과"}, "채점 모델이 제한 시간 안에 답하지 않았습니다"),
        ({"error": "400 bad request", "permanent": True}, "채점 모델이 이 요청을 받지 않았습니다"),
        ({"error": "응답에 판정이 없다"}, "채점 모델의 답을 받지 못했거나 읽지 못했습니다"),
    ],
)
def test_the_reason_line_is_a_short_human_summary_of_the_last_attempt(fields, reason):
    attempt = ClassroomScoringAttempt(**{"rate_limited": False, "permanent": False, **fields})
    assert classroom_scoring.failure_cap_reason(attempt) == reason


def test_the_metric_window_reads_the_recorded_failures(db):
    """경보 입력의 단위 — `platform_failures.report` 가 1분 집계에 남긴 수를 경보 검사가 읽는다."""

    from classroom.agent_grading import AgentPlatformUnavailable
    from classroom.platform_failures import report

    moment = datetime(2026, 11, 22, 3, 0, tzinfo=dt_timezone.utc)
    report(AgentPlatformUnavailable("x", kind="unreachable"), product="classroom", model="m")
    assert alerts.gather(timezone.now().timestamp()).results(15)["grader_unreachable"] == 1
    assert alerts.gather(moment.timestamp()).results(15)["grader_unreachable"] == 0
