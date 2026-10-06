"""강사 키의 OpenAI 크레딧이 떨어지면 채점을 멈추고 소유자에게 알린다 (#586).

2026-10-06 클래스 5 에서 429 `insufficient_quota` 가 일반 채점 실패로 기록돼, 참여자가 낸
시도 다섯 건이 실패 한도에 닿아 자동 미달됐다. 크레딧 소진은 키 거부(401, ADR-0045)와 같은
자리 — 채점 대기 사유 「키」 — 로 멈춘다. 실패 시도로 세지 않는다.

풀리는 길은 둘이다. 소유자가 키를 다시 저장하면 그 자리에서 풀리고, 그러지 않아도 스캔이
`QUOTA_RECHECK_INTERVAL`(10분)마다 대기 시도 하나로 다시 쳐 본다 — 키 자체는 멀쩡해서
소유자가 다시 저장할 까닭을 모를 수 있다.

일시적 요청 빈도 제한(429 `rate_limit_exceeded`)은 크레딧과 다르다 — 다시 시도하되 실패
한도에 세지 않는다. 다만 첫 빈도 제한에서 `RATE_LIMIT_GRACE`(1시간)가 지나면 그 뒤의 것은
보통 실패로 센다(채점은 반드시 끝난다, ADR-0031).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from classroom import scoring as classroom_scoring
from core.models import ClockOverride
from notifications.models import CLASSROOM_NOTIFICATION_TYPES, NotificationType
from tests.classroom_scenarios import (
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    mine,
    openai_success_body,
    respond_to_models_endpoint,
    respond_with_quota_exhausted,
    respond_with_rate_limit,
    respond_with_transient_failure,
    roster_grid,
    run_scan,
    set_key,
    submit_repository,
    track_vendor_calls,
)

ME_URL = "/api/notifications/me"


@pytest.fixture(autouse=True)
def _real_adapter():
    with force_real_scoring_adapter():
        yield


@pytest.fixture
def start(db):
    moment = timezone.now()
    _set_now(moment)
    return moment


def _set_now(moment) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": moment})


def _setup(client, *, submissions: int = 1):
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    problem = create_open_problem(client, owner["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    for n in range(submissions):
        submit_repository(
            client,
            participant["access"],
            class_id,
            problem.id,
            f"https://github.com/octocat/hello-world-{n}",
        )
    return {"owner": owner, "co": co, "participant": participant, "class_id": class_id, "problem": problem}


def _attempts(client, ctx) -> list[dict]:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["submissions"]


def _notification_types(client, access: str) -> list[str]:
    response = client.get(f"{ME_URL}?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return [row["notification_type"] for row in response.json()["items"]]


def _respond_with_success(monkeypatch, ctx) -> list:
    return track_vendor_calls(monkeypatch, body=openai_success_body(ctx["problem"].item_id))


# --- 멈춘다 ---------------------------------------------------------------------


def test_exhausted_credit_never_turns_into_an_automatic_fail_and_waits_on_the_key(
    client, monkeypatch, start
):
    ctx = _setup(client)
    respond_with_quota_exhausted(monkeypatch)

    # 실패 한도(5회)의 두 배를, 다시 확인 간격을 넘겨 가며 돌린다.
    for n in range(10):
        _set_now(start + n * (classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1)))
        run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "pending"
    assert attempt["pending_reason"] == "no_api_key"


def test_other_waiting_attempts_of_the_class_do_not_call_the_vendor_meanwhile(
    client, monkeypatch, start
):
    _setup(client, submissions=3)
    calls = respond_with_quota_exhausted(monkeypatch)

    run_scan(client)
    _set_now(start + classroom_scoring.QUOTA_RECHECK_INTERVAL - timedelta(seconds=1))
    run_scan(client)

    assert len(calls) == 1


def test_instructor_screens_show_the_pause_as_needing_setup(client, monkeypatch, start):
    ctx = _setup(client)
    respond_with_quota_exhausted(monkeypatch)

    run_scan(client)

    assert get_class(client, ctx["owner"]["access"], ctx["class_id"])["scoring_quota_exhausted"] is True
    grid = roster_grid(client, ctx["owner"]["access"], ctx["class_id"])
    member = next(m for m in grid["members"] if not m["is_instructor"])
    [cell] = [c for c in member["cells"] if c["problem_id"] == ctx["problem"].id]
    assert cell["status"] == "needs_setup"


# --- 소유자에게 한 번 알린다 ------------------------------------------------------


def test_only_the_owner_is_told_once_however_many_attempts_and_rechecks(client, monkeypatch, start):
    ctx = _setup(client, submissions=2)
    respond_with_quota_exhausted(monkeypatch)

    for n in range(3):
        _set_now(start + n * (classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1)))
        run_scan(client)

    kind = NotificationType.CLASSROOM_SCORING_QUOTA_EXHAUSTED
    assert kind in CLASSROOM_NOTIFICATION_TYPES
    assert _notification_types(client, ctx["owner"]["access"]).count(kind) == 1
    assert kind not in _notification_types(client, ctx["co"]["access"])
    assert kind not in _notification_types(client, ctx["participant"]["access"])


def test_running_dry_again_after_recovering_tells_the_owner_again(client, monkeypatch, start):
    ctx = _setup(client)
    respond_with_quota_exhausted(monkeypatch)
    run_scan(client)

    respond_to_models_endpoint(monkeypatch)
    set_key(client, ctx["owner"]["access"], ctx["class_id"])
    submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id,
        "https://github.com/octocat/after-recharge",
    )
    run_scan(client)

    kind = NotificationType.CLASSROOM_SCORING_QUOTA_EXHAUSTED
    assert _notification_types(client, ctx["owner"]["access"]).count(kind) == 2


# --- 충전하면 이어진다 ------------------------------------------------------------


def test_saving_the_key_again_resumes_scoring_at_once(client, monkeypatch, start):
    ctx = _setup(client, submissions=2)
    respond_with_quota_exhausted(monkeypatch)
    run_scan(client)

    respond_to_models_endpoint(monkeypatch)
    set_key(client, ctx["owner"]["access"], ctx["class_id"])
    assert get_class(client, ctx["owner"]["access"], ctx["class_id"])["scoring_quota_exhausted"] is False
    _respond_with_success(monkeypatch, ctx)
    run_scan(client)

    assert [a["status"] for a in _attempts(client, ctx)] == ["scored", "scored"]


def test_a_recheck_after_the_interval_resumes_the_waiting_attempts_once_credit_is_back(
    client, monkeypatch, start
):
    ctx = _setup(client, submissions=3)
    respond_with_quota_exhausted(monkeypatch)
    run_scan(client)

    _respond_with_success(monkeypatch, ctx)
    _set_now(start + classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1))
    run_scan(client)

    assert [a["status"] for a in _attempts(client, ctx)] == ["scored", "scored", "scored"]
    assert get_class(client, ctx["owner"]["access"], ctx["class_id"])["scoring_quota_exhausted"] is False


def test_a_recheck_that_is_still_dry_spends_one_call_and_waits_another_interval(
    client, monkeypatch, start
):
    _setup(client, submissions=3)
    calls = respond_with_quota_exhausted(monkeypatch)
    run_scan(client)

    recheck = start + classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1)
    _set_now(recheck)
    run_scan(client)
    _set_now(recheck + classroom_scoring.QUOTA_RECHECK_INTERVAL - timedelta(seconds=1))
    run_scan(client)

    assert len(calls) == 2


# --- 빈도 제한은 다르다 ------------------------------------------------------------


def test_rate_limits_are_retried_without_counting_toward_the_failure_limit(client, monkeypatch, start):
    ctx = _setup(client)
    monkeypatch.setattr(classroom_scoring, "RATE_LIMIT_UNCOUNTED_ATTEMPTS", 3)
    calls = respond_with_rate_limit(monkeypatch)

    for _ in range(3):
        run_scan(client)
    respond_with_transient_failure(monkeypatch)
    for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT - 1):
        run_scan(client)

    assert len(calls) == 3
    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "pending"
    assert attempt["pending_reason"] is None
    assert NotificationType.CLASSROOM_SCORING_QUOTA_EXHAUSTED not in _notification_types(
        client, ctx["owner"]["access"]
    )


def test_rate_limits_past_the_uncounted_allowance_count_so_scoring_still_ends(
    client, monkeypatch, start
):
    ctx = _setup(client)
    monkeypatch.setattr(classroom_scoring, "RATE_LIMIT_UNCOUNTED_ATTEMPTS", 2)
    respond_with_rate_limit(monkeypatch)

    for _ in range(2 + classroom_scoring.SCORING_FAILURE_LIMIT):
        run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "scored"
    assert attempt["score"]["model_version"] != "gpt-4o-mini-2024-07-18"
