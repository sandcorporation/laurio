"""강사가 제출물을 열어 본다 — 그리고 그 열람은 기록되지 않는다 (#291,
ADR-0040, CONTEXT.md 「강의실」).

핵심 대상: 강사가 참여자들의 시도를 훑어보고 소스를 내려받거나 저장소를 열고
AI 판정과 근거를 함께 본다. 다운로드 파일명이 참여자 이름과 시도 번호를
구별해 여러 사람 것을 받아도 서로 덮지 않는다. 그 클래스의 강사가 아니면
열 수 없고, 이 열람 자체는
어디에도 기록되지 않는다.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote as urlquote

import pytest
from django.conf import settings
from django.test import override_settings

from tests.classroom_scenarios import respond_with_verdicts

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    # 이 파일은 실물 OpenAIScoringAdapter 경로 자체를 검증한다 —
    # CLASSROOM_SCORING_ADAPTER_MODE 기본값(fake)이 그 경로를 안 타므로
    # 강제한다(#340, ADR-0043). 벤더 응답은 respond_with_verdict(#469,
    # tests.classroom_scenarios)로 흉내 낸다.
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


def _create_open_problem(
    client, access: str, class_id: int, submission_format: str = "repository", title: str = "1주차"
) -> dict:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": [submission_format]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    required = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert required.status_code == 201
    required_id = required.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return {"problem_id": problem_id, "required_id": required_id}


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


def _source_object_key(problem_id: int, user_id: int) -> str:
    return f"classroom-submission:{problem_id}:{user_id}:source/{uuid.uuid4().hex}"


def _submit_source(client, access: str, class_id: int, problem_id: int, object_key: str, content_type: str = "application/zip") -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": object_key, "content_type": content_type, "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _instructor_submissions_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions"


def _list_submissions(client, access: str, class_id: int, problem_id: int):
    response = client.get(_instructor_submissions_url(class_id, problem_id), **_auth_header(access))
    return response


def _run_scan(client) -> None:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content


def test_instructor_sees_every_participants_attempts(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem = _create_open_problem(client, instructor["access"], class_id)

    alice = _login(client, uid="alice")
    _join(client, alice["access"], _join_code(client, instructor["access"], class_id), display_name="앨리스")
    bob = _login(client, uid="bob")
    _join(client, bob["access"], _join_code(client, instructor["access"], class_id), display_name="밥")

    _submit_repository(client, alice["access"], class_id, problem["problem_id"], "https://github.com/octocat/alice")
    _submit_repository(client, bob["access"], class_id, problem["problem_id"], "https://github.com/octocat/bob")

    response = _list_submissions(client, instructor["access"], class_id, problem["problem_id"])
    assert response.status_code == 200
    body = response.json()
    names = {row["member_display_name"] for row in body}
    assert names == {"앨리스", "밥"}
    values = {row["value"] for row in body}
    assert values == {"https://github.com/octocat/alice", "https://github.com/octocat/bob"}


def test_repository_attempts_have_no_download_url_since_the_value_is_already_a_url(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    _submit_repository(client, participant["access"], class_id, problem["problem_id"], "https://github.com/octocat/one")

    body = _list_submissions(client, instructor["access"], class_id, problem["problem_id"]).json()
    assert body[0]["download_url"] is None


def test_source_attempt_download_filename_distinguishes_participant_and_attempt(client, db):
    """AC: 다운로드 파일명이 참여자 이름과 시도를 구별한다 — 여러 사람 것을
    받아도 서로 덮지 않는다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem = _create_open_problem(client, instructor["access"], class_id, submission_format="source")

    alice = _login(client, uid="alice")
    _join(client, alice["access"], _join_code(client, instructor["access"], class_id), display_name="앨리스")
    bob = _login(client, uid="bob")
    _join(client, bob["access"], _join_code(client, instructor["access"], class_id), display_name="밥")

    _submit_source(
        client, alice["access"], class_id, problem["problem_id"],
        _source_object_key(problem["problem_id"], _uid(client, alice)),
    )
    _submit_source(
        client, alice["access"], class_id, problem["problem_id"],
        _source_object_key(problem["problem_id"], _uid(client, alice)),
    )
    _submit_source(
        client, bob["access"], class_id, problem["problem_id"],
        _source_object_key(problem["problem_id"], _uid(client, bob)),
    )

    body = _list_submissions(client, instructor["access"], class_id, problem["problem_id"]).json()
    download_urls = [row["download_url"] for row in body]
    assert all(download_urls)
    # 세 시도(앨리스 1·2번째, 밥 1번째) 모두 서로 다른 파일명으로 떨어진다 —
    # 참여자 이름만으로는 앨리스의 두 시도가 갈리지 않으므로 attempt_number가
    # 함께 실려야 한다.
    assert len(set(download_urls)) == len(download_urls) == 3

    alice_rows = sorted(
        (row for row in body if row["member_display_name"] == "앨리스"),
        key=lambda r: r["attempt_number"],
    )
    assert len(alice_rows) == 2
    # 한글 이름은 filename*=UTF-8''로 퍼센트 인코딩되어 실린다
    # (storage.filenames.content_disposition, RFC 5987) — 그 인코딩된 이름이
    # 시도 번호별로 갈린다.
    encoded_first = urlquote("앨리스-1.zip", safe="")
    encoded_second = urlquote("앨리스-2.zip", safe="")
    assert encoded_first in alice_rows[0]["download_url"]
    assert encoded_second in alice_rows[1]["download_url"]


def _uid(client, logged_in: dict) -> int:
    # `_login`은 access 토큰만 돌려주므로, target_ref 조립에 필요한 user id는
    # `/api/accounts/me`를 다시 쳐서 얻는다(참여자 화면이 이미 같은 방식을 쓴다).
    response = client.get("/api/accounts/me", **_auth_header(logged_in["access"]))
    assert response.status_code == 200
    return response.json()["id"]


def test_instructor_sees_the_ai_verdict_and_its_reasoning_once_scored(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    submitted = _submit_repository(
        client, participant["access"], class_id, problem["problem_id"], "https://github.com/octocat/one"
    )

    body = _list_submissions(client, instructor["access"], class_id, problem["problem_id"]).json()
    row = next(r for r in body if r["id"] == submitted["id"])
    assert row["status"] == "pending"
    assert row["score"] is None

    respond_with_verdicts(
        monkeypatch,
        [{"requirement_id": problem["required_id"], "is_met": True, "reasoning": "테스트 코드가 있다"}],
    )
    _run_scan(client)

    body = _list_submissions(client, instructor["access"], class_id, problem["problem_id"]).json()
    row = next(r for r in body if r["id"] == submitted["id"])
    assert row["status"] == "scored"
    assert row["passed"] is True
    assert row["score"]["reasoning"][0]["reasoning"] == "테스트 코드가 있다"
    assert row["score"]["reasoning"][0]["is_met"] is True


def test_only_the_classs_instructor_can_list_submissions(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit_repository(client, participant["access"], class_id, problem["problem_id"], "https://github.com/octocat/one")

    stranger = _login(client, uid="stranger-1")
    response = _list_submissions(client, stranger["access"], class_id, problem["problem_id"])
    assert response.status_code == 404

    response = _list_submissions(client, participant["access"], class_id, problem["problem_id"])
    assert response.status_code == 404
