"""강의실 채점은 상주 grader 가 한다 — 임대로 집고 잠금 없이 벤더를 기다린다 (#584, ADR-0059).

#582(ADR-0056)까지 강의실 채점은 Celery 워커 안에서 **행 잠금 트랜잭션을 쥔 채** 벤더를 기다렸다.
지금은 채점하는 길이 `manage.py grader`(`classroom.grader`) 하나다 — 즉시 채점과 60초 스캔은
「큐에 넣은 시각」(`scoring_queued_at`)만 찍는다. grader 는 ① 조건부 UPDATE 하나로 임대를 집고
② 아무 잠금 없이 (비동기로) 벤더를 기다린 뒤 ③ 임대가 아직 내 것인지 확인하는 짧은 트랜잭션으로
결과를 쓴다. 그래서:

- 두 번 불러도 벤더는 한 번이다 — 임대(`claim_attempt`)가 지킨다.
- 임대가 만료되면 다른 grader 가 다시 줍고, 늦게 도착한 앞 grader 의 결과는 버려진다.
- 전역 상한과 연결(클래스)당 상한이 동시 벤더 호출 수를 막는다.
- SIGTERM(`stop`) 이면 새로 집지 않고 하던 것은 끝낸다.
- 벤더를 기다리는 동안 DB 트랜잭션도 행 잠금도 없다.

pytest 는 `CLASSROOM_GRADER_INLINE` 이다 — 큐에 넣는 자리에서 한 시도를 동기로 채점한다(상주
프로세스가 없는 시험이 결과를 본다). 「grader 가 아직 안 돈다」는 이 스위치를 꺼서 흉내 낸다.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from collections import Counter
from datetime import timedelta

import pytest
import requests
import yaml
from django.conf import settings
from django.db import connection, connections, transaction
from django.test import Client
from django.utils import timezone

from classroom import grader as classroom_grader
from classroom import scoring as classroom_scoring
from classroom.models import ClassroomScore, ClassroomScoringAttempt, ClassroomSubmission
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


def _class_with_open_problem(client, *, uid: str = "instructor-1", participant_uid: str = "participant-1") -> dict:
    instructor = login(client, uid=uid)
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client, instructor["access"], class_id, required_labels=["README 가 있다"]
    )
    participant = login(client, uid=participant_uid)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return {"class_id": class_id, "problem": problem, "participant": participant}


def _status(client, ctx) -> str:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)[
        "submissions"
    ][0]["status"]


def _submit(client, ctx) -> int:
    return submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id
    )["id"]


def _submit_queued(client, ctx) -> int:
    """제출하고 큐에 넣는다(시각만 — 채점은 grader 가 한다). 제출 API 의 `on_commit` 이 하는 일."""

    submission_id = _submit(client, ctx)
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=timezone.now())
    return submission_id


def _set_now(moment) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": moment})


def _row(submission_id: int) -> ClassroomSubmission:
    return ClassroomSubmission.objects.get(pk=submission_id)


@pytest.fixture
def grader_absent(settings):
    """상주 grader 가 아직 돌지 않는다 — 큐에 넣어도 채점되지 않고 시각만 찍힌다."""

    settings.CLASSROOM_GRADER_INLINE = False


# --- 제출 → grader 가 채점한다 ------------------------------------------------


def test_submitting_scores_the_attempt_waiting_three_minutes_for_the_vendor(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    ctx = _class_with_open_problem(client)
    calls: list[dict] = []
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, capture_call=calls)

    with force_real_scoring_adapter(), django_capture_on_commit_callbacks(execute=True):
        _submit(client, ctx)

    assert _status(client, ctx) == "scored"
    [call] = calls
    assert call["timeout"] == 180


def test_the_lease_outlasts_the_vendor_timeout():
    """벤더(180초) < 임대. 임대가 더 짧으면 벤더를 기다리는 사이 다른 grader 가 같은 시도를
    다시 집어 벤더가 두 번 불린다."""

    vendor = classroom_scoring.CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS
    assert vendor == 180
    assert vendor < classroom_scoring.SCORING_LEASE.total_seconds()
    assert classroom_grader.VENDOR_OUTER_TIMEOUT_SECONDS < classroom_scoring.SCORING_LEASE.total_seconds()


def test_submitting_only_stamps_the_queue_when_no_grader_runs(
    client, db, grader_absent, django_capture_on_commit_callbacks
):
    ctx = _class_with_open_problem(client)
    with django_capture_on_commit_callbacks(execute=True):
        submission_id = _submit(client, ctx)

    assert _row(submission_id).scoring_queued_at is not None
    assert _status(client, ctx) == "pending"


# --- 스캔은 큐에 넣기만 한다 -------------------------------------------------


def test_scan_queues_a_pending_attempt_once_and_does_not_queue_it_again(client, db, grader_absent):
    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)

    first = run_scan(client)
    second = run_scan(client)

    assert first["rows"] == [{"submission_id": submission_id, "status": "queued"}]
    assert second["count"] == 0
    assert _status(client, ctx) == "pending"


def test_immediate_scoring_stamps_the_queue_so_the_scan_does_not_queue_it_too(
    client, db, grader_absent, django_capture_on_commit_callbacks
):
    ctx = _class_with_open_problem(client)
    with django_capture_on_commit_callbacks(execute=True):
        _submit(client, ctx)

    assert run_scan(client)["count"] == 0


def test_a_failed_attempt_is_queued_again_on_the_next_scan(client, db, monkeypatch):
    """처리를 마치면(실패로 끝나도) 큐 시각과 임대를 비운다 — 실패한 시도는 다음 tick 에 다시
    시도된다."""

    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)
    raise_vendor_network_error(monkeypatch, requests.ReadTimeout("read timed out"))

    with force_real_scoring_adapter():
        first = run_scan(client)
        second = run_scan(client)

    assert first["count"] == 1
    assert second["count"] == 1
    assert ClassroomScoringAttempt.objects.count() == 2
    row = _row(submission_id)
    assert row.scoring_queued_at is None and row.scoring_lease_owner == ""


# --- 임대 ----------------------------------------------------------------------


def test_claim_is_taken_once_and_taken_again_only_after_the_lease_expires(client, db, grader_absent):
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)
    now = timezone.now()

    assert classroom_scoring.claim_attempt(submission_id, owner="grader-a", as_of=now)
    assert not classroom_scoring.claim_attempt(submission_id, owner="grader-b", as_of=now)
    almost = now + classroom_scoring.SCORING_LEASE - timedelta(seconds=1)
    assert not classroom_scoring.claim_attempt(submission_id, owner="grader-b", as_of=almost)

    after = now + classroom_scoring.SCORING_LEASE + timedelta(seconds=1)
    assert classroom_scoring.claim_attempt(submission_id, owner="grader-b", as_of=after)
    assert _row(submission_id).scoring_lease_owner == "grader-b"


def test_an_attempt_that_is_not_queued_or_already_scored_cannot_be_claimed(client, db, grader_absent):
    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=None)
    assert not classroom_scoring.claim_attempt(submission_id, owner="g", as_of=timezone.now())

    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=timezone.now())
    classroom_grader.grade_inline(submission_id)
    assert ClassroomScore.objects.filter(submission_id=submission_id).count() == 1
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=timezone.now())
    assert not classroom_scoring.claim_attempt(submission_id, owner="g", as_of=timezone.now())


def test_a_dead_graders_attempt_is_picked_again_after_the_lease_and_the_late_result_is_dropped(
    client, db, grader_absent
):
    """grader A 가 임대를 쥐고 벤더를 기다리다 죽거나 너무 늦는다. 임대가 만료되면 B 가 줍고
    채점을 끝낸다 — 뒤늦게 돌아온 A 의 결과는 임대가 내 것이 아니라 버려진다(`lease_lost`)."""

    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)
    start = timezone.now()
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=start)
    assert classroom_scoring.claim_attempt(submission_id, owner="a", as_of=start)
    prepared_a = classroom_scoring.prepare_claimed_attempt(submission_id, owner="a", as_of=start)

    later = start + classroom_scoring.SCORING_LEASE + timedelta(seconds=1)
    assert [sid for sid, _ in classroom_scoring.next_candidates(later, limit=5)] == [submission_id]
    assert classroom_scoring.claim_attempt(submission_id, owner="b", as_of=later)
    prepared_b = classroom_scoring.prepare_claimed_attempt(submission_id, owner="b", as_of=later)

    scored = classroom_scoring.finish_scoring(prepared_b, classroom_scoring.call_vendor_sync(prepared_b))
    late = classroom_scoring.finish_scoring(prepared_a, classroom_scoring.call_vendor_sync(prepared_a))

    assert scored["status"] == "scored"
    assert late["status"] == "lease_lost"
    assert ClassroomScore.objects.filter(submission_id=submission_id).count() == 1


def test_a_late_result_after_another_grader_took_the_lease_writes_nothing(client, db, grader_absent):
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)
    start = timezone.now()
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=start)
    classroom_scoring.claim_attempt(submission_id, owner="a", as_of=start)
    prepared_a = classroom_scoring.prepare_claimed_attempt(submission_id, owner="a", as_of=start)
    classroom_scoring.claim_attempt(
        submission_id, owner="b", as_of=start + classroom_scoring.SCORING_LEASE + timedelta(seconds=1)
    )

    result = classroom_scoring.finish_scoring(prepared_a, classroom_scoring.call_vendor_sync(prepared_a))

    assert result["status"] == "lease_lost"
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0
    assert _row(submission_id).scoring_lease_owner == "b"


# --- 실패 규율은 그대로 -------------------------------------------------------


def test_vendor_timeout_is_a_failed_attempt_and_five_of_them_end_in_a_platform_fail(
    client, db, monkeypatch
):
    ctx = _class_with_open_problem(client)
    _submit(client, ctx)
    raise_vendor_network_error(monkeypatch, requests.ReadTimeout("read timed out (180)"))

    with force_real_scoring_adapter():
        for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT):
            run_scan(client)

    out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    submission = out["submissions"][0]
    assert submission["status"] == "scored"
    assert "자동으로 미달" in submission["score"]["reasoning"][0]["reasoning"]
    assert ClassroomScoringAttempt.objects.count() == classroom_scoring.SCORING_FAILURE_LIMIT


def test_an_unexpected_exception_is_a_failed_attempt_and_releases_the_lease(client, db, monkeypatch):
    """어댑터가 `LLMAdapterError` 가 아닌 예외를 던져도 실패한 시도로 남고(한도에 닿는다) 임대가
    풀린다 — 임대를 쥔 채 5분을 기다리지 않는다."""

    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)
    raise_vendor_network_error(monkeypatch, RuntimeError("boom"))

    with force_real_scoring_adapter():
        run_scan(client)

    [attempt] = ClassroomScoringAttempt.objects.all()
    assert "RuntimeError" in attempt.error
    assert _status(client, ctx) == "pending"
    row = _row(submission_id)
    assert row.scoring_queued_at is None and row.scoring_lease_owner == ""


# --- 두 번 불러도 한 번만 -----------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_graders_picking_the_same_attempt_call_the_vendor_once(django_db_blocker, monkeypatch, settings):
    """같은 시도를 두 grader(여기서는 두 스레드)가 동시에 집으려 해도 임대를 이긴 쪽만 벤더를
    부른다 — `ClassroomScore` 는 하나다."""

    settings.CLASSROOM_GRADER_INLINE = False
    vendor_calls: list[int] = []
    original_score = FakeClassroomScoringAdapter.score

    def _slow_score(self, scoring_input):
        vendor_calls.append(scoring_input.submission_id)
        time.sleep(0.3)
        return original_score(self, scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score", _slow_score)

    client = Client()
    ctx = _class_with_open_problem(client)
    submission_id = _submit(client, ctx)
    barrier = threading.Barrier(2)
    claims: list[bool] = []

    def worker():
        try:
            barrier.wait()
            result = classroom_grader.grade_inline(submission_id)
            claims.append(result is not None)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(claims) == [False, True]
    assert vendor_calls == [submission_id]
    assert ClassroomScore.objects.filter(submission_id=submission_id).count() == 1


# --- grader 루프 ---------------------------------------------------------------


def _queue_attempts(client, ctx, count: int) -> list[int]:
    return [_submit_queued(client, ctx) for _ in range(count)]


@pytest.mark.django_db(transaction=True)
def test_a_round_scores_what_is_queued(django_db_blocker, settings):
    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    ctx = _class_with_open_problem(client)
    ids = _queue_attempts(client, ctx, 3)

    results = classroom_grader.run_round(global_limit=4, per_connection_limit=2, poll_seconds=0.01)

    assert sorted(r["submission_id"] for r in results) == sorted(ids)
    assert {r["status"] for r in results} == {"scored"}
    assert ClassroomScore.objects.count() == 3
    assert not ClassroomSubmission.objects.filter(scoring_queued_at__isnull=False).exists()


@pytest.mark.django_db(transaction=True)
def test_a_round_does_not_end_when_in_flight_attempts_finish_during_a_pick(django_db_blocker, monkeypatch, settings):
    """#648 — 집기(`pick`)는 시작할 때의 상태(상한에 닿은 클래스·처리 중인 시도)로 후보를 읽는다. 그 DB
    걸음 사이에 하던 채점이 **모두** 끝나면 그 집기는 0을 돌려주고 `_tasks` 도 비어 있다 — 그래도 큐에는
    상한 때문에 빠졌던 시도가 남아 있다. 바퀴는 그때 끝나면 안 된다. CI 의 CPU 경쟁에서 둘이 같은 틱에
    끝나며 나던 흔들림을, 그 둘이 집기 도중에 끝나도록 순서를 고정해 재현한다."""

    settings.CLASSROOM_GRADER_INLINE = False
    gate = asyncio.Event()
    real_score_async = FakeClassroomScoringAdapter.score_async

    async def _gated(self, scoring_input):
        await gate.wait()
        return await real_score_async(self, scoring_input)

    real_pick = classroom_grader.Grader.pick

    async def _pick_while_both_finish(self):
        in_flight_at_start = set(self._tasks)
        started = await real_pick(self)
        if len(in_flight_at_start) == 2 and not gate.is_set():
            gate.set()  # 집기가 상한을 읽은 뒤에 둘 다 끝난다
            await asyncio.wait(in_flight_at_start)
        return started

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score_async", _gated)
    monkeypatch.setattr(classroom_grader.Grader, "pick", _pick_while_both_finish)
    client = Client()
    ctx = _class_with_open_problem(client)
    ids = _queue_attempts(client, ctx, 3)

    results = classroom_grader.run_round(global_limit=4, per_connection_limit=2, poll_seconds=0.01)

    assert sorted(r["submission_id"] for r in results) == sorted(ids)
    assert ClassroomScore.objects.count() == 3


@pytest.fixture
def two_classes_with_queued_attempts(settings):
    """두 클래스(연결 둘)에 시도 4건·2건이 줄 서 있다 — 준비라 픽스처에서 HTTP 로 만든다
    (#701: 시험 본문의 CPU 한도 밖)."""

    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    a = _class_with_open_problem(client, uid="instructor-a", participant_uid="participant-a")
    b = _class_with_open_problem(client, uid="instructor-b", participant_uid="participant-b")
    _queue_attempts(client, a, 4)
    _queue_attempts(client, b, 2)
    return a, b


@pytest.mark.django_db(transaction=True)
def test_concurrency_is_capped_per_connection_and_globally(
    django_db_blocker, monkeypatch, two_classes_with_queued_attempts
):
    a, b = two_classes_with_queued_attempts
    in_flight: Counter = Counter()
    peak: Counter = Counter()
    problem_class: dict[int, int] = {}

    async def _slow(self, scoring_input):
        class_id = problem_class[scoring_input.contest_id]
        in_flight[class_id] += 1
        in_flight["all"] += 1
        peak[class_id] = max(peak[class_id], in_flight[class_id])
        peak["all"] = max(peak["all"], in_flight["all"])
        await asyncio.sleep(0.15)
        in_flight[class_id] -= 1
        in_flight["all"] -= 1
        return self.score(scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score_async", _slow)
    problem_class[a["problem"].id] = a["class_id"]
    problem_class[b["problem"].id] = b["class_id"]

    results = classroom_grader.run_round(global_limit=3, per_connection_limit=2, poll_seconds=0.03)

    assert len(results) == 6 and {r["status"] for r in results} == {"scored"}
    # 상한을 넘지 않는다(정확성) — 그리고 실제로 겹쳐 돈다(병렬성; 부하에 따라 3 에 못 미칠 수 있다).
    assert peak[a["class_id"]] <= 2 and peak[b["class_id"]] <= 2
    assert 2 <= peak["all"] <= 3


@pytest.mark.django_db(transaction=True)
def test_nothing_is_held_while_waiting_for_the_vendor(django_db_blocker, monkeypatch, settings):
    """벤더를 기다리는 동안: 임대는 이미 커밋돼 있고(① 끝), 시도 행에 잠금이 없고, 이 DB 에
    「idle in transaction」 세션이 없다."""

    settings.CLASSROOM_GRADER_INLINE = False
    seen: dict = {}

    def _inspect(submission_id: int) -> None:
        try:
            with transaction.atomic():
                locked = ClassroomSubmission.objects.select_for_update(nowait=True).get(pk=submission_id)
            seen["lease_owner"] = locked.scoring_lease_owner
            seen["lock_free"] = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "select count(*) from pg_stat_activity "
                    "where datname = current_database() and state like 'idle in transaction%%'"
                )
                seen["idle_in_transaction"] = cursor.fetchone()[0]
        finally:
            connections.close_all()

    async def _slow(self, scoring_input):
        thread = threading.Thread(target=_inspect, args=(scoring_input.submission_id,))
        thread.start()
        await asyncio.get_running_loop().run_in_executor(None, thread.join)
        return self.score(scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score_async", _slow)
    client = Client()
    ctx = _class_with_open_problem(client)
    _submit_queued(client, ctx)

    classroom_grader.run_round(poll_seconds=0.01)

    assert seen["lock_free"] is True
    assert seen["lease_owner"] != ""
    assert seen["idle_in_transaction"] == 0
    assert ClassroomScore.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_stopping_lets_the_running_attempts_finish_and_picks_no_new_ones(
    django_db_blocker, monkeypatch, settings
):
    settings.CLASSROOM_GRADER_INLINE = False
    state: dict = {}

    async def _slow(self, scoring_input):
        state["started"].set()
        await asyncio.sleep(0.3)
        return self.score(scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score_async", _slow)
    client = Client()
    ctx = _class_with_open_problem(client)
    first = _submit_queued(client, ctx)

    async def main() -> None:
        state["started"] = asyncio.Event()
        stop = asyncio.Event()
        grader = classroom_grader.Grader(global_limit=1, per_connection_limit=1, poll_seconds=0.02)
        running = asyncio.create_task(grader.run_forever(stop))
        await asyncio.wait_for(state["started"].wait(), timeout=5)
        # 종료 신호 — 이 시각 뒤에 큐에 들어온 시도는 줍지 않는다.
        stop.set()
        await asyncio.get_running_loop().run_in_executor(None, _submit_more)
        await asyncio.wait_for(running, timeout=5)

    def _submit_more() -> None:
        try:
            state["second"] = _submit_queued(Client(), ctx)
        finally:
            connections.close_all()

    asyncio.run(main())

    assert ClassroomScore.objects.filter(submission_id=first).exists()
    assert not ClassroomScore.objects.filter(submission_id=state["second"]).exists()
    assert _row(state["second"]).scoring_queued_at is not None


# --- 배포 구성 -----------------------------------------------------------------


@pytest.mark.parametrize("target", ["prod"])
def test_deployed_compose_runs_the_grader_and_no_scoring_worker(target):
    compose = yaml.safe_load(
        (REPO_ROOT / "docker" / f"compose.{target}.yaml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    grader = services["grader"]

    assert "celery-scoring" not in services
    assert grader["command"] == "python manage.py grader"
    assert grader["image"] == services["backend"]["image"]
    assert grader["mem_limit"] == "1g"  # 상한이 없으면 같은 호스트의 DB 까지 OOM 에 휘말린다
    # 따뜻한 종료가 벤더를 기다리는 채점(임대 시간까지)을 마저 끝낼 시간.
    grace_minutes = int(grader["stop_grace_period"].rstrip("m"))
    assert grace_minutes * 60 >= classroom_scoring.SCORING_LEASE.total_seconds()
    assert "-Q classroom-scoring" not in services["celery-worker"]["command"]


def test_deploy_script_replaces_the_grader_with_the_backend_image():
    deploy = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")
    assert 'backend) echo "backend celery-worker celery-beat events grader" ;;' in deploy
    assert "events celery-scoring" not in deploy  # 서비스 목록에서 빠졌다(고아는 `retire_scoring_worker` 가 걷는다)


# --- 임대가 준비·대기 도중 만료돼도 벤더는 한 번 (#584 점검) ------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_lease_that_expires_while_one_grader_is_still_working_does_not_call_the_vendor_twice(
    django_db_blocker, monkeypatch, settings
):
    """소스 준비(저장소 clone)가 길어 임대(240초)가 만료돼도, 같은 grader 가 자기가 처리 중인 시도를
    다시 집지 않는다 — 후보에서 뺀다. 그리고 벤더를 부르기 직전에 임대를 연장한다."""

    settings.CLASSROOM_GRADER_INLINE = False
    calls: list[int] = []
    original_score = FakeClassroomScoringAdapter.score

    async def _vendor(self, scoring_input):
        calls.append(scoring_input.submission_id)
        await asyncio.sleep(0.4)
        return original_score(self, scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score_async", _vendor)

    real_prepare = classroom_scoring.prepare_claimed_head

    def _slow_prepare(submission_id, *, owner, as_of):
        # 준비하는 사이 시계가 임대보다 멀리 가 버렸다 — 임대는 이미 만료됐다.
        _set_now(as_of + classroom_scoring.SCORING_LEASE + timedelta(seconds=5))
        time.sleep(0.3)
        return real_prepare(submission_id, owner=owner, as_of=as_of)

    monkeypatch.setattr(classroom_scoring, "prepare_claimed_head", _slow_prepare)
    client = Client()
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)

    try:
        results = classroom_grader.run_round(global_limit=4, per_connection_limit=2, poll_seconds=0.02)
    finally:
        ClockOverride.objects.all().delete()  # transaction=True 시험은 롤백되지 않는다 — 시계를 되돌려 둔다.

    assert calls == [submission_id]
    assert [r["status"] for r in results] == ["scored"]


def test_the_lease_is_extended_only_by_its_owner(client, db, grader_absent):
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)
    start = timezone.now()
    classroom_scoring.claim_attempt(submission_id, owner="a", as_of=start)
    later = start + classroom_scoring.SCORING_LEASE + timedelta(seconds=1)
    classroom_scoring.claim_attempt(submission_id, owner="b", as_of=later)

    assert not classroom_scoring.extend_lease(submission_id, owner="a", as_of=later)
    assert classroom_scoring.extend_lease(submission_id, owner="b", as_of=later + timedelta(seconds=100))
    assert _row(submission_id).scoring_lease_until == later + timedelta(seconds=100) + classroom_scoring.SCORING_LEASE


# --- DB 연결은 정확히 하나, 그것도 DB 스레드에서만 (#584 점검) -------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_round_opens_one_database_connection_and_queries_only_on_the_db_thread(
    django_db_blocker, monkeypatch, settings
):
    """동시에 여러 건을 돌려도 DB 연결은 하나만 열리고(스레드 하나가 계속 쥔다), 쿼리는 `grader-db`
    스레드에서만 나간다 — 소스 읽기 풀·이벤트 루프·실시간 신호 풀에서는 0번이다."""

    from django.db.backends.base.base import BaseDatabaseWrapper

    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    a = _class_with_open_problem(client, uid="instructor-a", participant_uid="participant-a")
    b = _class_with_open_problem(client, uid="instructor-b", participant_uid="participant-b")
    _queue_attempts(client, a, 3)
    _queue_attempts(client, b, 2)

    cursors: list[str] = []
    connects: list[str] = []
    real_cursor, real_connect = BaseDatabaseWrapper._cursor, BaseDatabaseWrapper.connect

    def _cursor(self, name=None):
        cursors.append(threading.current_thread().name)
        return real_cursor(self, name)

    def _connect(self):
        connects.append(threading.current_thread().name)
        return real_connect(self)

    monkeypatch.setattr(BaseDatabaseWrapper, "_cursor", _cursor)
    monkeypatch.setattr(BaseDatabaseWrapper, "connect", _connect)

    results = classroom_grader.run_round(global_limit=4, per_connection_limit=2, poll_seconds=0.02)

    assert len(results) == 5 and {r["status"] for r in results} == {"scored"}
    assert cursors, "DB 스레드가 쿼리를 하지 않았다 — 시험이 아무것도 못 본다"
    assert {name.rsplit("_", 1)[0] for name in cursors} == {"grader-db"}
    assert len(connects) == 1 and connects[0].startswith("grader-db")


@pytest.mark.django_db(transaction=True)
def test_the_db_thread_reconnects_once_when_its_connection_died(django_db_blocker, monkeypatch, settings):
    """DB 재시작·풀러 교체 뒤 죽은 연결로 첫 작업이 `OperationalError` 로 실패하면 연결을 닫고 한 번
    다시 한다."""

    from django.db import OperationalError

    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    ctx = _class_with_open_problem(client)
    _queue_attempts(client, ctx, 1)

    real = classroom_scoring.next_candidates
    state = {"failed": 0}

    def _flaky(*args, **kwargs):
        if not state["failed"]:
            state["failed"] = 1
            raise OperationalError("server closed the connection unexpectedly")
        return real(*args, **kwargs)

    monkeypatch.setattr(classroom_scoring, "next_candidates", _flaky)

    results = classroom_grader.run_round(poll_seconds=0.02)

    assert state["failed"] == 1
    assert [r["status"] for r in results] == ["scored"]


# --- 잠긴 행을 기다리지 않는다 (#584 리허설) ---------------------------------------------------


def _hold_row_lock(submission_id: int):
    """다른 연결이 그 시도 행을 잠그고 있다 — 옛 채점 워커가 벤더를 기다리며 쥐는 잠금과 같다
    (`select_for_update`, 부모 행까지). `(스레드, 놓기)` 를 돌려준다."""

    locked, release = threading.Event(), threading.Event()

    def holder():
        try:
            with transaction.atomic():
                ClassroomSubmission.objects.select_for_update().get(pk=submission_id)
                locked.set()
                release.wait(30)
        finally:
            connections.close_all()

    thread = threading.Thread(target=holder)
    thread.start()
    assert locked.wait(5)

    def stop():
        release.set()
        thread.join()

    return stop


@pytest.mark.django_db(transaction=True)
def test_a_round_skips_a_row_another_connection_holds_and_picks_it_up_after(django_db_blocker, settings):
    """옛 워커 같은 다른 연결이 행을 잠그고 있어도 grader 한 바퀴는 그 행을 건너뛰고 나머지를 처리한다 —
    잠금을 기다리며 멈추지 않는다. 잠금이 풀린 뒤 다음 바퀴가 그 행을 처리한다."""

    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    ctx = _class_with_open_problem(client)
    locked_id, other_a, other_b = _queue_attempts(client, ctx, 3)
    release = _hold_row_lock(locked_id)
    try:
        started = time.monotonic()
        results = classroom_grader.run_round(global_limit=4, per_connection_limit=3, poll_seconds=0.02)
        elapsed = time.monotonic() - started
        assert {r["submission_id"] for r in results} == {other_a, other_b}
        assert elapsed < 3, "잠긴 행을 기다리며 멈췄다"
        assert not ClassroomScore.objects.filter(submission_id=locked_id).exists()
        assert _row(locked_id).scoring_lease_owner == ""
    finally:
        release()

    later = classroom_grader.run_round(global_limit=4, per_connection_limit=3, poll_seconds=0.02)
    assert [r["submission_id"] for r in later] == [locked_id]
    assert ClassroomScore.objects.filter(submission_id=locked_id).exists()


@pytest.mark.django_db(transaction=True)
def test_writing_the_result_gives_up_quickly_on_a_locked_row_and_writes_once_it_is_free(
    django_db_blocker, settings
):
    settings.CLASSROOM_GRADER_INLINE = False
    settings.CLASSROOM_GRADER_LOCK_TIMEOUT_MS = 300
    client = Client()
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)
    now = timezone.now()
    assert classroom_scoring.claim_attempt(submission_id, owner="a", as_of=now)
    prepared = classroom_scoring.prepare_claimed_attempt(submission_id, owner="a", as_of=now)
    outcome = classroom_scoring.call_vendor_sync(prepared)

    release = _hold_row_lock(submission_id)
    try:
        started = time.monotonic()
        busy = classroom_scoring.finish_scoring(prepared, outcome)
        extended = classroom_scoring.extend_lease(submission_id, owner="a", as_of=now)
        elapsed = time.monotonic() - started
        assert busy["status"] == "lock_busy" and extended is False
        assert elapsed < 2.5
        assert not ClassroomScore.objects.filter(submission_id=submission_id).exists()
        assert _row(submission_id).scoring_lease_owner == "a"  # 임대는 그대로 내 것이다
    finally:
        release()

    done = classroom_scoring.finish_scoring(prepared, outcome)
    assert done["status"] == "scored"
    assert ClassroomScore.objects.filter(submission_id=submission_id).count() == 1


# --- 배포 스크립트의 순서·장치 (#584 리허설) ---------------------------------------------------


def _deploy_text() -> str:
    return (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")


def test_orphan_scoring_processes_are_retired_before_every_migration_run():
    """옛 채점 워커의 장기 트랜잭션 뒤에 ALTER TABLE 이 줄을 서면 API 가 멈춘다(리허설 174초) —
    겹쳐 바꾸는 길·내렸다 올리는 길 모두, 마이그레이션 실행 앞에서 고아 채점 프로세스를 걷는다."""

    deploy = _deploy_text()
    calls = [m.start() for m in re.finditer(r"if ! run_migrations; then", deploy)]
    assert len(calls) == 2
    for call in calls:
        assert "retire_orphan_scoring" in deploy[max(0, call - 900) : call]
    # 풀러를 바꾸는 길도 내리기 전에 걷는다.
    pooler = deploy.index("풀러를 바꾼다 — 그 전에")
    assert "retire_orphan_scoring" in deploy[pooler : pooler + 200]


def test_retiring_covers_both_scoring_processes_and_clears_the_old_queue():
    deploy = _deploy_text()
    body = deploy[deploy.index("retire_orphan_scoring() {") : deploy.index("# 서비스 이름 → compose 서비스들.")]
    assert "celery-scoring grader" in body  # 둘 다 — 롤백 때는 grader 가 고아다
    assert "config --services" in body  # 지금 compose 에 있는 것은 건드리지 않는다
    assert "docker stop -t 240" in body
    assert "redis-cli -n 0 DEL classroom-scoring" in body


def test_migrations_wait_for_locks_only_briefly_and_retry():
    deploy = _deploy_text()
    body = deploy[deploy.index("run_migrations() {") : deploy.index('log "마이그레이션 끝"')]
    assert "lock_timeout=" in body and "PGOPTIONS" in body
    assert "lock timeout" in body and "MIGRATE_LOCK_RETRIES" in body
    # 풀러는 `options` 시작 매개변수를 거부한다 — 실제 DB 주소로 직접 붙는다.
    assert "printenv pgbouncer POSTGRES_HOST" in body.replace("--entrypoint printenv pgbouncer POSTGRES_HOST", "printenv pgbouncer POSTGRES_HOST")
