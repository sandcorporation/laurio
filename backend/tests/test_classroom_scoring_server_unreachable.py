"""호환 서버에 닿지 않으면 채점을 멈추고 소유자에게 알린다 (#603, ADR-0058).

강사의 호환 서버가 꺼졌거나 이름이 풀리지 않거나 인증서가 깨졌다면 그것은 소유자의 서버
문제이지 참여자 시도의 결함이 아니다. #601 까지는 이것이 보통 일시 실패로 세여 다섯 번이면
시도가 자동 미달됐다. 크레딧 소진(ADR-0057)과 같은 모양으로 멈춘다 — 실패 시도로 세지 않고,
채점 대기 사유 「키」, 소유자에게 상태 전이마다 한 번 알림, `QUOTA_RECHECK_INTERVAL` 마다 대기
시도 하나로 다시 쳐 보고, 소유자가 연결을 다시 저장하면 그 자리에서 풀린다.

**닿았는데** 늦거나(읽기 타임아웃) 몸통이 깨진 것은 서버가 받은 요청에 제대로 답하지 못한
것이라 지금처럼 실패 시도로 센다(채점은 반드시 끝난다, ADR-0031). 401·403 은 키 거부처럼
연결을 「거부됨」으로 둔다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from classroom import scoring as classroom_scoring
from core.models import ClockOverride
from core.safe_outbound import OutboundReason
from notifications.models import CLASSROOM_NOTIFICATION_TYPES, NotificationType
from tests.classroom_scenarios import (
    FakeCompatibleServer,
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
    roster_grid,
    run_scan,
    set_compatible_server,
    submit_repository,
)

ME_URL = "/api/notifications/me"
#: 다른 시험 파일의 서버와 다른 주소 — 모델 목록 캐시가 연결(주소·인증 값)로 찾는다.
SERVER_URL = "https://scoring.example.org/v1"
KIND = NotificationType.CLASSROOM_SCORING_SERVER_UNREACHABLE


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


def _after_intervals(start, n: int):
    return start + n * (classroom_scoring.QUOTA_RECHECK_INTERVAL + timedelta(seconds=1))


def _setup(client, monkeypatch, *, submissions: int = 1):
    """닿는 서버로 저장해 두고 시도를 낸 뒤, 그 서버가 닿지 않게 된다."""

    fake = FakeCompatibleServer(model_ids=["llama-3.1-8b-instruct"]).install(monkeypatch)
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"], with_key=False)
    set_compatible_server(client, owner["access"], class_id, SERVER_URL)
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    problem = create_open_problem(client, owner["access"], class_id)
    fake.verdicts = openai_success_body(problem.item_id)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    for n in range(submissions):
        submit_repository(
            client, participant["access"], class_id, problem.id, f"https://github.com/octocat/hello-world-{n}"
        )
    fake.refuse = OutboundReason.UNREACHABLE
    return fake, {"owner": owner, "co": co, "participant": participant, "class_id": class_id, "problem": problem}


def _attempts(client, ctx) -> list[dict]:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["submissions"]


def _scoring_calls(fake) -> int:
    return sum(1 for r in fake.requests if r["method"] == "POST")


def _notification_types(client, access: str) -> list[str]:
    response = client.get(f"{ME_URL}?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return [row["notification_type"] for row in response.json()["items"]]


def _unreachable(client, ctx) -> bool:
    return get_class(client, ctx["owner"]["access"], ctx["class_id"])["scoring_server_unreachable"]


# --- 멈춘다 ---------------------------------------------------------------------


def test_an_unreachable_server_never_turns_into_an_automatic_fail_and_waits_on_the_key(
    client, monkeypatch, start
):
    _, ctx = _setup(client, monkeypatch)

    # 실패 한도(5회)의 두 배를, 다시 확인 간격을 넘겨 가며 돌린다.
    for n in range(2 * classroom_scoring.SCORING_FAILURE_LIMIT):
        _set_now(_after_intervals(start, n))
        run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "pending"
    assert attempt["pending_reason"] == "no_api_key"
    assert _unreachable(client, ctx) is True


@pytest.mark.parametrize(
    "reason",
    [
        OutboundReason.DNS_FAILED,
        OutboundReason.CERTIFICATE,
        OutboundReason.NOT_PUBLIC,
        OutboundReason.REDIRECT,
    ],
)
def test_every_way_of_not_reaching_the_server_pauses_the_same(client, monkeypatch, start, reason):
    fake, ctx = _setup(client, monkeypatch)
    fake.refuse = reason

    run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["pending_reason"] == "no_api_key"
    assert _unreachable(client, ctx) is True


def test_other_waiting_attempts_of_the_class_do_not_call_the_server_meanwhile(client, monkeypatch, start):
    fake, _ = _setup(client, monkeypatch, submissions=3)

    run_scan(client)
    _set_now(start + classroom_scoring.QUOTA_RECHECK_INTERVAL - timedelta(seconds=1))
    run_scan(client)

    assert _scoring_calls(fake) == 1


def test_instructor_screens_show_the_pause_as_needing_setup(client, monkeypatch, start):
    _, ctx = _setup(client, monkeypatch)

    run_scan(client)

    grid = roster_grid(client, ctx["owner"]["access"], ctx["class_id"])
    member = next(m for m in grid["members"] if not m["is_instructor"])
    [cell] = [c for c in member["cells"] if c["problem_id"] == ctx["problem"].id]
    assert cell["status"] == "needs_setup"
    assert get_class(client, ctx["owner"]["access"], ctx["class_id"])["scoring_quota_exhausted"] is False


# --- 소유자에게 전이마다 한 번 알린다 ----------------------------------------------


def test_only_the_owner_is_told_once_however_many_attempts_and_rechecks(client, monkeypatch, start):
    _, ctx = _setup(client, monkeypatch, submissions=2)

    for n in range(3):
        _set_now(_after_intervals(start, n))
        run_scan(client)

    assert KIND in CLASSROOM_NOTIFICATION_TYPES
    assert _notification_types(client, ctx["owner"]["access"]).count(KIND) == 1
    assert KIND not in _notification_types(client, ctx["co"]["access"])
    assert KIND not in _notification_types(client, ctx["participant"]["access"])


def test_going_down_again_after_recovering_tells_the_owner_again(client, monkeypatch, start):
    fake, ctx = _setup(client, monkeypatch)
    run_scan(client)

    fake.refuse = None
    set_compatible_server(client, ctx["owner"]["access"], ctx["class_id"], SERVER_URL)
    fake.refuse = OutboundReason.UNREACHABLE
    submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id,
        "https://github.com/octocat/after-restart",
    )
    run_scan(client)

    assert _notification_types(client, ctx["owner"]["access"]).count(KIND) == 2


# --- 서버가 돌아오면 이어진다 -------------------------------------------------------


def test_saving_the_server_again_resumes_scoring_at_once(client, monkeypatch, start):
    fake, ctx = _setup(client, monkeypatch, submissions=2)
    run_scan(client)

    fake.refuse = None
    set_compatible_server(client, ctx["owner"]["access"], ctx["class_id"], SERVER_URL)
    assert _unreachable(client, ctx) is False
    run_scan(client)

    assert [a["status"] for a in _attempts(client, ctx)] == ["scored", "scored"]


def test_a_recheck_after_the_interval_resumes_the_waiting_attempts_once_the_server_is_back(
    client, monkeypatch, start
):
    fake, ctx = _setup(client, monkeypatch, submissions=3)
    run_scan(client)

    fake.refuse = None
    _set_now(_after_intervals(start, 1))
    run_scan(client)

    assert [a["status"] for a in _attempts(client, ctx)] == ["scored", "scored", "scored"]
    assert _unreachable(client, ctx) is False


def test_a_recheck_that_still_cannot_reach_spends_one_call_and_waits_another_interval(
    client, monkeypatch, start
):
    fake, _ = _setup(client, monkeypatch, submissions=3)
    run_scan(client)

    recheck = _after_intervals(start, 1)
    _set_now(recheck)
    run_scan(client)
    _set_now(recheck + classroom_scoring.QUOTA_RECHECK_INTERVAL - timedelta(seconds=1))
    run_scan(client)

    assert _scoring_calls(fake) == 2


# --- 닿았다면 다르다 ----------------------------------------------------------------


def test_a_server_that_is_reached_but_answers_too_late_counts_as_a_failed_attempt(client, monkeypatch, start):
    fake, ctx = _setup(client, monkeypatch)
    fake.refuse = OutboundReason.RESPONSE_FAILED

    for _ in range(classroom_scoring.SCORING_FAILURE_LIMIT):
        run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "scored"  # 실패 한도에 닿아 자동 미달
    assert _unreachable(client, ctx) is False
    assert KIND not in _notification_types(client, ctx["owner"]["access"])


def test_a_server_that_answers_a_broken_body_counts_as_a_failed_attempt(client, monkeypatch, start):
    fake, ctx = _setup(client, monkeypatch)
    fake.refuse = None
    fake.verdicts = {"choices": "깨진 몸통"}

    run_scan(client)

    [attempt] = _attempts(client, ctx)
    assert attempt["status"] == "scored"  # 영구 실패라 한 번에 자동 미달
    assert _unreachable(client, ctx) is False
    assert KIND not in _notification_types(client, ctx["owner"]["access"])


def test_a_server_that_refuses_the_auth_value_rejects_the_connection(client, monkeypatch, start):
    fake, ctx = _setup(client, monkeypatch)
    fake.refuse = None
    fake.accepted_auth = "another-token"

    run_scan(client)

    assert get_class(client, ctx["owner"]["access"], ctx["class_id"])["openai_key_status"] == "rejected"
    assert _unreachable(client, ctx) is False
    [attempt] = _attempts(client, ctx)
    assert attempt["pending_reason"] == "no_api_key"
