"""복사·템플릿이 채점 지침을 옮긴다 (#389, 부모 #385, CONTEXT.md 「채점 지침」).

핵심 대상: 문제 복사, 클래스 복사, 문제 템플릿의 공개·가져오기, 클래스
템플릿의 공개·가져오기 — 여섯 경로 모두 채점 지침(단계·직접 입력 문장)을
그대로 옮긴다. 채점 모델과 달리 지침은 "무엇을 통과로 볼지"의 일부라 함께
옮겨야 한다(#385 Implementation Decisions). 두 템플릿 미리보기 응답에도
문제별 채점 지침이 실린다.
"""

from __future__ import annotations

from classroom.models import Class, Problem, ProblemTemplate

CLASSES_URL = "/api/classroom/classes"
PROBLEM_TEMPLATES_URL = "/api/classroom/problem-templates"
CLASS_TEMPLATES_URL = "/api/classroom/class-templates"


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


def _create_problem(client, access: str, class_id: int, **overrides) -> int:
    payload = {
        "title": "1주차",
        "description": "설명",
        "submission_formats": ["source"],
    }
    payload.update(overrides)
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


CUSTOM_SENTENCE = "함수 이름은 solve 여야 하지만 출력 형식은 자유롭게 판정한다."


def test_copying_a_problem_preserves_a_preset_guideline(client, db):
    access = _login(client)["access"]
    source_class = _create_class(client, access, "1기")
    target_class = _create_class(client, access, "2기")
    problem_id = _create_problem(client, access, source_class, grading_strictness="strict")

    response = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}/copy",
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "strict"
    assert body["grading_guideline_text"] == ""


def test_copying_a_problem_preserves_a_custom_guideline(client, db):
    access = _login(client)["access"]
    source_class = _create_class(client, access, "1기")
    target_class = _create_class(client, access, "2기")
    problem_id = _create_problem(
        client, access, source_class, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )

    response = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{problem_id}/copy",
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == CUSTOM_SENTENCE


def test_copying_a_class_preserves_each_problems_guideline(client, db):
    access = _login(client)["access"]
    source_class = _create_class(client, access, "1기")
    _create_problem(
        client, access, source_class, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )

    response = client.post(
        f"{CLASSES_URL}/{source_class}/copy", content_type="application/json", **_auth_header(access)
    )

    assert response.status_code == 201
    new_class_id = response.json()["id"]
    copied = Class.objects.get(pk=new_class_id).problems.get()
    assert copied.grading_strictness == "custom"
    assert copied.grading_guideline_text == CUSTOM_SENTENCE


def _publish_problem_template(client, access, class_id, problem_id, publisher_display_name="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def test_publishing_a_problem_template_preserves_the_guideline(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )

    response = _publish_problem_template(client, access, class_id, problem_id)

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == CUSTOM_SENTENCE


def test_the_problem_template_preview_shows_the_guideline(client, db):
    """두 템플릿 미리보기 응답에 문제별 채점 지침이 실린다(#389 AC)."""

    publisher = _login(client, uid="instructor-1")
    class_id = _create_class(client, publisher["access"])
    problem_id = _create_problem(client, publisher["access"], class_id, grading_strictness="lenient")
    share_code = _publish_problem_template(
        client, publisher["access"], class_id, problem_id
    ).json()["share_code"]

    viewer = _login(client, uid="instructor-2")
    response = client.get(
        f"{PROBLEM_TEMPLATES_URL}/{share_code}", **_auth_header(viewer["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grading_strictness"] == "lenient"
    assert body["grading_guideline_text"] == ""


def test_importing_a_problem_template_preserves_the_guideline(client, db):
    publisher = _login(client, uid="instructor-1")
    class_id = _create_class(client, publisher["access"])
    problem_id = _create_problem(
        client, publisher["access"], class_id, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )
    share_code = _publish_problem_template(
        client, publisher["access"], class_id, problem_id
    ).json()["share_code"]

    importer = _login(client, uid="instructor-2")
    target_class = _create_class(client, importer["access"], "가져간 클래스")
    response = client.post(
        f"{PROBLEM_TEMPLATES_URL}/{share_code}/import",
        data={"target_class_id": target_class},
        content_type="application/json",
        **_auth_header(importer["access"]),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == CUSTOM_SENTENCE
    assert Problem.objects.get(pk=body["id"]).grading_guideline_text == CUSTOM_SENTENCE


def _publish_class_template(client, access, class_id, publisher_display_name="김강사"):
    return client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )


def test_publishing_a_class_template_preserves_each_problems_guideline(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )

    response = _publish_class_template(client, access, class_id)

    assert response.status_code == 201
    body = response.json()
    assert body["problems"][0]["grading_strictness"] == "custom"
    assert body["problems"][0]["grading_guideline_text"] == CUSTOM_SENTENCE


def test_the_class_template_preview_shows_each_problems_guideline(client, db):
    """두 템플릿 미리보기 응답에 문제별 채점 지침이 실린다(#389 AC)."""

    publisher = _login(client, uid="instructor-1")
    class_id = _create_class(client, publisher["access"])
    _create_problem(client, publisher["access"], class_id, grading_strictness="strict")
    share_code = _publish_class_template(client, publisher["access"], class_id).json()["share_code"]

    viewer = _login(client, uid="instructor-2")
    response = client.get(f"{CLASS_TEMPLATES_URL}/{share_code}", **_auth_header(viewer["access"]))

    assert response.status_code == 200
    assert response.json()["problems"][0]["grading_strictness"] == "strict"


def test_importing_a_class_template_preserves_each_problems_guideline(client, db):
    publisher = _login(client, uid="instructor-1")
    class_id = _create_class(client, publisher["access"])
    _create_problem(
        client, publisher["access"], class_id, grading_strictness="custom", grading_guideline_text=CUSTOM_SENTENCE
    )
    share_code = _publish_class_template(client, publisher["access"], class_id).json()["share_code"]

    importer = _login(client, uid="instructor-2")
    response = client.post(
        f"{CLASS_TEMPLATES_URL}/{share_code}/import",
        data={"name": "가져간 클래스"},
        content_type="application/json",
        **_auth_header(importer["access"]),
    )

    assert response.status_code == 201
    new_class_id = response.json()["id"]
    imported_problem = Class.objects.get(pk=new_class_id).problems.get()
    assert imported_problem.grading_strictness == "custom"
    assert imported_problem.grading_guideline_text == CUSTOM_SENTENCE


def test_importing_does_not_carry_a_stale_guideline_if_the_original_changes_later(client, db):
    """템플릿은 공개 시점의 사본이다 — 원본을 나중에 고쳐도 이미 공개된
    템플릿(과 그 뒤의 가져오기)은 그대로다(모델 docstring과 같은 불변식)."""

    publisher = _login(client, uid="instructor-1")
    class_id = _create_class(client, publisher["access"])
    problem_id = _create_problem(client, publisher["access"], class_id, grading_strictness="normal")
    share_code = _publish_problem_template(
        client, publisher["access"], class_id, problem_id
    ).json()["share_code"]

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"grading_strictness": "strict"},
        content_type="application/json",
        **_auth_header(publisher["access"]),
    )

    template = ProblemTemplate.objects.get(share_code=share_code)
    assert template.grading_strictness == "normal"
