"""템플릿을 내릴 수 있는 사람은 공개한 사람뿐이다 — 요약이 그 사실을 내려 준다(#1446).

공개자가 아닌 강사(소유자 포함)에게 화면이 「내리기」를 보이면 눌렀을 때 404 다. 규칙(공개자만 내린다)은
그대로 두고, 클래스·문제 상세의 `published_template.can_take_down` 이 부른 사람에 맞춰 내려간다.
"""

from __future__ import annotations

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    auth_header,
    create_class,
    login,
)


def _problem(client, access, class_id) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "description": "설명", "submission_formats": ["source"]},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _post(client, access, url, data=None):
    return client.post(url, data=data or {}, content_type="application/json", **auth_header(access))


def test_problem_template_only_publisher_can_take_down(client, db):
    owner = login(client, "instructor-1")
    co = login(client, "instructor-2")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    problem_id = _problem(client, owner["access"], class_id)
    published = _post(
        client,
        co["access"],
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        {"publisher_display_name": "공동강사"},
    )
    assert published.status_code in (200, 201)
    assert published.json()["is_mine"] is True

    def summary(access):
        problems = client.get(f"{CLASSES_URL}/{class_id}/problems", **auth_header(access)).json()
        detail = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **auth_header(access))
        assert detail.status_code == 200
        assert detail.json()["published_template"] == problems[0]["published_template"] | {}
        return detail.json()["published_template"]

    assert summary(co["access"])["can_take_down"] is True
    assert summary(owner["access"])["can_take_down"] is False
    assert summary(owner["access"])["publisher_display_name"] == "공동강사"


def test_class_template_only_publisher_can_take_down(client, db):
    owner = login(client, "instructor-1")
    co = login(client, "instructor-2")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    _problem(client, owner["access"], class_id)
    published = _post(
        client,
        co["access"],
        f"{CLASSES_URL}/{class_id}/publish-template",
        {"publisher_display_name": "공동강사"},
    )
    assert published.status_code in (200, 201)

    def summary(access):
        response = client.get(f"{CLASSES_URL}/{class_id}", **auth_header(access))
        assert response.status_code == 200
        return response.json()["published_template"]

    assert summary(co["access"])["can_take_down"] is True
    assert summary(owner["access"])["can_take_down"] is False
