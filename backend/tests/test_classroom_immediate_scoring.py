"""제출하면 곧바로 채점이 시작된다 — 스캔은 안전망으로 남는다 (#378, ADR-0046).

핵심 대상 셋: (1) 강의실 제출이 커밋되면 그 시도의 채점 작업이 큐에 들어간다,
(2) 시도 하나 채점 내부 엔드포인트(`/api/internal/classroom/attempts/{id}/score`)가
스캔과 같은 함수·같은 후보 조건으로 그 시도를 채점하고 내부 토큰 없이는
거절된다, (3) 두 경로(즉시 채점↔즉시 채점, 즉시 채점↔스캔)가 겹쳐도
`ClassroomScore`는 시도당 정확히 하나다(ADR-0006).

`test_classroom_scoring.py`·`test_classroom_scoring_fake_adapter.py`와 헬퍼가
겹치지만 이 저장소의 관용구대로 파일마다 자기 것을 따로 갖는다 — 공유 conftest
픽스처로 옮기지 않는다.
"""

from __future__ import annotations

import inspect
import threading
import time

import pytest
from django.conf import settings
from django.db import connections
from django.test import Client

from classroom import tasks as classroom_tasks
from classroom.models import ClassroomScore, ClassroomScoringAttempt
from classroom.scoring import FakeClassroomScoringAdapter

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _score_url(submission_id: int) -> str:
    return f"/api/internal/classroom/attempts/{submission_id}/score"


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


def test_submitting_enqueues_the_immediate_scoring_task(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    """제출 응답이 나가기 전이 아니라 **트랜잭션이 커밋된 뒤** 큐에 들어간다 —
    `on_commit` 콜백을 실제로 실행해 봐야 관찰된다(그냥 `db` 픽스처는 테스트를
    통째로 롤백해 콜백이 평소엔 전혀 안 불린다)."""

    calls: list[int] = []
    monkeypatch.setattr(classroom_tasks.score_attempt, "delay", lambda submission_id: calls.append(submission_id))

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

    assert calls == [submitted["id"]]


def test_submission_survives_when_the_broker_is_unreachable(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    """브로커에 닿지 못해도 제출은 성공한다 — 시도는 이미 커밋됐고 60초 스캔이 줍는다
    (ADR-0046 「안전망」). 발행 실패가 커밋 뒤에 예외로 튀면 참여자는 500 을 받고 다시
    내 시도가 중복된다(staging Redis 재시작, 호스트 runserver 의 기본 브로커 주소)."""

    from kombu.exceptions import OperationalError

    def _unreachable(submission_id):
        raise OperationalError("Error 111 connecting to 127.0.0.1:6379. Connection refused.")

    monkeypatch.setattr(classroom_tasks.score_attempt, "delay", _unreachable)

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


def test_submitting_does_not_score_synchronously_even_with_the_task_enqueued(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    """`test_classroom_scoring.test_submitting_does_not_score_synchronously`와
    같은 계약을 이 파일의 관심사(즉시 채점 자체) 옆에서도 고정한다 — 큐에 넣는
    것과 실제로 채점하는 것은 다른 일이다. 태스크의 `delay`를 실제로 실행해도
    (dev·CI에는 이걸 소비할 워커가 없다, #40) 이 요청·응답 자체는 여전히
    동기로 채점하지 않는다."""

    ctx_calls: list[int] = []
    monkeypatch.setattr(
        classroom_tasks.score_attempt, "delay", lambda submission_id: ctx_calls.append(submission_id)
    )

    with django_capture_on_commit_callbacks(execute=True):
        ctx = _setup_submission(client)

    assert ctx_calls == [ctx["submission_id"]]
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "pending"
    assert ClassroomScore.objects.count() == 0


def test_the_task_calls_the_internal_score_endpoint_with_the_token():
    """`core.tasks.run_scan`과 같은 모양이다(`tests/test_scheduler_celery.py`의
    관용구) — 실제로 브로커·워커 없이 소스만으로 내부 인증 경로를 고정한다."""

    source = inspect.getsource(classroom_tasks.score_attempt)
    assert "/api/internal/classroom/attempts/" in source
    assert "call_internal" in source


# --- 내부 엔드포인트: 인증 -------------------------------------------------------


def test_internal_score_endpoint_rejects_without_the_internal_token(client, db):
    ctx = _setup_submission(client)

    response = client.post(_score_url(ctx["submission_id"]), content_type="application/json")

    assert response.status_code == 401
    assert ClassroomScore.objects.count() == 0


# --- 내부 엔드포인트: 채점 자체 (스캔과 같은 함수·같은 후보 조건) ------------------


def test_internal_score_endpoint_scores_a_pending_candidate(client, db):
    ctx = _setup_submission(client)

    response = client.post(
        _score_url(ctx["submission_id"]), content_type="application/json", **_internal_headers()
    )

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "scored"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "scored"


def test_internal_score_endpoint_is_idempotent_when_called_twice(client, db):
    """같은 시도에 엔드포인트를 두 번 불러도 `ClassroomScore`는 하나다(#378 AC) —
    두 번째 호출 시점에는 스캔의 후보 조건(`classroom_score__isnull=True`)을
    이미 벗어나 있어 곧바로 건너뛴다."""

    ctx = _setup_submission(client)

    first = client.post(
        _score_url(ctx["submission_id"]), content_type="application/json", **_internal_headers()
    )
    second = client.post(
        _score_url(ctx["submission_id"]), content_type="application/json", **_internal_headers()
    )

    assert first.json()["status"] == "scored"
    assert second.json()["status"] == "not_a_candidate"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1


def test_internal_score_endpoint_skips_a_submission_whose_class_has_no_key(client, db, monkeypatch):
    """스캔의 후보 조건 밖(키 없음)은 곧바로 채점되지 않고 조용히 건너뛴다(#378
    AC) — "시도했는데 실패했다"가 아니므로 `ClassroomScoringAttempt`도 남기지
    않는다."""

    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: called.append(1)
    )
    ctx = _setup_submission(client, with_key=False)

    response = client.post(
        _score_url(ctx["submission_id"]), content_type="application/json", **_internal_headers()
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_a_candidate"
    assert not called
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["status"] == "pending"


def test_internal_score_endpoint_skips_an_unknown_submission_id(client, db):
    ctx = _setup_submission(client)

    response = client.post(
        _score_url(ctx["submission_id"] + 100_000),
        content_type="application/json",
        **_internal_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_a_candidate"


def test_internal_score_endpoint_skips_what_the_scan_already_scored(client, db):
    """즉시 채점↔스캔 두 경로가 겹쳐도 `ClassroomScore`는 하나다(#378 AC,
    ADR-0006) — 스캔이 먼저 채점을 끝낸 뒤 즉시 채점 엔드포인트가 불려도
    같은 후보 조건이 그 시도를 걸러 조용히 건너뛴다."""

    ctx = _setup_submission(client)

    scanned = _run_scan(client)
    assert scanned["count"] == 1

    response = client.post(
        _score_url(ctx["submission_id"]), content_type="application/json", **_internal_headers()
    )

    assert response.json()["status"] == "not_a_candidate"
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1


# --- 두 경로가 실제로 겹친다 — 행 잠금 ------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_overlapping_calls_to_the_internal_endpoint_score_the_attempt_once(
    django_db_blocker, monkeypatch
):
    """즉시 채점 두 경로(제출 직후 태스크 ↔ 놓친 시도를 줍는 스캔, 또는 같은
    태스크가 재시도로 겹치는 것)가 정말로 동시에 같은 시도를 집어도
    `ClassroomScore`는 하나다(#378 AC, ADR-0006) — `_score_one`의
    `select_for_update(skip_locked=True)`가 그것을 지킨다.

    `FakeClassroomScoringAdapter.score`에 지연을 넣어 한쪽이 행을 잠그고 있는
    동안 다른 쪽의 SELECT ... FOR UPDATE SKIP LOCKED가 실제로 그 잠금과
    마주치는 창을 만든다 — 그러지 않으면 두 요청이 순서대로 너무 빨리 끝나
    "겹침" 자체가 우연에 맡겨진다."""

    original_score = FakeClassroomScoringAdapter.score

    def _slow_score(self, scoring_input):
        time.sleep(0.3)
        return original_score(self, scoring_input)

    monkeypatch.setattr(FakeClassroomScoringAdapter, "score", _slow_score)

    with django_db_blocker.unblock():
        client = Client()
        ctx = _setup_submission(client)

        results: list = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with django_db_blocker.unblock():
                    local_client = Client()
                    barrier.wait()
                    response = local_client.post(
                        _score_url(ctx["submission_id"]),
                        content_type="application/json",
                        **_internal_headers(),
                    )
                    results.append(response)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        statuses = sorted(r.json()["status"] for r in results)
        assert statuses == ["locked_elsewhere", "scored"], [
            (r.status_code, r.content) for r in results
        ]
        assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1
