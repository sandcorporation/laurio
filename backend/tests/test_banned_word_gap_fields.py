"""#480의 구조 검사가 찾아낸, 앞선 티켓들이 빠뜨린 실제 검사 대상 여덟
(spec #474).

`core.banned_word_rules` 모듈 docstring이 경위를 적는다 — 이미 검사하는
필드(이름·공개 제목/본문)와 같은 범주인데 어느 티켓에도 없던 자리를 규칙
표를 채우다가 찾았다. 면제로 덮지 않고 실제 검사를 걸었다: 클래스 템플릿을
가져올 때 새로 붙이는 이름, 채점 지침 "custom" 문장(만들 때·고칠 때),
공모전 요구사항 문구(만들 때 인라인·따로 추가·수정), 개최자·개발자 공개
소개글.

HTTP만 친다(이 저장소의 유일한 백엔드 시임) — `core.banned_words`의 판정
함수나 라우터 도우미를 직접 부르지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from classroom.models import Problem
from contests.models import Category, Contest, DeliverableType, Requirement

CLASSES_URL = "/api/classroom/classes"
CONTESTS_URL = "/api/contests"
SPONSOR_URL = "/api/accounts/sponsor-profile"
DEVELOPER_URL = "/api/accounts/developer-profile"
ORIGIN = "http://testserver"
PW = "operator-pw-banned-words-gap-480"

pytestmark = pytest.mark.django_db


# --- 공용 헬퍼 ---------------------------------------------------------------


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


def _operator_client(username: str):
    from django.core.management import call_command

    call_command("create_operator", username, password=PW, superuser=True)
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
        data={"granted": True, "reason": "금칙어 gap 테스트용 개최 권한"},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def _create_free_contest(client, access: str, category, deliverable_type, **overrides) -> dict:
    payload = {
        "title": "정상 제목",
        "category_id": category.id,
        "deliverable_type_ids": [deliverable_type.id],
        "description": "정상 설명",
        "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
        "requirements": [],
    }
    payload.update(overrides)
    return client.post(
        f"{CONTESTS_URL}/free",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


@pytest.fixture
def category(db):
    return Category.objects.create(name="금칙어 gap 테스트")


@pytest.fixture
def deliverable_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


@pytest.fixture
def hosting_user(client, db):
    pair = _login(client, "sponsor-gap-480")
    user = get_user_model().objects.get(email="sponsor-gap-480@example.com")
    root = _operator_client("root-gap-480")
    _grant_hosting_permission(root, user.id)
    return pair


# --- 클래스 템플릿을 가져올 때 붙이는 새 이름 --------------------------------


def test_profane_name_is_rejected_on_class_template_import(client):
    instructor = _login(client, "instructor-import-gap")
    class_id = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "description": "", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    published = client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": "강사"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert published.status_code == 201, published.content
    share_code = published.json()["share_code"]

    response = client.post(
        f"/api/classroom/class-templates/{share_code}/import",
        data={"name": "씨발 클래스"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 422
    assert "씨발" not in response.json()["detail"]


def test_legitimate_name_passes_on_class_template_import(client):
    instructor = _login(client, "instructor-import-gap-ok")
    class_id = _create_class(client, instructor["access"])
    client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "description": "", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    published = client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": "강사"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    share_code = published.json()["share_code"]

    response = client.post(
        f"/api/classroom/class-templates/{share_code}/import",
        data={"name": "가져온 클래스"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 201
    assert response.json()["name"] == "가져온 클래스"


# --- 채점 지침 "custom" 문장 --------------------------------------------------


def test_profane_grading_guideline_is_rejected_on_create(client):
    instructor = _login(client, "instructor-guideline-gap")
    class_id = _create_class(client, instructor["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "description": "",
            "submission_formats": ["source"],
            "grading_strictness": "custom",
            "grading_guideline_text": "씨발 대충 하지 마라",
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 422
    assert "씨발" not in response.json()["detail"]
    assert not Problem.objects.filter(classroom_id=class_id).exists()


def test_profane_grading_guideline_is_rejected_on_update(client):
    instructor = _login(client, "instructor-guideline-gap-update")
    class_id = _create_class(client, instructor["access"])
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "description": "",
            "submission_formats": ["source"],
            "grading_strictness": "custom",
            "grading_guideline_text": "정상 지침 문장",
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert created.status_code == 201, created.content
    problem_id = created.json()["id"]

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"grading_guideline_text": "병신 같은 소리 하지 마라"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 422
    problem = Problem.objects.get(id=problem_id)
    assert problem.grading_guideline_text == "정상 지침 문장"


def test_legitimate_grading_guideline_passes(client):
    instructor = _login(client, "instructor-guideline-gap-ok")
    class_id = _create_class(client, instructor["access"])

    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={
            "title": "1주차",
            "description": "",
            "submission_formats": ["source"],
            "grading_strictness": "custom",
            "grading_guideline_text": "테스트 커버리지를 꼼꼼히 본다",
        },
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert response.status_code == 201
    assert response.json()["grading_guideline_text"] == "테스트 커버리지를 꼼꼼히 본다"


# --- 공모전 요구사항 문구 -----------------------------------------------------


def test_profane_requirement_text_is_rejected_on_free_contest_create(
    client, category, deliverable_type, hosting_user
):
    response = _create_free_contest(
        client,
        hosting_user["access"],
        category,
        deliverable_type,
        requirements=[{"text": "씨발 로그인 기능이 있다", "grade": "required"}],
    )

    assert response.status_code == 422
    assert not Contest.objects.exists()


def test_profane_requirement_text_is_rejected_on_add(client, category, deliverable_type, hosting_user):
    created = _create_free_contest(client, hosting_user["access"], category, deliverable_type)
    assert created.status_code == 200, created.content
    contest_id = created.json()["id"]

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/requirements",
        data={"text": "병신 같은 요구사항", "grade": "required"},
        content_type="application/json",
        **_auth_header(hosting_user["access"]),
    )

    assert response.status_code == 422
    assert not Requirement.objects.filter(contest_id=contest_id).exists()


def test_profane_requirement_text_is_rejected_on_update(
    client, category, deliverable_type, hosting_user
):
    created = _create_free_contest(
        client,
        hosting_user["access"],
        category,
        deliverable_type,
        requirements=[{"text": "정상 요구사항", "grade": "required"}],
    )
    assert created.status_code == 200, created.content
    contest_id = created.json()["id"]
    requirement_id = created.json()["requirements"][0]["id"]

    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}/requirements/{requirement_id}",
        data={"text": "씨발 이걸로 바꿔라"},
        content_type="application/json",
        **_auth_header(hosting_user["access"]),
    )

    assert response.status_code == 422
    assert Requirement.objects.get(id=requirement_id).text == "정상 요구사항"


def test_legitimate_requirement_text_passes(client, category, deliverable_type, hosting_user):
    response = _create_free_contest(
        client,
        hosting_user["access"],
        category,
        deliverable_type,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )

    assert response.status_code == 200
    assert response.json()["requirements"][0]["text"] == "로그인 기능이 있다"


# --- 개최자·개발자 공개 소개글 -----------------------------------------------


def _post_profile(client, access: str, url: str, **payload):
    return client.post(url, data=payload, content_type="application/json", **_auth_header(access))


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_profane_bio_is_rejected(client, url):
    pair = _login(client, "profile-bio-gap")

    response = _post_profile(client, pair["access"], url, bio="이 사람은 씨발 최고다")

    assert response.status_code == 422
    assert response.json()["detail"] == "소개에 욕설을 쓸 수 없습니다."
    assert "씨발" not in response.json()["detail"]
    for model in (SponsorProfile, DeveloperProfile):
        assert not model.objects.filter(bio__contains="씨발").exists()


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_impersonation_word_in_bio_passes(client, url):
    """소개는 본문이지 이름이 아니므로 사칭 목록을 걸지 않는다 — 「제 직업은
    관리자입니다」가 막히면 안 된다(공개 제목·본문과 같은 원칙, spec #474)."""

    pair = _login(client, "profile-bio-gap-impersonation")

    response = _post_profile(client, pair["access"], url, bio="제 직업은 관리자입니다")

    assert response.status_code == 200
    assert response.json()["bio"] == "제 직업은 관리자입니다"


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_legitimate_bio_passes(client, url):
    pair = _login(client, "profile-bio-gap-ok")

    response = _post_profile(client, pair["access"], url, bio="풀스택 개발자입니다")

    assert response.status_code == 200
    assert response.json()["bio"] == "풀스택 개발자입니다"
