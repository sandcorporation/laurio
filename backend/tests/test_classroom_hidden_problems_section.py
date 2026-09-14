"""참여자 문제 목록 아래 「숨겨진 문제」 — 지난 기록에 닿는다 (#406,
CONTEXT.md 「Problem」).

핵심 대상: 숨긴 문제에 한 번이라도 낸 참여자는 문제 목록 응답의 별도
묶음(`hidden_problems`)에서 그 문제를 통과 여부와 함께 찾는다. 낸 적 없는
숨긴 문제는 이 묶음에도, 열린 목록에도 실리지 않는다. 강사가 다시 열면
그 문제는 이 묶음에서 빠지고 열린 목록으로 돌아온다.
"""

from __future__ import annotations

CLASSES_URL = "/api/classroom/classes"


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


def _create_open_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["repository"]},
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
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _hide(client, access: str, class_id: int, problem_id: int):
    return client.post(f"{CLASSES_URL}/{class_id}/problems/{problem_id}/hide", **_auth_header(access))


def _reopen(client, access: str, class_id: int, problem_id: int):
    return client.post(f"{CLASSES_URL}/{class_id}/problems/{problem_id}/reopen", **_auth_header(access))


def _submit(client, access: str, class_id: int, problem_id: int, value: str):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": value, "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )


def _my_problems(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems/mine", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


def test_hidden_problem_with_a_submission_appears_in_the_hidden_bundle(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)

    body = _my_problems(client, participant["access"], class_id)

    assert body["problems"] == []
    assert [p["id"] for p in body["hidden_problems"]] == [problem_id]


def test_hidden_problem_never_submitted_to_appears_nowhere(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _hide(client, instructor["access"], class_id, problem_id)

    body = _my_problems(client, participant["access"], class_id)

    assert body["problems"] == []
    assert body["hidden_problems"] == []


def test_hidden_bundle_carries_pass_status(client, db, monkeypatch):
    """fake 채점 어댑터가 소스에 그 문구가 등장하면 통과로 판정한다."""

    from django.conf import settings

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": "sk-test-instructor-key"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(
        client,
        participant["access"],
        class_id,
        problem_id,
        "https://github.com/octocat/fake-clone-marker-pass",
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("fake 경로인데 네트워크로 나갔다.")

    monkeypatch.setattr("core.llm_scoring.requests.post", _fail_if_called)
    # 체크리스트 문구를 fake 저장소 소스에 등장하는 문구로 맞춘다.
    problem_detail = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(instructor["access"])
    ).json()
    item_id = problem_detail["checklist_items"][0]["id"]
    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
        data={"label": "fake-clone-marker-pass"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    scan = client.post(
        "/api/internal/scans/classroom-submission-scoring",
        content_type="application/json",
        HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN,
    )
    assert scan.status_code == 200, scan.content
    assert scan.json()["count"] == 1

    _hide(client, instructor["access"], class_id, problem_id)

    body = _my_problems(client, participant["access"], class_id)

    assert body["hidden_problems"] == [
        {
            "id": problem_id,
            "title": "1주차",
            "submission_formats": ["repository"],
            "passed": True,
        }
    ]


def test_reopened_problem_leaves_the_hidden_bundle_and_returns_to_the_open_list(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)
    assert _my_problems(client, participant["access"], class_id)["hidden_problems"] != []

    _reopen(client, instructor["access"], class_id, problem_id)

    body = _my_problems(client, participant["access"], class_id)
    assert body["hidden_problems"] == []
    assert [p["id"] for p in body["problems"]] == [problem_id]


def test_a_participant_who_never_submitted_sees_no_hidden_bundle_even_if_others_did(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id = _create_open_problem(client, instructor["access"], class_id)
    submitter = _login(client, uid="participant-1")
    _join(client, submitter["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, submitter["access"], class_id, problem_id, "https://github.com/octocat/hello")

    bystander = _login(client, uid="participant-2")
    _join(client, bystander["access"], _join_code(client, instructor["access"], class_id))

    _hide(client, instructor["access"], class_id, problem_id)

    body = _my_problems(client, bystander["access"], class_id)
    assert body["hidden_problems"] == []
