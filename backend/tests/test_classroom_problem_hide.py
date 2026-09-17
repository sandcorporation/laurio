"""문제 숨김 — 강사가 거두고 다시 연다 (#405, CONTEXT.md 「Problem」).

핵심 대상: 강사가 열린 문제를 「숨기기」로 참여자에게서 거두고 「다시 열기」로
되돌린다. 제출이 있어도 숨길 수 있다. 숨김에서 초안으로 가는 길은 없다 —
허용되지 않는 전이는 400, 남의 클래스·문제는 404다. 참여자 쪽: 숨긴 문제는
열린 목록에서 빠지고, 낸 적 있는 사람만 그 문제 화면을 읽기 전용으로 계속
보며 새로 낼 수는 없다. 낸 적 없는 참여자에게는 존재 자체가 숨겨진다.
채점은 문제 상태를 보지 않는다 — 숨긴 뒤에도 시도는 끝까지 채점된다.
"""

from __future__ import annotations

from django.conf import settings

from classroom.models import Problem

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


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

    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트 통과", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    item_id = checklist.json()["id"]
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id, item_id


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


def _hide_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/hide"


def _reopen_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/reopen"


def _mine_list_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/mine"


def _mine_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine"


def _submissions_url(class_id: int, problem_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions"


def _hide(client, access: str, class_id: int, problem_id: int):
    return client.post(_hide_url(class_id, problem_id), **_auth_header(access))


def _reopen(client, access: str, class_id: int, problem_id: int):
    return client.post(_reopen_url(class_id, problem_id), **_auth_header(access))


def _submit(client, access: str, class_id: int, problem_id: int, value: str):
    return client.post(
        _submissions_url(class_id, problem_id),
        data={"value": value, "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )


# --- 강사: 전이 -------------------------------------------------------------


def test_instructor_hides_an_open_problem_even_with_submissions(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello"
    )
    assert submitted.status_code == 201

    response = _hide(client, instructor["access"], class_id, problem_id)

    assert response.status_code == 200
    assert response.json()["status"] == Problem.Status.HIDDEN
    assert Problem.objects.get(id=problem_id).status == Problem.Status.HIDDEN


def test_instructor_reopens_a_hidden_problem(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)

    response = _reopen(client, instructor["access"], class_id, problem_id)

    assert response.status_code == 200
    assert response.json()["status"] == Problem.Status.OPEN
    assert Problem.objects.get(id=problem_id).status == Problem.Status.OPEN


def test_reopening_without_required_items_is_400(client, db):
    """다시 열기도 열기와 같은 필수 항목 규칙을 따른다(#405 AC) — 지금은
    숨긴 문제의 마지막 필수 항목 삭제 자체가 전이 표(#440)로 422 거절되므로,
    「필수 항목을 다 지운 숨긴 문제」는 API로 만들 수 없다. 그래도 이 규칙이
    사라지지 않았다는 것을 문제 상세의 `available_transitions`로 확인한다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)

    # 필수 항목을 없애려는 시도 자체가 거절된다(#440) — 예전에는 여기서
    # 204가 나고, 그 사이 상태에서 다시 열기가 400으로 막혔었다.
    delete = client.delete(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items/{item_id}",
        **_auth_header(instructor["access"]),
    )
    assert delete.status_code == 422
    assert Problem.objects.get(id=problem_id).status == Problem.Status.HIDDEN

    detail = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(instructor["access"])
    )
    transitions = detail.json()["available_transitions"]
    assert transitions == [{"name": "reopen", "to_state": "open", "blocked_reason": None}]

    response = _reopen(client, instructor["access"], class_id, problem_id)
    assert response.status_code == 200


def test_hiding_a_draft_problem_is_rejected(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "초안", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]

    response = _hide(client, instructor["access"], class_id, problem_id)

    assert response.status_code == 400
    assert Problem.objects.get(id=problem_id).status == Problem.Status.DRAFT


def test_reopening_an_open_problem_is_rejected(client, db):
    """열림 → 열림은 「다시 열기」 엔드포인트의 전이가 아니다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)

    response = _reopen(client, instructor["access"], class_id, problem_id)

    assert response.status_code == 400


def test_hiding_an_already_hidden_problem_is_rejected(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)

    response = _hide(client, instructor["access"], class_id, problem_id)

    assert response.status_code == 400


def test_hide_on_another_instructors_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id, _item_id = _create_open_problem(client, a["access"], class_id)

    response = _hide(client, b["access"], class_id, problem_id)

    assert response.status_code == 404


def test_reopen_on_another_instructors_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id, _item_id = _create_open_problem(client, a["access"], class_id)
    _hide(client, a["access"], class_id, problem_id)

    response = _reopen(client, b["access"], class_id, problem_id)

    assert response.status_code == 404


# --- 강사: 목록·격자에 남는 상태 표시 -----------------------------------------


def test_hidden_problem_stays_in_the_instructor_problem_list_with_its_status(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)

    listing = client.get(f"{CLASSES_URL}/{class_id}/problems", **_auth_header(instructor["access"]))

    assert listing.status_code == 200
    row = next(p for p in listing.json() if p["id"] == problem_id)
    assert row["status"] == Problem.Status.HIDDEN


def test_hidden_problem_stays_in_the_roster_grid_with_its_status(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)

    grid = client.get(f"{CLASSES_URL}/{class_id}/roster-grid", **_auth_header(instructor["access"]))

    assert grid.status_code == 200
    row = next(p for p in grid.json()["problems"] if p["id"] == problem_id)
    assert row["status"] == Problem.Status.HIDDEN


def test_hidden_problems_submissions_remain_visible_to_the_instructor(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)

    submissions = client.get(
        _submissions_url(class_id, problem_id), **_auth_header(instructor["access"])
    )

    assert submissions.status_code == 200
    assert len(submissions.json()) == 1


# --- 참여자 -------------------------------------------------------------------


def test_hidden_problem_is_excluded_from_the_participant_list(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _hide(client, instructor["access"], class_id, problem_id)

    listing = client.get(_mine_list_url(class_id), **_auth_header(participant["access"]))

    assert listing.status_code == 200
    assert listing.json()["problems"] == []


def test_a_participant_who_submitted_still_reaches_the_hidden_problem_read_only(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)

    response = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))

    assert response.status_code == 200
    body = response.json()
    assert len(body["submissions"]) == 1
    assert body["submit_blocked_reason"] == "hidden"


def test_a_participant_who_never_submitted_gets_a_404_for_the_hidden_problem(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _hide(client, instructor["access"], class_id, problem_id)

    response = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))

    assert response.status_code == 404


def test_submission_to_a_hidden_problem_is_rejected(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)

    response = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/again"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "강사가 숨긴 문제라 새로 낼 수 없습니다."


def test_submission_is_accepted_again_after_reopening(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit(client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello")
    _hide(client, instructor["access"], class_id, problem_id)
    _reopen(client, instructor["access"], class_id, problem_id)

    response = _submit(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/again"
    )

    assert response.status_code == 201


def test_reopened_problem_reappears_in_the_participant_list(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _hide(client, instructor["access"], class_id, problem_id)
    _reopen(client, instructor["access"], class_id, problem_id)

    listing = client.get(_mine_list_url(class_id), **_auth_header(participant["access"]))

    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()["problems"]] == [problem_id]


# --- 채점: 문제 상태를 보지 않는다 --------------------------------------------


def test_a_submission_made_before_hiding_is_still_scored_by_the_scan(client, db, monkeypatch):
    """#405 AC "제출 뒤 문제를 숨겨도 그 시도가 스캔에서 끝까지 채점된다" —
    채점 경로가 Problem.status 를 보지 않는다는 것을 스캔 하나로 고정한다."""

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("fake 경로인데 네트워크로 나갔다.")

    monkeypatch.setattr("core.llm_scoring.requests.post", _fail_if_called)

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    # fake 저장소 채점 어댑터는 이 문구가 소스에 등장하는지로 충족을 가른다.
    submitted = _submit(
        client,
        participant["access"],
        class_id,
        problem_id,
        "https://github.com/octocat/fake-clone-marker-pass",
    )
    assert submitted.status_code == 201
    submission_id = submitted.json()["id"]

    _hide(client, instructor["access"], class_id, problem_id)

    scan = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert scan.status_code == 200, scan.content
    assert scan.json()["count"] == 1
    assert scan.json()["rows"][0]["status"] == "scored"

    mine = client.get(_mine_url(class_id, problem_id), **_auth_header(participant["access"]))
    assert mine.status_code == 200
    submission_out = next(
        s for s in mine.json()["submissions"] if s["id"] == submission_id
    )
    assert submission_out["status"] == "scored"


# --- 복사: 원본 상태와 무관하게 초안 -------------------------------------------


def test_copying_a_hidden_problem_lands_as_a_draft(client, db):
    """#405 AC "숨긴 문제를 복사·템플릿으로 가져오면 초안이 된다"."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"], name="원본 클래스")
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)
    _hide(client, instructor["access"], class_id, problem_id)
    target_class_id = _create_class(client, instructor["access"], name="대상 클래스")

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/copy",
        data={"target_class_id": target_class_id},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 201
    assert response.json()["status"] == Problem.Status.DRAFT
