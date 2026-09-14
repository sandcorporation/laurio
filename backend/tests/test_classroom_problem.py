"""Problem — 문제를 만들고 목록에서 본다 (#282, CONTEXT.md 「강의실」, ADR-0039).

핵심 대상: 강사가 문제를 만들고 고치며, 마감 필드는 애초에 없다. 제출 형식은
소스·저장소 둘 중 하나. 클래스 상세에 문제가 순서대로 서고 순서를 바꿀 수
있다. 초안과 열린 문제가 모델 수준에서 구별된다 — 초안에서 열림으로의 전이와
그 전이가 요구하는 체크리스트 조건은 #283이 붙인다.

`ClassMember`(가입)가 아직 없어(#279/#280) 참여자 열람은 이 티켓의 범위 밖이다
— 강사가 아닌 요청은 클래스 자체가 없는 것으로 취급한다(#278과 같은 404).
"""

from __future__ import annotations

from classroom.models import Problem

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


def test_instructor_creates_a_problem_with_source_or_repository_format(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차 — Todo API",
            "description": "REST API를 만든다",
            "submission_formats": ["source"],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "1주차 — Todo API"
    assert body["submission_formats"] == ["source"]
    assert body["status"] == Problem.Status.DRAFT
    assert "deadline_at" not in body
    assert "deadline" not in body


def test_unknown_submission_format_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["demo_url"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_empty_submission_formats_is_rejected(client, db):
    """#373 AC — 빈 목록은 「제출할 방법이 없는 문제」라 만들 수 없다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": []},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_instructor_opens_a_problem_to_both_formats(client, db):
    """#373 AC — zip·GitHub 둘 다 켠 문제를 만들 수 있다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository", "source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    # 저장 순서는 입력 순서가 아니라 정해진 순서(소스·저장소)를 따른다 —
    # 화면이 언제나 같은 순서로 체크박스를 그리게 한다.
    assert response.json()["submission_formats"] == ["source", "repository"]


def test_patching_a_problem_to_an_empty_format_list_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = created.json()["id"]

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"submission_formats": []},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422
    # 거절됐으니 원래 값이 그대로 남는다.
    assert Problem.objects.get(id=problem_id).submission_formats == ["source"]


def test_instructor_edits_title_description_and_format(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = created.json()["id"]

    patched = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"title": "1주차 — 수정", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["title"] == "1주차 — 수정"
    assert body["submission_formats"] == ["repository"]


def test_description_round_trips_as_markdown_verbatim_and_unsanitized(client, db):
    """설명이 마크다운으로 그려지려면(#313) 저장·응답 양쪽이 원문을 건드리지
    않아야 한다 — 태그를 걷어내면 코드블록 안의 예시 HTML도 함께 사라진다
    (ADR-0012 개정). 채점 LLM이 보는 값과 화면이 받는 값이 같다는 것도 이
    라운드트립 하나로 같이 고정된다."""
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    markdown = (
        "# 제목\n\n**굵게** 그리고 `<b>escape 안 됨</b>` 코드.\n\n"
        "```html\n<script>alert(1)</script>\n```\n\n"
        "- 목록1\n- 목록2\n\n[링크](https://codemit.example)"
    )

    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "마크다운 문제", "description": markdown, "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201
    assert created.json()["description"] == markdown

    problem_id = created.json()["id"]
    fetched = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        **_auth_header(pair["access"]),
    )
    assert fetched.status_code == 200
    assert fetched.json()["description"] == markdown


def test_problems_are_ordered_and_reorderable(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    ids = []
    for title in ["1주차", "2주차", "3주차"]:
        created = client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data={"title": title, "submission_formats": ["source"]},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )
        ids.append(created.json()["id"])

    listing = client.get(f"{CLASSES_URL}/{class_id}/problems", **_auth_header(pair["access"]))
    assert [p["id"] for p in listing.json()] == ids

    reordered = client.post(
        f"{CLASSES_URL}/{class_id}/problems/reorder",
        data={"problem_ids": [ids[2], ids[0], ids[1]]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert reordered.status_code == 200
    assert [p["id"] for p in reordered.json()] == [ids[2], ids[0], ids[1]]

    listing_again = client.get(f"{CLASSES_URL}/{class_id}/problems", **_auth_header(pair["access"]))
    assert [p["id"] for p in listing_again.json()] == [ids[2], ids[0], ids[1]]


def test_reorder_rejects_a_mismatched_problem_set(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = created.json()["id"]

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/reorder",
        data={"problem_ids": [problem_id, 999999]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_new_problems_default_to_draft_and_status_is_a_distinct_field(client, db):
    """초안과 열림이 모델 수준에서 구별된다는 것의 최소 증거 — 전이 자체는
    체크리스트가 붙는 #283에서 검증한다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.json()["status"] == Problem.Status.DRAFT

    stored = Problem.objects.get(id=created.json()["id"])
    assert stored.status == Problem.Status.DRAFT
    assert {choice for choice, _label in Problem.Status.choices} == {"draft", "open", "hidden"}


def test_instructor_reads_a_single_problem(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "description": "설명", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = created.json()["id"]

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    assert response.status_code == 200
    assert response.json()["title"] == "1주차"


def test_a_non_instructor_cannot_see_another_classs_problems(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(a["access"]),
    )

    response = client.get(f"{CLASSES_URL}/{class_id}/problems", **_auth_header(b["access"]))
    assert response.status_code == 404
