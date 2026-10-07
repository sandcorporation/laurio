"""제출하면 곧바로 채점이 시작된다 — 스캔은 안전망으로 남는다 (#378, #584, ADR-0046, ADR-0059).

핵심 대상 셋: (1) 강의실 제출이 커밋되면 그 시도가 grader 의 큐에 들어간다(「큐에 넣은 시각」),
(2) grader 가 스캔과 같은 후보 조건으로 그 시도를 채점한다(내부 HTTP 를 거치지 않는다),
(3) 두 경로(즉시 채점↔스캔)가 겹쳐도 `ClassroomScore`는 시도당 정확히 하나다(ADR-0006). 임대·
동시 실행·실패 규율은 `test_classroom_grader.py`가 본다.

`test_classroom_scoring.py`·`test_classroom_scoring_fake_adapter.py`와 헬퍼가
겹치지만 이 저장소의 관용구대로 파일마다 자기 것을 따로 갖는다 — 공유 conftest
픽스처로 옮기지 않는다.
"""

from __future__ import annotations

from django.conf import settings

from django.utils import timezone

from classroom.grader import grade_inline
from classroom.models import ClassroomScore, ClassroomScoringAttempt, ClassroomSubmission
from tests.classroom_scenarios import track_vendor_calls

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _run_task(submission_id: int) -> dict:
    """grader 가 하듯 한 시도를 처리한다 — 임대를 집을 수 없으면(큐에 없거나 이미 채점됨)
    `not_claimed`."""

    ClassroomSubmission.objects.filter(pk=submission_id, scoring_queued_at__isnull=True).update(
        scoring_queued_at=timezone.now()
    )
    return grade_inline(submission_id) or {"submission_id": submission_id, "status": "not_claimed"}


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


def _create_open_problem(client, access: str, class_id: int, label: str) -> tuple[int, int]:
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
        data={"label": label, "required": True},
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


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


# `core.repository_adapters.FakeGitHubAdapter.clone`은 `"# fake clone of {url}\n"`을
# 소스로 돌려준다 — 그 URL을 체크리스트 문구로 써서 fake 어댑터의 통과·미통과를
# 결정적으로 고른다(`test_classroom_scoring_fake_adapter.py`와 같은 요령).
_PASSING_URL = "https://github.com/octocat/fake-clone-marker-pass"
_PASSING_LABEL = "fake-clone-marker-pass"


def _setup_submission(client, *, with_key: bool = True) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    if with_key:
        _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, _PASSING_LABEL)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(client, participant["access"], class_id, problem_id, _PASSING_URL)
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


# --- 제출 → 즉시 채점 작업이 큐에 들어간다 --------------------------------------


def test_submitting_enqueues_the_attempt_after_the_commit(
    client, db, settings, django_capture_on_commit_callbacks
):
    """제출 응답이 나가기 전이 아니라 **트랜잭션이 커밋된 뒤** 큐에 들어간다 —
    `on_commit` 콜백을 실제로 실행해 봐야 관찰된다(그냥 `db` 픽스처는 테스트를
    통째로 롤백해 콜백이 평소엔 전혀 안 불린다). 큐에 넣는다는 것은 시각을 찍는다는 것이다."""

    settings.CLASSROOM_GRADER_INLINE = False
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id, _PASSING_LABEL)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        submitted = _submit_repository(
            client, participant["access"], class_id, problem_id, _PASSING_URL
        )

    assert callbacks
    assert ClassroomSubmission.objects.get(pk=submitted["id"]).scoring_queued_at is not None


def test_submission_survives_when_the_grader_is_not_running(
    client, db, settings, django_capture_on_commit_callbacks
):
    """grader 가 꺼져 있어도 제출은 성공한다 — 시도는 큐에서 기다리고 grader 가 뜨면 줍는다
    (ADR-0046 「안전망」)."""

    settings.CLASSROOM_GRADER_INLINE = False
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id, _PASSING_LABEL)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    with django_capture_on_commit_callbacks(execute=True):
        submitted = _submit_repository(
            client, participant["access"], class_id, problem_id, _PASSING_URL
        )

    mine = _mine(client, participant["access"], class_id, problem_id)
    assert [s["id"] for s in mine["submissions"]] == [submitted["id"]]
    assert mine["submissions"][0]["status"] == "pending"


def test_task_scores_a_pending_candidate(client, db):
    ctx = _setup_submission(client)

    result = _run_task(ctx["submission_id"])

    assert result["status"] == "scored"
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "scored"


def test_task_is_idempotent_when_run_twice(client, db):
    """같은 시도의 태스크가 두 번 돌아도 `ClassroomScore`는 하나다(#378 AC) — 두 번째는
    스캔의 후보 조건(`classroom_score__isnull=True`)을 이미 벗어나 곧바로 건너뛴다."""

    ctx = _setup_submission(client)

    first = _run_task(ctx["submission_id"])
    second = _run_task(ctx["submission_id"])

    assert first["status"] == "scored"
    assert second["status"] == "not_claimed"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1


def test_task_skips_a_submission_whose_class_has_no_key(client, db, monkeypatch):
    """스캔의 후보 조건 밖(키 없음)은 채점되지 않고 조용히 건너뛴다(#378 AC) — "시도했는데
    실패했다"가 아니므로 `ClassroomScoringAttempt`도 남기지 않는다."""

    calls = track_vendor_calls(monkeypatch)
    ctx = _setup_submission(client, with_key=False)

    result = _run_task(ctx["submission_id"])

    assert result["status"] == "not_a_candidate"
    assert not calls
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "pending"


def test_task_skips_an_unknown_submission_id(client, db):
    ctx = _setup_submission(client)

    assert _run_task(ctx["submission_id"] + 100_000)["status"] == "not_claimed"


def test_task_skips_what_the_scan_already_scored(client, db):
    """즉시 채점↔스캔 두 경로가 겹쳐도 `ClassroomScore`는 하나다(#378 AC, ADR-0006) —
    스캔이 넣은 태스크가 먼저 채점을 끝낸 뒤 즉시 채점 태스크가 돌아도 같은 후보 조건이
    그 시도를 걸러 조용히 건너뛴다."""

    ctx = _setup_submission(client)

    scanned = _run_scan(client)
    assert scanned["count"] == 1

    assert _run_task(ctx["submission_id"])["status"] == "not_claimed"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1
