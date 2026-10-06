"""강의실 채점은 Celery 워커 안에서 돈다 — 느린 벤더(추론 모델)를 3분까지 기다린다 (#582, ADR-0056).

#581(GlitchTip 오류 87)까지 강의실 채점은 내부 HTTP 요청을 받은 gunicorn 워커 안에서
돌아 벤더 타임아웃이 그 요청 예산(30초)에 묶였다. 지금은 채점하는 길이 Celery 태스크
(`classroom.score_attempt`) 하나다 — 제출 직후의 즉시 채점과 60초 안전망 스캔은 그 태스크를
**큐에 넣기만** 하고, 태스크가 워커 안에서 직접 채점한다. 그래서:

- 벤더 타임아웃은 3분이고, 태스크의 시간 한도(soft·hard)와 「큐에 넣은 시각」의 창(5분)이
  그 바깥을 차례로 감싼다.
- 스캔은 「큐에 넣은 시각」이 5분 안인 시도를 다시 넣지 않는다 — 워커가 죽어 잃은 태스크만
  그 뒤에 다시 줍힌다.
- 같은 시도를 둘이 동시에 집어도 벤더는 한 번만 불린다(`_score_one` 의 행 잠금).

pytest 는 dev·CI 처럼 `CELERY_TASK_ALWAYS_EAGER` 다 — 큐에 넣는 자리에서 태스크가 그대로
돈다. 「잃은 태스크」는 큐에 넣는 순간(`delay`)을 아무 일도 하지 않게 바꿔 흉내 낸다.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest
import requests
import yaml
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import connections
from django.test import Client
from django.utils import timezone

from classroom import scoring as classroom_scoring
from classroom import tasks as classroom_tasks
from classroom.models import ClassroomScore, ClassroomScoringAttempt
from classroom.scoring import FakeClassroomScoringAdapter
from core.models import ClockOverride
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    mine,
    raise_vendor_network_error,
    respond_with_verdict,
    run_scan,
    submit_repository,
)

REPO_ROOT = settings.BASE_DIR.parent


def _class_with_open_problem(client) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client, instructor["access"], class_id, required_labels=["README 가 있다"]
    )
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return {"class_id": class_id, "problem": problem, "participant": participant}


def _status(client, ctx) -> str:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)[
        "submissions"
    ][0]["status"]


def _lose_queued_tasks(monkeypatch) -> list[int]:
    """큐에 넣은 태스크가 아무 데서도 돌지 않는다 — 워커가 받아 들고 죽은 것과 같다."""

    queued: list[int] = []
    monkeypatch.setattr(classroom_tasks.score_attempt, "delay", lambda sid: queued.append(sid))
    return queued


def _set_now(moment) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": moment})


# --- 제출 → 태스크가 채점한다 ------------------------------------------------


def test_submitting_scores_the_attempt_in_the_task_waiting_three_minutes_for_the_vendor(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    ctx = _class_with_open_problem(client)
    calls: list[dict] = []
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, capture_call=calls)

    with force_real_scoring_adapter(), django_capture_on_commit_callbacks(execute=True):
        submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)

    assert _status(client, ctx) == "scored"
    [call] = calls
    assert call["timeout"] == 180


def test_task_time_limits_wrap_the_vendor_timeout_and_the_queue_window_wraps_the_task():
    """벤더(180초) < soft(태스크가 스스로 실패를 남길 기회) < hard(워커가 프로세스를 죽인다)
    < 큐 창(5분 — 그 안에서는 스캔이 다시 넣지 않는다). 순서가 뒤집히면 살아 있는 태스크와
    다시 넣은 태스크가 겹치거나, 실패가 기록되기 전에 프로세스가 죽는다."""

    task = classroom_tasks.score_attempt
    vendor = classroom_scoring.CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS
    assert vendor == 180
    assert vendor < task.soft_time_limit < task.time_limit
    assert task.time_limit < classroom_scoring.SCORING_QUEUE_WINDOW.total_seconds()


def test_scoring_task_goes_to_its_own_queue():
    from config.celery import app

    route = app.amqp.router.route({}, classroom_tasks.score_attempt.name)
    assert route["queue"].name == "classroom-scoring"


# --- 스캔은 큐에 넣기만 한다 -------------------------------------------------


def test_scan_queues_a_pending_attempt_and_does_not_queue_it_again_within_five_minutes(
    client, db, monkeypatch
):
    ctx = _class_with_open_problem(client)
    submitted = submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id
    )
    start = timezone.now()
    _set_now(start)
    queued = _lose_queued_tasks(monkeypatch)

    first = run_scan(client)
    _set_now(start + timedelta(minutes=4, seconds=59))
    second = run_scan(client)

    assert first["rows"] == [{"submission_id": submitted["id"], "status": "queued"}]
    assert second["count"] == 0
    assert queued == [submitted["id"]]
    assert _status(client, ctx) == "pending"


def test_scan_queues_a_lost_task_again_after_five_minutes(client, db, monkeypatch):
    ctx = _class_with_open_problem(client)
    submitted = submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id
    )
    start = timezone.now()
    _set_now(start)
    queued = _lose_queued_tasks(monkeypatch)
    run_scan(client)

    _set_now(start + timedelta(minutes=5, seconds=1))
    again = run_scan(client)

    assert again["count"] == 1
    assert queued == [submitted["id"], submitted["id"]]


def test_immediate_scoring_stamps_the_queue_so_the_scan_does_not_queue_it_too(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    ctx = _class_with_open_problem(client)
    queued = _lose_queued_tasks(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        submitted = submit_repository(
            client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id
        )

    scanned = run_scan(client)

    assert queued == [submitted["id"]]
    assert scanned["count"] == 0


def test_a_failed_attempt_is_queued_again_on_the_next_scan(client, db, monkeypatch):
    """태스크가 처리를 마치면(실패로 끝나도) 큐 시각을 비운다 — 실패한 시도는 5분이 아니라
    다음 tick 에 다시 시도된다(#582 전과 같은 간격)."""

    ctx = _class_with_open_problem(client)
    submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    raise_vendor_network_error(monkeypatch, requests.ReadTimeout("read timed out"))

    with force_real_scoring_adapter():
        first = run_scan(client)
        second = run_scan(client)

    assert first["count"] == 1
    assert second["count"] == 1
    assert ClassroomScoringAttempt.objects.count() == 2


# --- 실패 규율은 그대로 -------------------------------------------------------


def test_vendor_timeout_is_a_failed_attempt_and_five_of_them_end_in_a_platform_fail(
    client, db, monkeypatch
):
    ctx = _class_with_open_problem(client)
    submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    raise_vendor_network_error(monkeypatch, requests.ReadTimeout("read timed out (180)"))

    with force_real_scoring_adapter():
        for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT):
            run_scan(client)

    out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    submission = out["submissions"][0]
    assert submission["status"] == "scored"
    assert "자동으로 미달" in submission["score"]["reasoning"][0]["reasoning"]
    assert ClassroomScoringAttempt.objects.count() == classroom_scoring.SCORING_FAILURE_LIMIT


def test_soft_time_limit_inside_the_vendor_call_is_recorded_as_a_failed_attempt(
    client, db, monkeypatch
):
    """벤더 타임아웃이 어떤 이유로 듣지 않아도 soft 한도가 채점 도중에 예외를 던지고, 그것도
    실패한 시도로 남는다 — 그래야 실패 한도에 닿는다(오류 87 은 기록 없이 죽었다)."""

    ctx = _class_with_open_problem(client)
    submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    raise_vendor_network_error(monkeypatch, SoftTimeLimitExceeded())

    with force_real_scoring_adapter():
        run_scan(client)

    [attempt] = ClassroomScoringAttempt.objects.all()
    assert "SoftTimeLimitExceeded" in attempt.error
    assert _status(client, ctx) == "pending"


# --- 두 번 불러도 한 번만 -----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_tasks_for_the_same_attempt_call_the_vendor_once(django_db_blocker, monkeypatch):
    """즉시 채점 태스크와 스캔이 넣은 태스크(또는 재전달된 같은 태스크)가 정말로 동시에 돌아도
    벤더는 한 번, `ClassroomScore` 는 하나다 — `_score_one` 의 `select_for_update(skip_locked)`."""

    vendor_calls: list[int] = []
    original_score = FakeClassroomScoringAdapter.score

    def _slow_score(self, scoring_input):
        vendor_calls.append(scoring_input.submission_id)
        time.sleep(0.3)
        return original_score(self, scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score", _slow_score)

    with django_db_blocker.unblock():
        client = Client()
        ctx = _class_with_open_problem(client)
        submitted = submit_repository(
            client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id
        )

        barrier = threading.Barrier(2)

        def worker():
            try:
                with django_db_blocker.unblock():
                    barrier.wait()
                    classroom_tasks.score_attempt.apply(args=[submitted["id"]])
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert vendor_calls == [submitted["id"]]
        assert ClassroomScore.objects.filter(submission_id=submitted["id"]).count() == 1


# --- 배포 구성 -----------------------------------------------------------------


@pytest.mark.parametrize("target", ["staging", "prod"])
def test_deployed_compose_runs_a_scoring_worker_and_the_general_worker_does_not_score(target):
    compose = yaml.safe_load(
        (REPO_ROOT / "docker" / f"compose.{target}.yaml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    scoring = services["celery-scoring"]
    general = services["celery-worker"]

    assert "-Q classroom-scoring" in scoring["command"]
    assert "--concurrency 8" in scoring["command"]
    assert "-Q celery" in general["command"]
    assert "classroom-scoring" not in general["command"]
    assert scoring["image"] == services["backend"]["image"]
    # 따뜻한 종료가 채점 중인 태스크(hard 한도까지)를 마저 끝낼 시간.
    grace_minutes = int(scoring["stop_grace_period"].rstrip("m"))
    assert grace_minutes * 60 >= classroom_tasks.score_attempt.time_limit


def test_deploy_script_replaces_the_scoring_worker_with_the_backend_image():
    deploy = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")
    assert 'backend) echo "backend celery-worker celery-beat events celery-scoring" ;;' in deploy
