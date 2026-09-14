"""제출 — 소스나 저장소를 내고, 시도가 쌓인다 (#286, CONTEXT.md 「강의실」,
ADR-0039).

핵심 대상: 참여자가 열린 문제에 소스 또는 저장소로 제출하고, 몇 번이든 다시
내면 그때마다 새 시도가 순서대로 쌓인다(마감도 횟수 상한도 없다). 자료 모델은
공모전 쪽(`SubmissionAsset`)을 그대로 물려받는다 — 근거 연결도 자가 체크도
없다. 남의 제출물은 애초에 질의에 없고, 그 클래스의 참여자가 아니면(또는
내보내졌으면) 제출 자체가 막힌다.
"""

from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model

from classroom.models import ClassroomSubmission, Problem

CLASSES_URL = "/api/classroom/classes"


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    user = get_user_model().objects.get(username=f"kakao:{uid}")
    return {"access": body["access"], "user_id": user.id, "email": email}


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


def _create_open_problem(
    client, access: str, class_id: int, submission_formats: list[str] | str = "repository"
) -> int:
    formats = [submission_formats] if isinstance(submission_formats, str) else submission_formats
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": formats},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트 통과", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _mine_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine"


def _submissions_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions"


def _source_object_key(problem_id: int, user_id: int) -> str:
    return f"classroom-submission:{problem_id}:{user_id}:source/{uuid.uuid4().hex}"


def _submit(
    client,
    access: str,
    class_id: int,
    problem_id: int,
    value: str,
    submission_format: str = "repository",
    **extra,
):
    return client.post(
        _submissions_url(class_id, problem_id),
        data={"value": value, "submission_format": submission_format, **extra},
        content_type="application/json",
        **_auth_header(access),
    )


def test_participant_submits_a_repository_url_and_it_appears_as_the_first_attempt(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    response = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello"
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["attempt_number"] == 1
    assert body["submission_format"] == "repository"
    assert body["value"] == "https://github.com/octocat/hello"
    assert body["download_url"] is None


def test_resubmitting_stacks_a_new_attempt_instead_of_replacing(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    first = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/one"
    )
    second = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/two"
    )

    assert first.json()["attempt_number"] == 1
    assert second.json()["attempt_number"] == 2
    assert ClassroomSubmission.objects.filter(problem_id=problem_id).count() == 2


def test_source_submission_uses_the_shared_submission_asset_model(client, db):
    from submissions.models import Submission, SubmissionAsset

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    object_key = _source_object_key(problem_id, participant["user_id"])

    response = _submit(
        client, participant["access"], class_id, problem_id, object_key, submission_format="source"
    )

    assert response.status_code == 201, response.content
    submission = ClassroomSubmission.objects.get(id=response.json()["id"])
    assert submission.product == Submission.Product.CLASSROOM
    asset = SubmissionAsset.objects.get(submission=submission)
    assert asset.kind == SubmissionAsset.Kind.SOURCE
    assert asset.value == object_key


def test_source_object_key_must_belong_to_callers_own_target_ref(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1")
    other = _login(client, uid="participant-2")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _join(client, other["access"], _join_code(client, instructor["access"], class_id))
    stolen_key = _source_object_key(problem_id, other["user_id"])

    response = _submit(
        client, participant["access"], class_id, problem_id, stolen_key, submission_format="source"
    )

    assert response.status_code == 422
    assert ClassroomSubmission.objects.count() == 0


def test_repository_value_must_be_a_github_url(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    response = _submit(client, participant["access"], class_id, problem_id, "not-a-url")

    assert response.status_code == 422


def test_a_format_the_problem_does_not_allow_is_rejected_even_if_it_is_a_valid_value(client, db):
    """#373 AC — 화면을 우회해도 서버가 거절한다. 소스만 여는 문제에 저장소를
    골라 내면, 그 값 자체는 멀쩡한 GitHub URL이라도 422다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    response = _submit(
        client,
        participant["access"],
        class_id,
        problem_id,
        "https://github.com/octocat/hello",
        submission_format="repository",
    )

    assert response.status_code == 422
    assert ClassroomSubmission.objects.count() == 0


def test_a_problem_open_to_both_formats_accepts_either_on_different_attempts(client, db):
    """#373 AC — 둘 다 열린 문제에서 참여자는 시도마다 그중 하나를 골라 낸다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(
        client, instructor["access"], class_id, ["source", "repository"]
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    object_key = _source_object_key(problem_id, participant["user_id"])

    source_attempt = _submit(
        client, participant["access"], class_id, problem_id, object_key, submission_format="source"
    )
    repository_attempt = _submit(
        client,
        participant["access"],
        class_id,
        problem_id,
        "https://github.com/octocat/hello",
        submission_format="repository",
    )

    assert source_attempt.status_code == 201, source_attempt.content
    assert repository_attempt.status_code == 201, repository_attempt.content
    assert source_attempt.json()["submission_format"] == "source"
    assert repository_attempt.json()["submission_format"] == "repository"


def test_non_participant_cannot_submit(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    stranger = _login(client, uid="stranger-1")

    response = _submit(
        client, stranger["access"], class_id, problem_id, "https://github.com/octocat/hello"
    )

    assert response.status_code == 404
    assert ClassroomSubmission.objects.count() == 0


def test_expelled_member_cannot_submit_a_new_attempt(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    members = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(instructor["access"]))
    member_id = next(m["id"] for m in members.json() if not m["is_instructor"])
    expel = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert expel.status_code == 200

    response = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello"
    )

    assert response.status_code == 403


def test_expelled_member_can_still_read_their_past_submissions(client, db):
    """티켓 #300 AC — 내보내진 사람도 지난 제출과 판정을 읽을 수 있다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")

    members = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(instructor["access"]))
    member_id = next(m["id"] for m in members.json() if not m["is_instructor"])
    client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    mine = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))

    assert mine.status_code == 200
    body = mine.json()
    assert len(body["submissions"]) == 1
    assert body["submissions"][0]["value"] == "https://github.com/octocat/hello"


def test_expelled_members_problem_view_signals_why_they_cannot_submit(client, db):
    """화면이 제출 수단을 감추고 이유를 말해 줄 신호(#300 AC)."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    mine_before = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))
    assert mine_before.json()["member_expelled"] is False

    members = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(instructor["access"]))
    member_id = next(m["id"] for m in members.json() if not m["is_instructor"])
    client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    mine_after = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))
    assert mine_after.json()["member_expelled"] is True


def test_expelled_member_still_sees_the_problem_list(client, db):
    """티켓 #300 AC — 내보내진 사람도 문제 목록을 그대로 읽는다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    members = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(instructor["access"]))
    member_id = next(m["id"] for m in members.json() if not m["is_instructor"])
    client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/mine", **_auth_header(participant["access"])
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_draft_problem_cannot_be_submitted_to(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "초안", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    response = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello"
    )

    assert response.status_code == 404


def test_participant_sees_only_their_own_attempts(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    join_code = _join_code(client, instructor["access"], class_id)
    first = _login(client, uid="participant-1")
    second = _login(client, uid="participant-2")
    _join(client, first["access"], join_code)
    _join(client, second["access"], join_code)

    _submit(client, first["access"], class_id, problem_id, "https://github.com/octocat/first")
    _submit(client, second["access"], class_id, problem_id, "https://github.com/octocat/second")

    mine = client.get(_mine_url(class_id, problem_id), **_auth_header(first["access"]))

    assert mine.status_code == 200
    body = mine.json()
    assert len(body["submissions"]) == 1
    assert body["submissions"][0]["value"] == "https://github.com/octocat/first"


def test_mine_includes_the_problem_and_its_checklist(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    mine = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))

    assert mine.status_code == 200
    body = mine.json()
    assert body["problem"]["id"] == problem_id
    assert body["problem"]["checklist_items"][0]["label"] == "테스트 통과"
    assert body["submissions"] == []


def test_non_participant_gets_a_404_instead_of_the_problems_existence(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "repository")
    stranger = _login(client, uid="stranger-1")

    response = client.get(_mine_url(class_id, problem_id), **_auth_header(stranger["access"]))

    assert response.status_code == 404


def test_download_filename_is_derived_from_the_submitters_user_email_not_a_developer_profile(
    client, db
):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id, "source")
    participant = _login(client, uid="participant-1", email="learner@example.com")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    object_key = _source_object_key(problem_id, participant["user_id"])

    response = _submit(
        client,
        participant["access"],
        class_id,
        problem_id,
        object_key,
        submission_format="source",
        content_type="application/zip",
    )

    assert response.status_code == 201, response.content
    download_url = response.json()["download_url"]
    assert download_url is not None
    assert "learner@example.com" in download_url
    assert 'filename="learner@example.com.zip"' in download_url


def test_classroom_submission_has_no_unique_constraint_across_attempts(client, db):
    """공모전 자식(`ContestSubmission`)과 달리 `(problem, member)` 유니크
    제약이 없다 — ADR-0039가 정한 강의실만의 계약이다."""

    constraint_names = {c.name for c in ClassroomSubmission._meta.constraints}
    assert not any("problem" in name and "member" in name for name in constraint_names)
