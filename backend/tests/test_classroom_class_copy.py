"""클래스 복사 — 지난 기수로 다음 기수를 연다 (#293, CONTEXT.md 「강의실」).

핵심 대상: 강사가 클래스를 복사해 새 클래스를 연다. 문제와 체크리스트와
채점 설정(클래스 기본 모델·문제별 덮어쓰기)이 순서 그대로 따라온다.
참여자·제출물·Score·달성률은 이 티켓 범위에 없는 모델들이라 자연히
따라오지 않는다(`ClassMember`·`Submission`이 아직 없다, #279~#281/
#286~#290). 복사본과 원본이 독립이다. OpenAI 키는 강사 본인의 결제
수단이지 「채점 설정」이 아니므로 따라오지 않는다 — 애초에 저장 뒤에는
평문을 다시 볼 방법이 없다(#284). 이름은 원본과 같지 않다(`" 사본"`을
붙인다, #339) — 목록과 문제 복사 대상 목록에서 둘을 구별해야 한다.
"""

from __future__ import annotations

from classroom.models import Class, Problem

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


def _create_problem(
    client, access: str, class_id: int, title: str = "1주차", submission_format: str = "source"
) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "description": "설명", "submission_formats": [submission_format]},
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


def _copy_class_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/copy"


def test_instructor_copies_a_class_with_problems_and_checklists_in_order(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")

    p1 = _create_problem(client, pair["access"], source_class, "1주차")
    _add_item(client, pair["access"], source_class, p1, "테스트가 통과한다", True)
    _add_item(client, pair["access"], source_class, p1, "README가 있다", False)
    p2 = _create_problem(client, pair["access"], source_class, "2주차")
    _add_item(client, pair["access"], source_class, p2, "배포됐다", True)

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    body = response.json()
    assert body["id"] != source_class
    assert body["name"] == "1기 사본"

    listing = client.get(f"{CLASSES_URL}/{body['id']}/problems", **_auth_header(pair["access"]))
    problems = listing.json()
    assert [p["title"] for p in problems] == ["1주차", "2주차"]
    assert [p["order"] for p in problems] == [0, 1]
    assert [i["label"] for i in problems[0]["checklist_items"]] == ["테스트가 통과한다", "README가 있다"]
    assert [i["label"] for i in problems[1]["checklist_items"]] == ["배포됐다"]


def test_copied_problems_are_always_drafts_even_if_originals_were_open(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"])
    p1 = _create_problem(client, pair["access"], source_class)
    _add_item(client, pair["access"], source_class, p1, "테스트가 통과한다", True)
    opened = client.post(
        f"{CLASSES_URL}/{source_class}/problems/{p1}/open", **_auth_header(pair["access"])
    )
    assert opened.status_code == 200

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    new_class_id = response.json()["id"]

    listing = client.get(f"{CLASSES_URL}/{new_class_id}/problems", **_auth_header(pair["access"]))
    assert listing.json()[0]["status"] == Problem.Status.DRAFT


def test_copied_class_carries_the_default_scoring_model_but_not_the_openai_key(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"])
    client.patch(
        f"{CLASSES_URL}/{source_class}",
        data={"default_model": "gpt-4.1-mini"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    client.put(
        f"{CLASSES_URL}/{source_class}/openai-key",
        data={"api_key": "sk-test-1234"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    body = response.json()
    assert body["default_model"] == "gpt-4.1-mini"
    assert body["has_openai_key"] is False
    assert body["openai_key_masked"] is None

    stored = Class.objects.get(id=body["id"])
    assert stored.openai_api_key_encrypted == ""


def test_copy_is_independent_from_the_original(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"])
    p1 = _create_problem(client, pair["access"], source_class, "1주차")
    item_id = _add_item(client, pair["access"], source_class, p1, "테스트가 통과한다", True)

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    new_class_id = response.json()["id"]
    copied_listing = client.get(
        f"{CLASSES_URL}/{new_class_id}/problems", **_auth_header(pair["access"])
    )
    copied_problem = copied_listing.json()[0]
    assert copied_problem["id"] != p1
    copied_item = copied_problem["checklist_items"][0]
    assert copied_item["id"] != item_id

    client.patch(
        f"{CLASSES_URL}/{new_class_id}/problems/{copied_problem['id']}",
        data={"title": "고친 제목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    client.patch(
        f"{CLASSES_URL}/{new_class_id}/problems/{copied_problem['id']}/checklist-items/{copied_item['id']}",
        data={"label": "고친 항목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    original = client.get(
        f"{CLASSES_URL}/{source_class}/problems/{p1}", **_auth_header(pair["access"])
    )
    assert original.json()["title"] == "1주차"
    assert original.json()["checklist_items"][0]["label"] == "테스트가 통과한다"


def test_copied_class_carries_the_instructor_display_name(client, db):
    pair = _login(client)
    source_class_response = client.post(
        CLASSES_URL,
        data={"name": "1기", "instructor_display_name": "김강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    source_class = source_class_response.json()["id"]

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    assert response.json()["instructor_display_name"] == "김강사"


def test_copied_class_name_is_distinguishable_from_the_original(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "3기")

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    assert response.json()["name"] != "3기"

    listing = client.get(CLASSES_URL, **_auth_header(pair["access"]))
    names = [c["name"] for c in listing.json()]
    assert names.count("3기") == 1


def test_copying_a_class_with_a_name_at_the_length_limit_does_not_overflow(client, db):
    pair = _login(client)
    long_name = "가" * 200
    source_class = _create_class(client, pair["access"], long_name)

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    body = response.json()
    assert len(body["name"]) <= 200
    assert body["name"].endswith(" 사본")
    assert body["name"] != long_name


def test_copying_a_class_with_no_problems_works(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "빈 클래스")

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    assert response.status_code == 201
    assert response.json()["name"] == "빈 클래스 사본"

    listing = client.get(
        f"{CLASSES_URL}/{response.json()['id']}/problems", **_auth_header(pair["access"])
    )
    assert listing.json() == []


def test_cannot_copy_someone_elses_class(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    source_class = _create_class(client, a["access"])

    response = client.post(_copy_class_url(source_class), **_auth_header(b["access"]))
    assert response.status_code == 404


def test_copying_a_nonexistent_class_is_404(client, db):
    pair = _login(client)
    response = client.post(_copy_class_url(999999), **_auth_header(pair["access"]))
    assert response.status_code == 404


def test_the_new_class_belongs_to_the_copying_instructor_and_appears_in_their_list(client, db):
    pair = _login(client)
    source_class = _create_class(client, pair["access"], "1기")

    response = client.post(_copy_class_url(source_class), **_auth_header(pair["access"]))
    new_class_id = response.json()["id"]

    listing = client.get(CLASSES_URL, **_auth_header(pair["access"]))
    ids = [c["id"] for c in listing.json()]
    assert source_class in ids
    assert new_class_id in ids
