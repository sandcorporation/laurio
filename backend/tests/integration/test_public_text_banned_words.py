"""공개 제목·본문에 욕설을 막는다 — 사칭 목록은 이 자리에 적용하지 않는다
(spec #474, #479).

대상 넷: 공모전 제목·설명(개최·무료 개최·수정), 문제 제목·설명, 클래스
이름, 체크리스트 항목. 이름 필드(#475·#477·#478)와 갈리는 지점이 핵심이다
— 사칭 낱말이 든 제목·본문은 **통과한다**: 「관리자 페이지 만들기」는 정당한
문제 제목이고 「운영자 대시보드」는 정당한 공모전 제목이다
(`core.banned_word_rules.RULES`의 `checks_impersonation=False` 항목들).

HTTP만 친다(이 저장소의 유일한 백엔드 시임) — `core.banned_words`의 판정
함수나 라우터 도우미를 직접 부르지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from classroom.models import Class, Problem
from contests.models import Category, Contest, DeliverableType

CONTESTS_URL = "/api/contests"
CLASSES_URL = "/api/classroom/classes"
ORIGIN = "http://testserver"
PW = "operator-pw-banned-words-4179"


# --- 공용 로그인 헬퍼 ---------------------------------------------------------


def _login(client, uid, email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _operator_client(username, *, superuser=True):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _grant_hosting_permission(operator_client, user_id: int) -> None:
    response = operator_client.post(
        f"/api/operator/hosting-permissions/{user_id}",
        data={"granted": True, "reason": "금칙어 테스트용 개최 권한"},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def category(db):
    return Category.objects.create(name="금칙어 테스트")


@pytest.fixture
def deliverable_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _contest_payload(category, deliverable_type, **overrides):
    payload = {
        "title": "정상 제목",
        "category_id": category.id,
        "deliverable_type_ids": [deliverable_type.id],
        "description": "정상 설명",
        "prize": 1_000_000,
        "deadline_at": "2030-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# --- 공모전 제목·설명 (유료 개최) --------------------------------------------


@pytest.mark.django_db
def test_profane_contest_title_is_rejected_on_paid_create(client, category, deliverable_type):
    pair = _login(client, "sponsor-title-paid")
    _verify(client, pair["access"], "title-paid-ci")

    response = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type, title="씨발 공모전"),
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Contest.objects.exists()


@pytest.mark.django_db
def test_profane_contest_description_is_rejected_on_paid_create(
    client, category, deliverable_type
):
    pair = _login(client, "sponsor-desc-paid")
    _verify(client, pair["access"], "desc-paid-ci")

    response = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type, description="병신 같은 프로젝트"),
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Contest.objects.exists()


@pytest.mark.django_db
def test_impersonation_word_in_contest_title_passes(client, category, deliverable_type):
    """사칭 목록은 공개 제목·본문에 걸지 않는다 — 「운영자 대시보드」는
    정당한 공모전 제목이다(spec #474 Implementation Decisions)."""

    pair = _login(client, "sponsor-title-impersonation")
    _verify(client, pair["access"], "title-impersonation-ci")

    response = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type, title="운영자 대시보드"),
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    assert response.json()["title"] == "운영자 대시보드"


@pytest.mark.django_db
def test_rejection_detail_does_not_echo_the_banned_word(client, category, deliverable_type):
    pair = _login(client, "sponsor-detail-shape")
    _verify(client, pair["access"], "detail-shape-ci")

    response = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type, title="씨발"),
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "씨발" not in detail


# --- 공모전 제목·설명 (무료 개최) --------------------------------------------


@pytest.mark.django_db
def test_profane_contest_title_is_rejected_on_free_create(client, category, deliverable_type):
    pair = _login(client, "sponsor-title-free")
    user = get_user_model().objects.get(email="sponsor-title-free@example.com")
    root = _operator_client("root-title-free")
    _grant_hosting_permission(root, user.id)

    response = client.post(
        f"{CONTESTS_URL}/free",
        data={
            "title": "씨발 무료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "description": "정상 설명",
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Contest.objects.exists()


# --- 공모전 제목·설명 (draft 수정) -------------------------------------------


@pytest.mark.django_db
def test_profane_contest_title_is_rejected_on_update(client, category, deliverable_type):
    pair = _login(client, "sponsor-title-update")
    _verify(client, pair["access"], "title-update-ci")
    created = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type),
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"title": "씨발"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert Contest.objects.get(id=created["id"]).title != "씨발"


@pytest.mark.django_db
def test_profane_contest_description_is_rejected_on_update(client, category, deliverable_type):
    pair = _login(client, "sponsor-desc-update")
    _verify(client, pair["access"], "desc-update-ci")
    created = client.post(
        CONTESTS_URL,
        data=_contest_payload(category, deliverable_type),
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"description": "병신 같은 요구사항"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert Contest.objects.get(id=created["id"]).description != "병신 같은 요구사항"


# --- 클래스 이름 -------------------------------------------------------------


def _classroom_login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.django_db
def test_profane_class_name_is_rejected_on_create(client, db):
    pair = _classroom_login(client, uid="instructor-class-name")

    response = client.post(
        CLASSES_URL,
        data={"name": "씨발 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Class.objects.exists()


@pytest.mark.django_db
def test_impersonation_word_in_class_name_passes(client, db):
    """「운영자 대시보드」와 같은 이유로 클래스 이름도 사칭 목록을 걸지
    않는다."""

    pair = _classroom_login(client, uid="instructor-class-impersonation")

    response = client.post(
        CLASSES_URL,
        data={"name": "관리자 페이지 만들기 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 201
    assert response.json()["name"] == "관리자 페이지 만들기 스터디"


@pytest.mark.django_db
def test_profane_class_name_is_rejected_on_update(client, db):
    pair = _classroom_login(client, uid="instructor-class-name-update")
    class_id = client.post(
        CLASSES_URL,
        data={"name": "정상 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()["id"]

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"name": "병신 스터디"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert Class.objects.get(id=class_id).name == "정상 스터디"


# --- 문제 제목·설명 -----------------------------------------------------------


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.django_db
def test_profane_problem_title_is_rejected_on_create(client, db):
    pair = _classroom_login(client, uid="instructor-problem-title")
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "씨발 문제", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Problem.objects.exists()


@pytest.mark.django_db
def test_profane_problem_description_is_rejected_on_create(client, db):
    pair = _classroom_login(client, uid="instructor-problem-desc")
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "정상 제목",
            "description": "좆같은 설명",
            "submission_formats": ["source"],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Problem.objects.exists()


@pytest.mark.django_db
def test_impersonation_word_in_problem_title_passes(client, db):
    """이 티켓의 핵심 — 사칭 목록은 문제 제목·설명에 걸지 않는다. 「관리자
    페이지 만들기」는 정당한 문제 제목이다(spec #474, #479)."""

    pair = _classroom_login(client, uid="instructor-problem-impersonation")
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "관리자 페이지 만들기", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 201
    assert response.json()["title"] == "관리자 페이지 만들기"


@pytest.mark.django_db
def test_profane_problem_title_is_rejected_on_update(client, db):
    pair = _classroom_login(client, uid="instructor-problem-title-update")
    class_id = _create_class(client, pair["access"])
    problem_id = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "정상 제목", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()["id"]

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"title": "개새끼 문제"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert Problem.objects.get(id=problem_id).title == "정상 제목"


# --- 체크리스트 항목 ----------------------------------------------------------


@pytest.mark.django_db
def test_profane_checklist_item_is_rejected_when_creating_problem(client, db):
    pair = _classroom_login(client, uid="instructor-checklist-inline")
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "정상 제목",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "씨발 항목", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Problem.objects.exists()


@pytest.mark.django_db
def test_profane_checklist_item_is_rejected_on_add(client, db):
    pair = _classroom_login(client, uid="instructor-checklist-add")
    class_id = _create_class(client, pair["access"])
    problem_id = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "정상 제목", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()["id"]

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "병신 항목", "required": True},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert not Problem.objects.get(id=problem_id).checklist_items.exists()


@pytest.mark.django_db
def test_profane_checklist_item_is_rejected_on_update(client, db):
    pair = _classroom_login(client, uid="instructor-checklist-update")
    class_id = _create_class(client, pair["access"])
    problem_id = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "정상 제목",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "원래 항목", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()
    item_id = problem_id["checklist_items"][0]["id"]

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id['id']}/checklist-items/{item_id}",
        data={"label": "좆같은 항목"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
    assert Problem.objects.get(id=problem_id["id"]).checklist_items.get(id=item_id).label == (
        "원래 항목"
    )


@pytest.mark.django_db
def test_impersonation_word_in_checklist_item_passes(client, db):
    """체크리스트 항목도 사칭 목록을 걸지 않는다 — 「관리자 권한을
    부여한다」는 정당한 채점 기준일 수 있다."""

    pair = _classroom_login(client, uid="instructor-checklist-impersonation")
    class_id = _create_class(client, pair["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "정상 제목",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "관리자 권한을 부여한다", "required": True}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 201
    assert response.json()["checklist_items"][0]["label"] == "관리자 권한을 부여한다"
