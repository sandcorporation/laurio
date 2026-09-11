"""문제를 만들면서 채점 모델을 함께 고른다 (#327, 부모 #312).

모델은 #285 가 만들었지만 **편집 화면에만** 있었다 — 만들고 다시 들어가야
고칠 수 있었다. 마크다운 에디터(#324)로 긴 설명을 쉽게 쓰게 되면서 그 왕복이
더 자주 물린다: 안 고르면 클래스 기본값이고 기본값은 가장 작은 컨텍스트라,
긴 설명이 뒷부분부터 잘린 채 채점된다.

핵심 대상: **만들기 요청 하나**가 문제·체크리스트·모델을 함께 만든다. 모델만
따로 저장하는 두 번째 요청이 생기지 않는다는 뜻이다.
"""

from __future__ import annotations

from classroom.models import Problem
from classroom.scoring_models import DEFAULT_SCORING_MODEL

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


def _create_problem(client, access: str, class_id: int, **overrides):
    payload = {
        "title": "3주차 — 서버와 붙이기",
        "description": "긴 설명",
        "submission_format": "source",
    }
    payload.update(overrides)
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


def test_a_problem_can_pick_its_scoring_model_while_being_created(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id, model="gpt-4.1")

    assert response.status_code == 201
    body = response.json()
    assert body["model"] == "gpt-4.1"
    assert body["effective_model"] == "gpt-4.1"
    assert Problem.objects.get(pk=body["id"]).model == "gpt-4.1"


def test_not_picking_a_model_keeps_following_the_class_default(client, db):
    """기존 동작이 바뀌지 않는다 — 이 필드는 순수한 추가다."""

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id)

    assert response.status_code == 201
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == DEFAULT_SCORING_MODEL


def test_an_explicitly_empty_model_also_follows_the_class_default(client, db):
    """화면의 「클래스 기본값을 따릅니다」가 보내는 값이 빈 문자열이다."""

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id, model="")

    assert response.status_code == 201
    assert response.json()["model"] == ""
    assert response.json()["effective_model"] == DEFAULT_SCORING_MODEL


def test_an_unknown_model_is_refused_and_the_problem_is_not_created(client, db):
    """편집 화면의 거절과 같은 규칙이고, 거절되면 문제도 남지 않는다."""

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id, model="gpt-9-imaginary")

    assert response.status_code == 422
    assert "gpt-9-imaginary" in response.json()["detail"]
    assert Problem.objects.filter(classroom_id=class_id).count() == 0


def test_the_model_rides_the_same_request_as_the_checklist_and_opening(client, db):
    """세 가지가 한 요청에서 함께 성립한다 — 모델만 따로 저장하는 두 번째
    요청이 생기지 않는다는 것이 이 티켓의 요구다."""

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(
        client,
        access,
        class_id,
        model="gpt-4.1-mini",
        checklist_items=[{"label": "목록을 받아온다", "required": True}],
        open=True,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["model"] == "gpt-4.1-mini"
    assert body["status"] == Problem.Status.OPEN
    assert [item["label"] for item in body["checklist_items"]] == ["목록을 받아온다"]


def test_a_rejected_model_does_not_leave_checklist_items_behind(client, db):
    """검증이 트랜잭션보다 앞선다 — 「실패하면 문제도 안 생긴다」(#315)가
    이 필드에도 그대로 적용된다."""

    from classroom.models import ChecklistItem

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(
        client,
        access,
        class_id,
        model="nope",
        checklist_items=[{"label": "항목", "required": True}],
    )

    assert response.status_code == 422
    assert Problem.objects.filter(classroom_id=class_id).count() == 0
    assert ChecklistItem.objects.count() == 0
