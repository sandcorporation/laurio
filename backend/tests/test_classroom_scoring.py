"""제출하면 바로 채점에 들어간다 — 시도마다 Score 하나 (#287, CONTEXT.md
「강의실」, ADR-0006/0031/0037/0039).

핵심 대상: 제출 즉시 사람이 더 할 일 없이 채점이 비동기로 시작되고(스캔이
집는다), 시도마다 `ClassroomScore`가 정확히 하나 생기며 다시 채점되지
않는다. 강사 본인의 키와 그 문제의 모델로 친다. 채점이 실패해도 무한히
되돌지 않고 상한(5회) 뒤에는 그 사실이 판정으로 남는다. 키가 없거나
틀렸을 때 참여자가 보는 것이 「고장」으로 읽히지 않는다.

**이 파일은 `OpenAIScoringAdapter` 경로 자체를 검증한다**(HTTP 상태·응답
모양별 분기) — 그래서 모든 테스트가 `CLASSROOM_SCORING_ADAPTER_MODE`를 그
어댑터로 강제한다(#340, ADR-0043). 기본값(fake)이 되는 `FakeClassroomScoringAdapter`
경로는 별도 파일(`test_classroom_scoring_fake_adapter.py`)이 덮는다 —
"결정적이고 네트워크가 없다"는 이 파일의 관심사가 아니다.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from classroom.models import ClassroomScore, ClassroomScoringAttempt, ClassroomSubmission
from notifications.models import Notification, NotificationType
from storage.adapters.fake import FakeStorageAdapter

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


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


def _create_open_problem(client, access: str, class_id: int, submission_format: str = "repository") -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": [submission_format]},
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


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _submit_source(client, access: str, class_id: int, problem_id: int, object_key: str) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": object_key, "content_type": "application/zip", "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _openai_success_body(item_id: int, *, is_met: bool) -> dict:
    return {
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "verdicts": [
                                {
                                    "requirement_id": item_id,
                                    "is_met": is_met,
                                    "reasoning": "판정 근거",
                                }
                            ]
                        }
                    )
                },
            }
        ],
    }


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _setup_submission(client, *, submission_format="repository", with_key=True):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    if with_key:
        _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, submission_format)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


def test_submitting_does_not_score_synchronously(client, db):
    ctx = _setup_submission(client)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    assert mine["submissions"][0]["status"] == "pending"
    assert ClassroomScore.objects.count() == 0


def test_scan_scores_a_submission_with_a_key(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    result = _run_scan(client)

    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "scored"
    assert submission_out["score"]["reasoning"] == [
        {"checklist_item_id": ctx["item_id"], "is_met": True, "reasoning": "판정 근거"}
    ]


def test_scan_skips_a_submission_whose_class_has_no_key(client, db, monkeypatch):
    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: called.append(1) or _FakeResponse(200, {}),
    )
    ctx = _setup_submission(client, with_key=False)

    result = _run_scan(client)

    assert result["count"] == 0
    assert not called
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "pending"


def test_score_is_created_exactly_once_even_if_scanned_twice(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    _run_scan(client)
    second = _run_scan(client)

    assert second["count"] == 0
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1


def test_wrong_key_finalizes_immediately_without_looking_broken(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "Incorrect API key"}}),
    )

    _run_scan(client)

    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.model_version != "gpt-4o-mini-2024-07-18"
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "scored"
    reasoning_text = submission_out["score"]["reasoning"][0]["reasoning"]
    # 「고장」으로 읽히지 않는다(#287 AC) — 스택트레이스·예외 타입·HTTP 상태
    # 코드가 그대로 노출되지 않는다.
    assert "Traceback" not in reasoning_text
    assert "401" not in reasoning_text
    assert "Exception" not in reasoning_text
    # 그리고 다시 낼 수 있다는 사실을 알려준다 — 참여자가 다음에 뭘 할 수
    # 있는지 안내한다.
    assert "다시 제출" in reasoning_text
    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"], permanent=True).exists()


def test_transient_failures_retry_up_to_the_cap_then_finalize(client, db, monkeypatch):
    ctx = _setup_submission(client)
    submission = ClassroomSubmission.objects.get(id=ctx["submission_id"])
    for _ in range(4):
        ClassroomScoringAttempt.objects.create(submission=submission, error="네트워크 순단", permanent=False)

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(500, {"error": {"message": "internal error"}}),
    )

    _run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission=submission).count() == 5
    score = ClassroomScore.objects.get(submission=submission)
    assert score.reasoning[0]["is_met"] is False


def test_repository_submission_is_scored_from_the_cloned_source(client, db, monkeypatch):
    ctx = _setup_submission(client, submission_format="repository")
    captured_prompts = []

    def _capture(url, *, headers, json, timeout):
        captured_prompts.append(json["messages"][1]["content"])
        return _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True))

    monkeypatch.setattr("core.llm_scoring.requests.post", _capture)

    _run_scan(client)

    assert len(captured_prompts) == 1
    assert "app.py" in captured_prompts[0]


def test_score_appears_in_the_scan_result_rows(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    result = _run_scan(client)

    assert result["rows"][0]["status"] == "scored"
    assert result["rows"][0]["submission_id"] == ctx["submission_id"]


def test_source_submission_is_scored_from_the_uploaded_object(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    participant_user_id = get_user_model().objects.get(username="kakao:participant-1").id

    object_key = f"classroom-submission:{problem_id}:{participant_user_id}:source/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(object_key, _zip_bytes({"main.py": "SOURCE_MARKER\n"}))
    submitted = _submit_source(client, participant["access"], class_id, problem_id, object_key)

    captured_prompts = []

    def _capture(url, *, headers, json, timeout):
        captured_prompts.append(json["messages"][1]["content"])
        return _FakeResponse(200, _openai_success_body(item_id, is_met=True))

    monkeypatch.setattr("core.llm_scoring.requests.post", _capture)

    result = _run_scan(client)

    assert result["count"] == 1
    assert "SOURCE_MARKER" in captured_prompts[0]
    score = ClassroomScore.objects.get(submission_id=submitted["id"])
    assert score.reasoning == [{"checklist_item_id": item_id, "is_met": True, "reasoning": "판정 근거"}]


def test_source_not_yet_in_storage_retries_instead_of_failing(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    participant_user_id = get_user_model().objects.get(username="kakao:participant-1").id

    # 스토리지에 아직 쓰지 않은 object_key — 업로드가 지연된 상황을 흉내낸다.
    object_key = f"classroom-submission:{problem_id}:{participant_user_id}:source/{uuid.uuid4().hex}"
    submitted = _submit_source(client, participant["access"], class_id, problem_id, object_key)

    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: called.append(1) or _FakeResponse(200, _openai_success_body(item_id, is_met=True)),
    )

    result = _run_scan(client)

    # 후보로는 집혔지만("아직" 상태를 남기는 것도 처리다) LLM은 부르지 않는다 —
    # 소스가 없는 채로 채점을 시도해 점수를 만들면 안 된다.
    assert result["rows"][0]["status"] == "source_not_ready"
    assert not called
    assert ClassroomScore.objects.filter(submission_id=submitted["id"]).count() == 0
    assert ClassroomScoringAttempt.objects.filter(
        submission_id=submitted["id"], permanent=False
    ).exists()


# --- 채점 완료를 낸 사람에게 알린다 (#303) --------------------------------------------


def _participant_user_id():
    return get_user_model().objects.get(username="kakao:participant-1").id


def _instructor_user_id():
    return get_user_model().objects.get(username="kakao:instructor-1").id


def test_scoring_completion_notifies_the_submitter_on_pass(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    _run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.recipient_id == _participant_user_id()
    assert notification.context["class_id"] == ctx["class_id"]
    assert notification.context["problem_id"] == ctx["problem_id"]
    assert notification.context["submission_id"] == ctx["submission_id"]
    assert notification.context["attempt_number"] == 1
    assert notification.context["passed"] is True


def test_scoring_completion_notifies_the_submitter_on_fail(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=False)),
    )

    _run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.context["passed"] is False


def test_permanent_failure_finalization_also_notifies_the_submitter(client, db, monkeypatch):
    """자동 미달(`_finalize_platform_failure`)로 채점이 끝난 경우도 "채점이
    끝났다"이므로 침묵으로 남지 않는다(AC)."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "Incorrect API key"}}),
    )

    _run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.recipient_id == _participant_user_id()
    assert notification.context["passed"] is False


def test_notification_is_never_sent_to_the_instructor(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    _run_scan(client)

    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        recipient_id=_instructor_user_id(),
    ).exists()


def test_notification_is_not_dispatched_to_any_channel(client, db, monkeypatch):
    """#301과 같은 규칙 — 문자로 나가지 않는다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    _run_scan(client)

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    )
    assert notification.status == Notification.Status.NOT_DISPATCHED
    assert notification.dispatches.count() == 0


def test_joining_a_class_creates_no_notification(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")

    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).exists()


def test_each_attempt_gets_its_own_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)

    second = _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world-again",
    )
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=False)),
    )
    _run_scan(client)

    notifications = Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).order_by("id")
    assert notifications.count() == 2
    by_submission = {n.context["submission_id"]: n for n in notifications}
    assert by_submission[ctx["submission_id"]].context["attempt_number"] == 1
    assert by_submission[second["id"]].context["attempt_number"] == 2
    assert by_submission[ctx["submission_id"]].context["passed"] is True
    assert by_submission[second["id"]].context["passed"] is False


def test_notification_creation_failure_does_not_prevent_scoring(client, db, monkeypatch):
    """AC: "알림 만들기가 실패해도 채점 자체는 그대로 끝난다." — 알림 쪽이
    죽어도(`create_notification`이 예외로 죽는 극단적인 경우) `ClassroomScore`는
    이미 커밋된 채로 남고, 스캔 결과도 정상 종결(`scored`)로 보고된다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )
    monkeypatch.setattr(
        "notifications.services.create_notification",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("notification backend is down")),
    )

    result = _run_scan(client)

    assert result["count"] == 1
    assert result["rows"][0]["status"] == "scored"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED
    ).exists()
