"""강의실이 `attempt-submitted`·`attempt-scored`를 fake 이벤트 버스에 발행한다
(#379·#383, ADR-0046).

핵심 대상: 시도 제출·`ClassroomScore` 생성(정상 채점·실패 상한에 의한 플랫폼
자동 미달) 모두에서 그 시도의 참여자와 그 클래스 강사에게 신호가 간다 — 다른
참여자·다른 클래스 강사에게는 가지 않는다. `attempt-scored`는 참여자가
내보내진 뒤라면 참여자에게는 가지 않되 강사에게는 그대로 간다(#383). 공모전
채점(`scoring` 앱)은 이 버스를 아예 모른다(import하지 않는다) — 앱 경계
테스트(`test_app_boundaries.py`)가 그 사실을 구조로 지킨다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import override_settings

from core.events import FakeEventBus

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _login(client, uid: str, email: str | None = None) -> dict:
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _create_open_problem(client, access: str, class_id: int) -> tuple[int, int]:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert checklist.status_code == 201
    item_id = checklist.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id, item_id


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _submit_repository(client, access: str, class_id: int, problem_id: int, url: str) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url, "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _run_scan(client, capture) -> dict:
    """`capture`는 `django_capture_on_commit_callbacks` 픽스처다 —
    `classroom.events.publish_attempt_scored`가 `transaction.on_commit`으로
    미루는 발행을, 실제 커밋이 없는 pytest 트랜잭션 안에서도 실행되게 한다
    (그 함수의 docstring 참고)."""

    from django.conf import settings

    with capture(execute=True):
        response = client.post(
            SCAN_URL,
            content_type="application/json",
            HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN,
        )
    assert response.status_code == 200, response.content
    return response.json()


def _user_id(uid: str) -> int:
    return get_user_model().objects.get(username=f"kakao:{uid}").id


def _setup_open_problem_with_participant(client, *, participant_uid: str = "participant-1"):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid=participant_uid)
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
    }


def test_normal_scoring_publishes_attempt_scored_to_the_submitter(
    client, db, django_capture_on_commit_callbacks
):
    """체크리스트 문구가 그대로 통과 판정이 나든 미통과가 나든(FakeClassroomScoringAdapter는
    체크리스트 문구가 소스에 있는지만 본다) — 어느 쪽이든 채점이 끝나면 신호가 간다.
    강사도 같은 신호를 받는다(#383) — 그건 아래 별도 테스트가 확인한다."""

    ctx = _setup_open_problem_with_participant(client)
    submitted = _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )

    _run_scan(client, django_capture_on_commit_callbacks)

    participant_id = _user_id("participant-1")
    events = FakeEventBus._queues.get(participant_id, [])
    assert len(events) == 1
    event = events[0]
    assert event.kind == "attempt-scored"
    assert event.recipient_id == participant_id
    assert event.payload == {
        "class_id": ctx["class_id"],
        "problem_id": ctx["problem_id"],
        "submission_id": submitted["id"],
    }


def test_other_participants_do_not_receive_the_signal(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _setup_open_problem_with_participant(client)
    other = _login(client, uid="other-participant")
    _join(
        client, other["access"], _join_code(client, ctx["instructor"]["access"], ctx["class_id"])
    )

    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )
    _run_scan(client, django_capture_on_commit_callbacks)

    assert FakeEventBus._queues.get(_user_id("other-participant"), []) == []


def test_instructor_also_receives_attempt_scored(client, db, django_capture_on_commit_callbacks):
    """#383 AC "attempt-scored 가 그 클래스 강사에게도 발행된다" — #379 시점의
    "그 참여자에게만"을 이 티켓이 넓혔다."""

    ctx = _setup_open_problem_with_participant(client)
    submitted = _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )
    _run_scan(client, django_capture_on_commit_callbacks)

    instructor_id = _user_id("instructor-1")
    events = FakeEventBus._queues.get(instructor_id, [])
    assert len(events) == 1
    event = events[0]
    assert event.kind == "attempt-scored"
    assert event.recipient_id == instructor_id
    assert event.payload == {
        "class_id": ctx["class_id"],
        "problem_id": ctx["problem_id"],
        "submission_id": submitted["id"],
    }


def test_other_class_instructor_does_not_receive_attempt_scored(
    client, db, django_capture_on_commit_callbacks
):
    """#383 AC "다른 클래스 강사에게는 어느 신호도 가지 않는다"."""

    ctx = _setup_open_problem_with_participant(client)
    other_instructor = _login(client, uid="other-instructor")
    _create_class(client, other_instructor["access"], name="다른 클래스")
    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )
    _run_scan(client, django_capture_on_commit_callbacks)

    assert FakeEventBus._queues.get(_user_id("other-instructor"), []) == []


def test_expelled_participant_does_not_receive_the_signal(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _setup_open_problem_with_participant(client)
    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )

    members = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/members", **_auth_header(ctx["instructor"]["access"])
    )
    assert members.status_code == 200
    participant_member_id = next(
        m["id"] for m in members.json() if not m["is_instructor"]
    )
    expel = client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/members/{participant_member_id}/expel",
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert expel.status_code == 200

    _run_scan(client, django_capture_on_commit_callbacks)

    assert FakeEventBus._queues.get(_user_id("participant-1"), []) == []
    # 참여자 몫만 걸러진다 — 강사는 내보내진 뒤에도 그 시도의 채점 결과를
    # 그대로 받는다(#383, 위 docstring "강사는 ... 항상 받는다").
    instructor_events = FakeEventBus._queues.get(_user_id("instructor-1"), [])
    assert len(instructor_events) == 1
    assert instructor_events[0].kind == "attempt-scored"


def test_submission_publishes_attempt_submitted_to_the_submitter_and_the_instructor(
    client, db, django_capture_on_commit_callbacks
):
    """#383 AC "강의실 제출이 커밋되면 attempt-submitted 가 그 참여자와 그
    클래스 강사에게 발행된다" — 채점을 기다리지 않는다, 제출 자체가 신호다."""

    ctx = _setup_open_problem_with_participant(client)
    with django_capture_on_commit_callbacks(execute=True):
        submitted = _submit_repository(
            client,
            ctx["participant"]["access"],
            ctx["class_id"],
            ctx["problem_id"],
            "https://github.com/octocat/hello-world",
        )

    expected_payload = {
        "class_id": ctx["class_id"],
        "problem_id": ctx["problem_id"],
        "submission_id": submitted["id"],
    }

    participant_id = _user_id("participant-1")
    participant_events = FakeEventBus._queues.get(participant_id, [])
    assert len(participant_events) == 1
    assert participant_events[0].kind == "attempt-submitted"
    assert participant_events[0].recipient_id == participant_id
    assert participant_events[0].payload == expected_payload

    instructor_id = _user_id("instructor-1")
    instructor_events = FakeEventBus._queues.get(instructor_id, [])
    assert len(instructor_events) == 1
    assert instructor_events[0].kind == "attempt-submitted"
    assert instructor_events[0].recipient_id == instructor_id
    assert instructor_events[0].payload == expected_payload


def test_attempt_submitted_does_not_reach_other_participants_or_other_class_instructor(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _setup_open_problem_with_participant(client)
    other_participant = _login(client, uid="other-participant")
    _join(
        client,
        other_participant["access"],
        _join_code(client, ctx["instructor"]["access"], ctx["class_id"]),
    )
    other_instructor = _login(client, uid="other-instructor")
    _create_class(client, other_instructor["access"], name="다른 클래스")

    with django_capture_on_commit_callbacks(execute=True):
        _submit_repository(
            client,
            ctx["participant"]["access"],
            ctx["class_id"],
            ctx["problem_id"],
            "https://github.com/octocat/hello-world",
        )

    assert FakeEventBus._queues.get(_user_id("other-participant"), []) == []
    assert FakeEventBus._queues.get(_user_id("other-instructor"), []) == []


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def test_platform_failure_path_also_publishes_attempt_scored(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    """실패 상한(`SCORING_FAILURE_LIMIT=5`)에 도달해 `_finalize_platform_failure`가
    직접 `ClassroomScore`를 만드는 경로도 같은 신호를 낸다(#379 AC "정상·실패
    상한")."""

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        instructor = _login(client, uid="instructor-2")
        class_id = _create_class(client, instructor["access"], name="실패 테스트")
        _set_key(client, instructor["access"], class_id)
        problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
        participant = _login(client, uid="participant-2")
        _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
        submitted = _submit_repository(
            client,
            participant["access"],
            class_id,
            problem_id,
            "https://github.com/octocat/hello-world",
        )

        monkeypatch.setattr(
            "core.llm_scoring.requests.post",
            lambda *a, **k: _FakeResponse(500, {"error": {"message": "boom"}}),
        )

        for _ in range(5):
            _run_scan(client, django_capture_on_commit_callbacks)

        participant_id = _user_id("participant-2")
        events = FakeEventBus._queues.get(participant_id, [])
        assert len(events) == 1
        assert events[0].kind == "attempt-scored"
        assert events[0].payload["submission_id"] == submitted["id"]


def test_a_failing_bus_does_not_break_scoring(client, db, monkeypatch, django_capture_on_commit_callbacks):
    """발행은 커밋 뒤에 돈다 — 점수는 이미 저장됐다. 버스(Redis)가 죽어 발행이 예외를 내도
    채점이 실패로 기록되거나 스캔이 깨지면 안 된다: 신호는 빠르게 만드는 장치이지 진실의
    출처가 아니고, 화면은 폴링으로 맞춰진다(ADR-0046)."""

    from classroom.models import ClassroomScore

    def _down(self, event):
        raise ConnectionError("event bus is down")

    monkeypatch.setattr(FakeEventBus, "publish", _down)
    ctx = _setup_open_problem_with_participant(client)
    submitted = _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )

    result = _run_scan(client, django_capture_on_commit_callbacks)

    assert result["rows"][0]["status"] == "scored"
    assert ClassroomScore.objects.filter(submission_id=submitted["id"]).exists()


def test_fake_bus_does_not_grow_without_bound_when_nobody_subscribes(db):
    """fake 버스는 테스트용이지만 배포 환경이 값을 모르는 동안(#380 전) staging 도 이것으로
    뜬다 — 구독자가 없는 gunicorn·celery 프로세스에서 신호가 영원히 쌓이면 안 된다."""

    from core.events import Event

    bus = FakeEventBus()
    for i in range(FakeEventBus.MAX_QUEUED_PER_RECIPIENT + 50):
        bus.publish(Event(kind="attempt-scored", recipient_id=7, payload={"submission_id": i}))

    queued = FakeEventBus._queues[7]
    assert len(queued) == FakeEventBus.MAX_QUEUED_PER_RECIPIENT
    assert queued[-1].payload == {"submission_id": FakeEventBus.MAX_QUEUED_PER_RECIPIENT + 49}
