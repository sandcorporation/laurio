"""문제 하나를 템플릿으로 공개하고 링크로 가져온다 (#316, CONTEXT.md 「강의실」).

핵심 대상: 공개하는 순간 사본이 떠져 원본을 고치거나 지워도 템플릿은
그대로다. 링크를 연 강사가 미리 보고 자기 클래스로 가져오면 체크리스트는
순서 그대로 따라오되 채점 모델은 따라오지 않는다. 참여자·제출물·판정·
가입 코드·OpenAI 키는 애초에 템플릿이 모르는 것들이다. 올린 사람만 내릴 수
있고, 내려도 이미 가져간 사람의 것은 그대로다.
"""

from __future__ import annotations

from classroom.models import Problem, ProblemTemplate

CLASSES_URL = "/api/classroom/classes"
TEMPLATES_URL = "/api/classroom/problem-templates"


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
        data={"name": name, "instructor_display_name": "김강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(
    client, access: str, class_id: int, title: str = "1주차", submission_format: str = "source"
) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_format": submission_format},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _add_item(client, access: str, class_id: int, problem_id: int, label: str, required: bool = True):
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "required": required},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _publish(client, access: str, class_id: int, problem_id: int, publisher_display_name="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def _import(client, access: str, share_code: str, target_class_id: int):
    return client.post(
        f"{TEMPLATES_URL}/{share_code}/import",
        data={"target_class_id": target_class_id},
        content_type="application/json",
        **_auth_header(access),
    )


def test_instructor_publishes_a_problem_as_a_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")
    _add_item(client, pair["access"], class_id, problem_id, "테스트가 통과한다", True)
    _add_item(client, pair["access"], class_id, problem_id, "README가 있다", False)

    response = _publish(client, pair["access"], class_id, problem_id, "김강사")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["title"] == "Todo API"
    assert body["description"] == "설명"
    assert body["submission_format"] == "source"
    assert body["publisher_display_name"] == "김강사"
    assert body["taken_down"] is False
    assert body["share_code"]
    labels_and_required = [(i["label"], i["required"]) for i in body["checklist_items"]]
    assert labels_and_required == [("테스트가 통과한다", True), ("README가 있다", False)]


def test_share_code_is_unguessable_and_unique(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    p1 = _create_problem(client, pair["access"], class_id, "1주차")
    p2 = _create_problem(client, pair["access"], class_id, "2주차")

    r1 = _publish(client, pair["access"], class_id, p1)
    r2 = _publish(client, pair["access"], class_id, p2)
    assert r1.json()["share_code"] != r2.json()["share_code"]
    assert len(r1.json()["share_code"]) >= 16


def test_publishing_someone_elses_problem_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)

    response = _publish(client, b["access"], class_id, problem_id)
    assert response.status_code == 404


def test_editing_the_original_problem_does_not_change_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "원제목")

    published = _publish(client, pair["access"], class_id, problem_id)
    share_code = published.json()["share_code"]

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"title": "고친 제목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.json()["title"] == "원제목"


def test_deleting_the_original_class_leaves_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    published = _publish(client, pair["access"], class_id, problem_id)
    share_code = published.json()["share_code"]

    from classroom.models import Class as ClassModel

    ClassModel.objects.get(id=class_id).delete()

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.status_code == 200
    assert preview.json()["title"]


def test_another_instructor_previews_before_importing(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id, "Todo API")
    _add_item(client, a["access"], class_id, problem_id, "필수 항목", True)
    share_code = _publish(client, a["access"], class_id, problem_id, "김강사").json()["share_code"]

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(b["access"]))
    assert preview.status_code == 200
    body = preview.json()
    assert body["title"] == "Todo API"
    assert body["publisher_display_name"] == "김강사"
    assert [i["label"] for i in body["checklist_items"]] == ["필수 항목"]


def test_preview_requires_login(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]

    response = client.get(f"{TEMPLATES_URL}/{share_code}")
    assert response.status_code == 401


def test_import_creates_a_draft_problem_in_the_target_class(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id, "Todo API", "repository")
    _add_item(client, a["access"], class_id, problem_id, "필수 항목", True)
    _add_item(client, a["access"], class_id, problem_id, "선택 항목", False)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    target_class = _create_class(client, b["access"], "내 클래스")
    response = _import(client, b["access"], share_code, target_class)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["classroom_id"] == target_class
    assert body["title"] == "Todo API"
    assert body["submission_format"] == "repository"
    assert body["status"] == Problem.Status.DRAFT
    labels_and_required = [(i["label"], i["required"]) for i in body["checklist_items"]]
    assert labels_and_required == [("필수 항목", True), ("선택 항목", False)]


def test_import_does_not_carry_the_scoring_model(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4.1-mini"},
        content_type="application/json",
        **_auth_header(a["access"]),
    )
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    target_class = _create_class(client, b["access"])
    client.patch(
        f"{CLASSES_URL}/{target_class}",
        data={"default_model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(b["access"]),
    )
    response = _import(client, b["access"], share_code, target_class)
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == "gpt-4o"


def test_copying_between_own_classes_still_carries_the_scoring_model(client, db):
    """#292의 기존 자기 클래스간 복사 규칙은 이 티켓이 건드리지 않는다 —
    회귀 감시용."""

    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")
    target_class = _create_class(client, pair["access"], "2기")
    problem_id = _create_problem(client, pair["access"], source_class)
    client.patch(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}",
        data={"model": "gpt-4.1-mini"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}/copy",
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.json()["model"] == "gpt-4.1-mini"


def test_import_does_not_carry_members_submissions_scores_join_code_or_key(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    target_class = _create_class(client, b["access"])
    before = client.get(f"{CLASSES_URL}/{target_class}", **_auth_header(b["access"])).json()

    _import(client, b["access"], share_code, target_class)

    members = client.get(f"{CLASSES_URL}/{target_class}/members", **_auth_header(b["access"]))
    assert members.json() == []
    after = client.get(f"{CLASSES_URL}/{target_class}", **_auth_header(b["access"])).json()
    assert after["join_code"] == before["join_code"]
    assert after["has_openai_key"] is False


def test_importing_into_an_archived_class_is_forbidden(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    target_class = _create_class(client, b["access"])
    archived = client.post(f"{CLASSES_URL}/{target_class}/archive", **_auth_header(b["access"]))
    assert archived.status_code == 200

    response = _import(client, b["access"], share_code, target_class)
    assert response.status_code == 403


def test_importing_into_someone_elses_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    other_class = _create_class(client, a["access"], "A의 다른 클래스")
    response = _import(client, b["access"], share_code, other_class)
    assert response.status_code == 404


def test_import_requires_login(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]
    target = _create_class(client, pair["access"], "다른 클래스")

    response = client.post(
        f"{TEMPLATES_URL}/{share_code}/import",
        data={"target_class_id": target},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_owner_takes_down_their_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]

    takedown = client.post(
        f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"])
    )
    assert takedown.status_code == 200
    assert takedown.json()["taken_down"] is True

    # 올린 사람 본인에게는 내려간 뒤에도 보인다 — 「내리기」를 누른 직후
    # 관리 화면 대신 죽은 링크로 튕기면 자기 것을 확인할 길이 없다.
    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.status_code == 200
    assert preview.json()["taken_down"] is True


def test_taken_down_template_is_invisible_to_others(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(a["access"]))

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(b["access"]))
    assert preview.status_code == 404


def test_taking_down_twice_is_idempotent(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]

    first = client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"]))
    second = client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"]))
    assert first.status_code == 200
    assert second.status_code == 200


def test_someone_elses_takedown_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id)
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    response = client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(b["access"]))
    assert response.status_code == 404

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(a["access"]))
    assert preview.status_code == 200


def test_taking_down_does_not_affect_already_imported_problems(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    problem_id = _create_problem(client, a["access"], class_id, "Todo API")
    share_code = _publish(client, a["access"], class_id, problem_id).json()["share_code"]

    target_class = _create_class(client, b["access"])
    imported = _import(client, b["access"], share_code, target_class).json()

    client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(a["access"]))

    still_there = client.get(
        f"{CLASSES_URL}/{target_class}/problems/{imported['id']}", **_auth_header(b["access"])
    )
    assert still_there.status_code == 200
    assert still_there.json()["title"] == "Todo API"


# --- 원본을 기억한다 (#333) ---------------------------------------------------


def test_publishing_the_same_problem_twice_does_not_create_a_new_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")

    first = _publish(client, pair["access"], class_id, problem_id, "김강사")
    assert first.status_code == 201, first.content
    share_code = first.json()["share_code"]

    second = _publish(client, pair["access"], class_id, problem_id, "다른 이름으로")
    assert second.status_code == 200, second.content
    assert second.json()["share_code"] == share_code
    assert second.json()["publisher_display_name"] == "김강사"

    assert ProblemTemplate.objects.filter(source_problem_id=problem_id).count() == 1


def test_publishing_again_after_takedown_creates_a_new_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")

    first = _publish(client, pair["access"], class_id, problem_id)
    first_share_code = first.json()["share_code"]
    client.post(f"{TEMPLATES_URL}/{first_share_code}/takedown", **_auth_header(pair["access"]))

    second = _publish(client, pair["access"], class_id, problem_id)
    assert second.status_code == 201, second.content
    assert second.json()["share_code"] != first_share_code

    assert ProblemTemplate.objects.filter(source_problem_id=problem_id).count() == 2


def test_problem_detail_shows_the_live_published_template_after_reload(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    before = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    ).json()
    assert before["published_template"] is None

    share_code = _publish(client, pair["access"], class_id, problem_id, "김강사").json()["share_code"]

    after = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    ).json()
    assert after["published_template"]["share_code"] == share_code
    assert after["published_template"]["publisher_display_name"] == "김강사"


def test_problem_detail_published_template_is_null_again_after_takedown(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]

    client.post(f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"]))

    after = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    ).json()
    assert after["published_template"] is None


def test_deleting_the_original_problem_clears_the_weak_reference_but_keeps_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")
    share_code = _publish(client, pair["access"], class_id, problem_id).json()["share_code"]

    Problem.objects.get(id=problem_id).delete()

    template = ProblemTemplate.objects.get(share_code=share_code)
    assert template.source_problem_id is None
    assert template.title == "Todo API"

    preview = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.status_code == 200
    assert preview.json()["title"] == "Todo API"
