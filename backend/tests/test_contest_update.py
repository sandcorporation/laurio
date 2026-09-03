"""DRAFT Contest 편집 — 결제가 문을 닫기 전까지는 무엇이든 고칠 수 있다 (#113, 부모 #110).

`PATCH /api/contests/{contest_id}`가 첫 번째 Contest 편집 엔드포인트다. 상태
게이트는 `contests.api._get_owned_draft_contest`가 진다 — 소유자가 아니면 404
("있는지가 아니라 없는지"), DRAFT가 아니면 409("분명히 거절당한다"). 요구형태나
상금을 바꾸면 최소 제안 상금 합계·상금미달 배지를 다시 계산하고, 이미 붙인
Requirement는 요구형태가 바뀌어도 지우지 않는다.
"""

from __future__ import annotations

import pytest

from contests.models import Category, Contest, DeliverableType, Requirement

CONTESTS_URL = "/api/contests"


def _login(client, uid="sponsor-1", email=None):
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


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


@pytest.fixture
def category(db):
    return Category.objects.create(name="교육")


@pytest.fixture
def other_category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


@pytest.fixture
def admin_type(db):
    return DeliverableType.objects.create(name="관리자 페이지", minimum_prize=1_500_000)


def _create_draft(client, access, *, category, deliverable_type_ids, prize=2_000_000):
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "고칠 초안",
            "category_id": category.id,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "원래 설명",
            "prize": prize,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.django_db
def test_updating_each_field_is_reflected_on_read_back(
    client, category, other_category, landing_type, admin_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-1")
    created = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
    contest_id = created["id"]

    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={
            "title": "고친 제목",
            "description": "고친 설명",
            "category_id": other_category.id,
            "deliverable_type_ids": [admin_type.id],
            "prize": 3_000_000,
            "deadline_at": "2031-06-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "고친 제목"
    assert body["description"] == "고친 설명"
    assert body["category"]["id"] == other_category.id
    assert [dt["id"] for dt in body["deliverable_types"]] == [admin_type.id]
    assert body["prize"] == 3_000_000
    assert body["deadline_at"].startswith("2031-06-01")

    # 다시 읽어도 그 값이다 — PATCH 응답만이 아니라 GET으로도 확인한다.
    reread = client.get(f"{CONTESTS_URL}/{contest_id}", **_auth_header(pair["access"]))
    assert reread.status_code == 200
    reread_body = reread.json()
    assert reread_body["title"] == "고친 제목"
    assert reread_body["prize"] == 3_000_000


@pytest.mark.django_db
def test_partial_update_leaves_other_fields_untouched(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-2")
    created = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
    contest_id = created["id"]

    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={"title": "제목만 고침"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "제목만 고침"
    # 나머지는 원래 값 그대로다.
    assert body["description"] == "원래 설명"
    assert body["prize"] == 2_000_000
    assert [dt["id"] for dt in body["deliverable_types"]] == [landing_type.id]


@pytest.mark.django_db
def test_changing_deliverable_types_recomputes_minimum_and_underfunded_badge(
    client, category, landing_type, admin_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-3")
    # 처음엔 랜딩(50만) 하나만 골라 100만 상금이면 미달이 아니다.
    created = _create_draft(
        client, pair["access"], category=category, deliverable_type_ids=[landing_type.id], prize=1_000_000
    )
    assert created["required_minimum_prize"] == 500_000
    assert created["is_underfunded"] is False
    contest_id = created["id"]

    # 관리자 페이지(150만)를 추가로 고르면 합계가 200만이 되어 100만 상금은 미달이다.
    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={"deliverable_type_ids": [landing_type.id, admin_type.id]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["required_minimum_prize"] == 500_000 + 1_500_000
    assert body["is_underfunded"] is True

    # 상금만 올려도(요구형태는 그대로) 다시 계산돼 미달이 풀린다.
    response2 = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={"prize": 5_000_000},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response2.status_code == 200
    body2 = response2.json()
    assert body2["required_minimum_prize"] == 500_000 + 1_500_000
    assert body2["is_underfunded"] is False


@pytest.mark.django_db
def test_changing_deliverable_types_does_not_delete_existing_requirements(
    client, category, landing_type, admin_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-4")
    created = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
    contest_id = created["id"]

    add_response = client.post(
        f"{CONTESTS_URL}/{contest_id}/requirements",
        data={"text": "로그인 기능을 지원한다", "grade": "required"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert add_response.status_code == 200

    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={"deliverable_type_ids": [admin_type.id]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    # 요구형태를 완전히 바꿔치기했는데도 기존 Requirement는 그대로 남아 있다.
    assert len(body["requirements"]) == 1
    assert body["requirements"][0]["text"] == "로그인 기능을 지원한다"
    assert Requirement.objects.filter(contest_id=contest_id).count() == 1


@pytest.mark.django_db
def test_empty_deliverable_type_ids_is_rejected(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-5")
    created = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    response = client.patch(
        f"{CONTESTS_URL}/{created['id']}",
        data={"deliverable_type_ids": []},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


@pytest.mark.django_db
def test_only_draft_can_be_updated_no_status_silently_passes(client, category, landing_type):
    """`Contest.Status`를 순회한다 — 고정된 상태 목록이 아니라 실제 enum을 돈다
    (test_home_curation.py와 같은 관용구). DRAFT를 뺀 모든 상태가 409여야 한다."""
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-6")

    for status in Contest.Status:
        created = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
        contest_id = created["id"]
        if status != Contest.Status.DRAFT:
            Contest.objects.filter(id=contest_id).update(status=status)

        response = client.patch(
            f"{CONTESTS_URL}/{contest_id}",
            data={"title": f"고쳐본다 ({status})"},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

        if status == Contest.Status.DRAFT:
            assert response.status_code == 200, f"DRAFT는 고칠 수 있어야 한다: {response.json()}"
        else:
            assert response.status_code == 409, (
                f"{status} 상태는 조용히 통과하면 안 된다: {response.status_code} {response.json()}"
            )


@pytest.mark.django_db
def test_strangers_contest_cannot_be_updated(client, category, landing_type):
    owner_pair = _login(client, uid="owner-sponsor")
    _verify(client, owner_pair["access"], ci="owner-ci-1")
    created = _create_draft(
        client, owner_pair["access"], category=category, deliverable_type_ids=[landing_type.id]
    )
    contest_id = created["id"]

    stranger_pair = _login(client, uid="stranger")
    response = client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data={"title": "남의 초안을 고쳐본다"},
        content_type="application/json",
        **_auth_header(stranger_pair["access"]),
    )
    # 있는지가 아니라 없는지로 단언한다 — 403이 아니라 404다.
    assert response.status_code == 404

    # 실제로 바뀌지 않았다.
    reread = client.get(f"{CONTESTS_URL}/{contest_id}", **_auth_header(owner_pair["access"]))
    assert reread.json()["title"] == "고칠 초안"
