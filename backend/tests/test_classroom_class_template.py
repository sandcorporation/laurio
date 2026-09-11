"""클래스를 통째로 템플릿으로 공개하고 가져온다 (#319, CONTEXT.md 「강의실」).

핵심 대상: 공개하는 순간 클래스 전체(문제들과 그 순서, 각 문제의 체크리스트)의
사본이 떠져 원본을 고치거나 지워도 템플릿은 그대로다. 가져오면 새 클래스가
생기고 이름을 정할 수 있으며, 그 클래스는 자기만의 새 가입 코드를 갖는다.
참여자·제출물·판정·가입 코드·OpenAI 키·채점 모델은 애초에 템플릿이 모르는
것들이다. #316(문제 템플릿)의 공개·내리기·미리보기·이름 적기 규율을 그대로
따른다.
"""

from __future__ import annotations

from classroom.models import Class, ClassTemplate, Problem

CLASSES_URL = "/api/classroom/classes"
CLASS_TEMPLATES_URL = "/api/classroom/class-templates"
PROBLEM_TEMPLATES_URL = "/api/classroom/problem-templates"


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


def _publish_class(client, access: str, class_id: int, publisher_display_name="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def _import_class(client, access: str, share_code: str, name: str = "가져온 클래스"):
    return client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/import",
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )


def test_instructor_publishes_a_class_as_a_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"], "1학기 웹 스터디")
    p1 = _create_problem(client, pair["access"], class_id, "1주차")
    _add_item(client, pair["access"], class_id, p1, "테스트가 통과한다", True)
    p2 = _create_problem(client, pair["access"], class_id, "2주차")
    _add_item(client, pair["access"], class_id, p2, "README가 있다", False)

    response = _publish_class(client, pair["access"], class_id, "김강사")
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["name"] == "1학기 웹 스터디"
    assert body["publisher_display_name"] == "김강사"
    assert body["taken_down"] is False
    assert body["share_code"]
    assert [p["title"] for p in body["problems"]] == ["1주차", "2주차"]
    assert body["problem_count"] == 2
    week1_labels = [(i["label"], i["required"]) for i in body["problems"][0]["checklist_items"]]
    assert week1_labels == [("테스트가 통과한다", True)]
    week2_labels = [(i["label"], i["required"]) for i in body["problems"][1]["checklist_items"]]
    assert week2_labels == [("README가 있다", False)]


def test_publishing_someone_elses_class_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])

    response = _publish_class(client, b["access"], class_id)
    assert response.status_code == 404


def test_editing_the_original_class_does_not_change_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"], "원래 이름")
    _create_problem(client, pair["access"], class_id, "원제목")

    published = _publish_class(client, pair["access"], class_id)
    share_code = published.json()["share_code"]

    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"name": "고친 이름"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.json()["name"] == "원래 이름"


def test_deleting_the_original_class_leaves_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)
    published = _publish_class(client, pair["access"], class_id)
    share_code = published.json()["share_code"]

    Class.objects.get(id=class_id).delete()

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.status_code == 200
    assert preview.json()["name"]


def test_another_instructor_previews_before_importing(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"], "1학기")
    _create_problem(client, a["access"], class_id, "1주차")
    _create_problem(client, a["access"], class_id, "2주차")
    share_code = _publish_class(client, a["access"], class_id, "김강사").json()["share_code"]

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(b["access"]))
    assert preview.status_code == 200
    body = preview.json()
    assert body["name"] == "1학기"
    assert body["publisher_display_name"] == "김강사"
    assert [p["title"] for p in body["problems"]] == ["1주차", "2주차"]


def test_preview_requires_login(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]

    response = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}")
    assert response.status_code == 401


def test_import_creates_a_new_class_with_a_chosen_name(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"], "원본 클래스")
    p1 = _create_problem(client, a["access"], class_id, "1주차", "repository")
    _add_item(client, a["access"], class_id, p1, "필수 항목", True)
    _add_item(client, a["access"], class_id, p1, "선택 항목", False)
    p2 = _create_problem(client, a["access"], class_id, "2주차")
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    response = _import_class(client, b["access"], share_code, "내가 붙인 이름")
    assert response.status_code == 201, response.content
    new_class = response.json()
    assert new_class["name"] == "내가 붙인 이름"
    assert new_class["id"]

    problems = client.get(
        f"{CLASSES_URL}/{new_class['id']}/problems", **_auth_header(b["access"])
    ).json()
    assert [p["title"] for p in problems] == ["1주차", "2주차"]
    assert all(p["status"] == Problem.Status.DRAFT for p in problems)
    assert problems[0]["submission_format"] == "repository"
    labels_and_required = [(i["label"], i["required"]) for i in problems[0]["checklist_items"]]
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
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    response = _import_class(client, b["access"], share_code)
    new_class_id = response.json()["id"]
    problems = client.get(
        f"{CLASSES_URL}/{new_class_id}/problems", **_auth_header(b["access"])
    ).json()
    assert problems[0]["model"] == ""


def test_import_gets_a_fresh_join_code_and_no_openai_key(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    _create_problem(client, a["access"], class_id)
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    response = _import_class(client, b["access"], share_code)
    new_class = response.json()
    assert new_class["join_code"]
    assert new_class["has_openai_key"] is False

    members = client.get(
        f"{CLASSES_URL}/{new_class['id']}/members", **_auth_header(b["access"])
    )
    assert members.json() == []


def test_importing_by_someone_else_does_not_reuse_the_original_join_code(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    _create_problem(client, a["access"], class_id)
    original = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(a["access"])).json()
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    new_class = _import_class(client, b["access"], share_code).json()
    assert new_class["join_code"] != original["join_code"]


def test_import_requires_login(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]

    response = client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/import",
        data={"name": "새 클래스"},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_owner_takes_down_their_class_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]

    takedown = client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"])
    )
    assert takedown.status_code == 200
    assert takedown.json()["taken_down"] is True

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(pair["access"]))
    assert preview.status_code == 200
    assert preview.json()["taken_down"] is True


def test_taken_down_class_template_is_invisible_to_others(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    _create_problem(client, a["access"], class_id)
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    client.post(f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(a["access"]))

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(b["access"]))
    assert preview.status_code == 404


def test_someone_elses_takedown_of_a_class_template_is_404(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    _create_problem(client, a["access"], class_id)
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    response = client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(b["access"])
    )
    assert response.status_code == 404

    preview = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(a["access"]))
    assert preview.status_code == 200


def test_taking_down_does_not_affect_already_imported_classes(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    _create_problem(client, a["access"], class_id, "Todo API")
    share_code = _publish_class(client, a["access"], class_id).json()["share_code"]

    imported = _import_class(client, b["access"], share_code, "가져온 클래스").json()

    client.post(f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(a["access"]))

    still_there = client.get(
        f"{CLASSES_URL}/{imported['id']}", **_auth_header(b["access"])
    )
    assert still_there.status_code == 200
    assert still_there.json()["name"] == "가져온 클래스"


def test_search_list_is_title_and_recency_only(client, db):
    pair = _login(client)
    class_a = _create_class(client, pair["access"], "파이썬 기초")
    _create_problem(client, pair["access"], class_a)
    class_b = _create_class(client, pair["access"], "자바스크립트 기초")
    _create_problem(client, pair["access"], class_b)
    _publish_class(client, pair["access"], class_a)
    _publish_class(client, pair["access"], class_b)

    response = client.get(
        f"{CLASS_TEMPLATES_URL}?q=파이썬", **_auth_header(pair["access"])
    )
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["파이썬 기초"]


def test_class_templates_and_problem_templates_are_distinguishable(client, db):
    """문제 하나짜리 템플릿과 클래스 템플릿이 목록에서 구별된다(#319 AC) —
    서로 다른 목록 엔드포인트에 산다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"], "묶음 클래스")
    problem_id = _create_problem(client, pair["access"], class_id, "낱개 문제")
    _publish_class(client, pair["access"], class_id)
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    class_templates = client.get(CLASS_TEMPLATES_URL, **_auth_header(pair["access"])).json()
    problem_templates = client.get(PROBLEM_TEMPLATES_URL, **_auth_header(pair["access"])).json()

    assert [item["name"] for item in class_templates["items"]] == ["묶음 클래스"]
    assert [item["title"] for item in problem_templates["items"]] == ["낱개 문제"]


def test_my_class_templates_lists_mine_including_taken_down(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"], "내 클래스")
    _create_problem(client, pair["access"], class_id)
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]
    client.post(f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"]))

    mine = client.get(f"{CLASS_TEMPLATES_URL}/mine", **_auth_header(pair["access"]))
    assert mine.status_code == 200
    assert len(mine.json()) == 1
    assert mine.json()[0]["taken_down"] is True


# --- 원본을 기억한다 (#333) ---------------------------------------------------


def test_publishing_the_same_class_twice_does_not_create_a_new_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"], "1학기 웹 스터디")
    _create_problem(client, pair["access"], class_id)

    first = _publish_class(client, pair["access"], class_id, "김강사")
    assert first.status_code == 201, first.content
    share_code = first.json()["share_code"]

    second = _publish_class(client, pair["access"], class_id, "다른 이름으로")
    assert second.status_code == 200, second.content
    assert second.json()["share_code"] == share_code
    assert second.json()["publisher_display_name"] == "김강사"

    assert ClassTemplate.objects.filter(source_class_id=class_id).count() == 1


def test_publishing_class_again_after_takedown_creates_a_new_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)

    first = _publish_class(client, pair["access"], class_id)
    first_share_code = first.json()["share_code"]
    client.post(f"{CLASS_TEMPLATES_URL}/{first_share_code}/takedown", **_auth_header(pair["access"]))

    second = _publish_class(client, pair["access"], class_id)
    assert second.status_code == 201, second.content
    assert second.json()["share_code"] != first_share_code

    assert ClassTemplate.objects.filter(source_class_id=class_id).count() == 2


def test_class_detail_shows_the_live_published_template_after_reload(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)

    before = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"])).json()
    assert before["published_template"] is None

    share_code = _publish_class(client, pair["access"], class_id, "김강사").json()["share_code"]

    after = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"])).json()
    assert after["published_template"]["share_code"] == share_code
    assert after["published_template"]["publisher_display_name"] == "김강사"


def test_class_detail_published_template_is_null_again_after_takedown(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _create_problem(client, pair["access"], class_id)
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]

    client.post(f"{CLASS_TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"]))

    after = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"])).json()
    assert after["published_template"] is None


def test_deleting_the_original_class_clears_the_weak_reference_but_keeps_the_template(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"], "1학기 웹 스터디")
    _create_problem(client, pair["access"], class_id)
    share_code = _publish_class(client, pair["access"], class_id).json()["share_code"]

    Class.objects.get(id=class_id).delete()

    template = ClassTemplate.objects.get(share_code=share_code)
    assert template.source_class_id is None
    assert template.name == "1학기 웹 스터디"
