"""강의실 채점이 fake 이벤트 버스에 `attempt-scored`를 발행한다 (#379, ADR-0046).

핵심 대상: `ClassroomScore`가 생기는 두 경로(정상 채점·실패 상한에 의한 플랫폼
자동 미달) 모두에서 그 시도의 참여자에게만 신호가 간다 — 다른 참여자·내보내진
참여자에게는 가지 않는다. 공모전 채점(`scoring` 앱)은 이 버스를 아예 모른다
(import하지 않는다) — 앱 경계 테스트(`test_app_boundaries.py`)가 그 사실을
구조로 지킨다.
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


def _run_scan(client) -> dict:
    from django.conf import settings

    response = client.post(
        SCAN_URL, content_type="application/json", HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN
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


def test_normal_scoring_publishes_attempt_scored_to_the_submitter_only(client, db):
    """체크리스트 문구가 그대로 통과 판정이 나든 미통과가 나든(FakeClassroomScoringAdapter는
    체크리스트 문구가 소스에 있는지만 본다) — 어느 쪽이든 채점이 끝나면 신호가 간다."""

    ctx = _setup_open_problem_with_participant(client)
    submitted = _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )

    _run_scan(client)

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


def test_other_participants_do_not_receive_the_signal(client, db):
    ctx = _setup_open_problem_with_participant(client)
    other = _login(client, uid="other-participant")
    _join(client, other["access"], _join_code(client, ctx["instructor"]["access"], ctx["class_id"]))

    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )
    _run_scan(client)

    assert FakeEventBus._queues.get(_user_id("other-participant"), []) == []


def test_instructor_does_not_receive_the_signal(client, db):
    """#379 AC "그 참여자에게만" — 강사(제출한 사람이 아니면)도 받지 않는다."""

    ctx = _setup_open_problem_with_participant(client)
    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world",
    )
    _run_scan(client)

    assert FakeEventBus._queues.get(_user_id("instructor-1"), []) == []


def test_expelled_participant_does_not_receive_the_signal(client, db):
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

    _run_scan(client)

    assert FakeEventBus._queues.get(_user_id("participant-1"), []) == []


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def test_platform_failure_path_also_publishes_attempt_scored(client, db, monkeypatch):
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
            _run_scan(client)

        participant_id = _user_id("participant-2")
        events = FakeEventBus._queues.get(participant_id, [])
        assert len(events) == 1
        assert events[0].kind == "attempt-scored"
        assert events[0].payload["submission_id"] == submitted["id"]
