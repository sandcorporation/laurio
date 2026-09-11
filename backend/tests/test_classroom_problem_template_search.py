"""공개된 템플릿을 목록에서 찾는다 — 제목 검색과 최신순 (#318, CONTEXT.md 「강의실」).

핵심 대상: 제목 검색과 최신순뿐이고(분류 체계 없음), 내려진 템플릿은 나오지
않으며, 로그인 없이는 목록에 닿을 수 없다. 항목이 많아져도 한 번에 전부
내려받지 않는다(페이지네이션).
"""

from __future__ import annotations

TEMPLATES_URL = "/api/classroom/problem-templates"
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
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(client, access: str, class_id: int, title: str) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _publish(client, access: str, class_id: int, problem_id: int, publisher_display_name="김강사"):
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/publish-template",
        data={"publisher_display_name": publisher_display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def test_list_is_empty_when_no_templates_exist(client, db):
    pair = _login(client)
    response = client.get(TEMPLATES_URL, **_auth_header(pair["access"]))
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["count"] == 0


def test_list_defaults_to_newest_first(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    p1 = _create_problem(client, pair["access"], class_id, "1주차")
    p2 = _create_problem(client, pair["access"], class_id, "2주차")
    _publish(client, pair["access"], class_id, p1)
    _publish(client, pair["access"], class_id, p2)

    response = client.get(TEMPLATES_URL, **_auth_header(pair["access"]))
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["2주차", "1주차"]


def test_list_shows_title_publisher_and_date(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")
    _publish(client, pair["access"], class_id, problem_id, "박강사")

    response = client.get(TEMPLATES_URL, **_auth_header(pair["access"]))
    item = response.json()["items"][0]
    assert item["title"] == "Todo API"
    assert item["publisher_display_name"] == "박강사"
    assert item["created_at"]
    assert item["share_code"]


def test_search_by_title(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    p1 = _create_problem(client, pair["access"], class_id, "Todo API 만들기")
    p2 = _create_problem(client, pair["access"], class_id, "체스 엔진")
    _publish(client, pair["access"], class_id, p1)
    _publish(client, pair["access"], class_id, p2)

    response = client.get(TEMPLATES_URL, {"q": "Todo"}, **_auth_header(pair["access"]))
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Todo API 만들기"]


def test_taken_down_templates_do_not_appear(client, db):
    pair = _login(client)
    other = _login(client, uid="instructor-other")
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id, "Todo API")
    share_code = _publish(client, pair["access"], class_id, problem_id)["share_code"]

    client.post(
        f"{TEMPLATES_URL}/{share_code}/takedown", **_auth_header(pair["access"])
    )

    response = client.get(TEMPLATES_URL, **_auth_header(other["access"]))
    assert response.json()["items"] == []

    # 남에게는 링크로도 열리지 않는다 — 올린 사람 본인은 예외다(별도로
    # test_classroom_problem_template.py의 test_owner_takes_down_their_template
    # 가 고정한다).
    direct = client.get(f"{TEMPLATES_URL}/{share_code}", **_auth_header(other["access"]))
    assert direct.status_code == 404


def test_list_requires_login(client, db):
    response = client.get(TEMPLATES_URL)
    assert response.status_code == 401


def test_list_is_paginated(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    for i in range(25):
        problem_id = _create_problem(client, pair["access"], class_id, f"문제 {i}")
        _publish(client, pair["access"], class_id, problem_id)

    first_page = client.get(TEMPLATES_URL, **_auth_header(pair["access"]))
    body = first_page.json()
    assert body["count"] == 25
    assert len(body["items"]) < 25

    second_page = client.get(TEMPLATES_URL, {"page": 2}, **_auth_header(pair["access"]))
    second_items = second_page.json()["items"]
    assert second_items
    assert {i["share_code"] for i in body["items"]}.isdisjoint(
        {i["share_code"] for i in second_items}
    )
