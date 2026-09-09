"""Contest 개최(draft) + DeliverableType·최소상금·상금미달 배지 (#8).

결제/Escrow(#9)는 범위 밖이라 이 티켓이 만드는 Contest는 항상 draft로 남는다.
Category(산업·장르)와 DeliverableType(산출물 종류)은 다른 축이며, 복수 선택한
DeliverableType의 최소 제안 상금은 합산되어 Prize 미달 시 배지만 서고 등록은 막지
않는다(ADR-0001).
"""

import pytest

from contests.models import Category, Contest, DeliverableType


def _login(client, uid="sponsor-1", email="sponsor@example.com"):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, ci: str = "sponsor-ci-1") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|sponsor-di-1"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


@pytest.fixture
def category(db):
    return Category.objects.create(name="엔터테인먼트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


@pytest.fixture
def admin_type(db):
    return DeliverableType.objects.create(name="관리자 페이지", minimum_prize=1_500_000)


@pytest.mark.django_db
def test_creating_contest_without_verification_is_rejected(client, category, landing_type):
    pair = _login(client)

    response = client.post(
        "/api/contests",
        data={
            "title": "미검증 개최 시도",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 403
    assert "본인확인" in response.json()["detail"]


@pytest.mark.django_db
def test_quote_sums_minimum_prize_across_selected_types_publicly(
    client, landing_type, admin_type
):
    response = client.post(
        "/api/contests/quote",
        data={"deliverable_type_ids": [landing_type.id, admin_type.id]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["minimum_total"] == 500_000 + 1_500_000


@pytest.mark.django_db
def test_verified_sponsor_creates_draft_contest_meeting_minimum(
    client, category, landing_type, admin_type
):
    pair = _login(client)
    _verify(client, pair["access"])

    response = client.post(
        "/api/contests",
        data={
            "title": "앱 + 관리자 페이지 의뢰",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id, admin_type.id],
            "description": "요구사항 설명",
            "prize": 2_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [
                {"text": "로그인 기능", "grade": "required"},
                {"text": "다크모드", "grade": "optional"},
            ],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["required_minimum_prize"] == 2_000_000
    assert body["is_underfunded"] is False
    assert len(body["deliverable_types"]) == 2
    assert body["category"]["name"] == "엔터테인먼트"
    assert [r["grade"] for r in body["requirements"]] == ["required", "optional"]

    contest = Contest.objects.get(id=body["id"])
    assert contest.sponsor.user.social_accounts.filter(provider_uid="sponsor-1").exists()


@pytest.mark.django_db
def test_prize_below_sum_sets_underfunded_badge_but_still_succeeds(
    client, category, landing_type, admin_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-2")

    response = client.post(
        "/api/contests",
        data={
            "title": "예산이 부족한 의뢰",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id, admin_type.id],
            "prize": 100_000,  # 합계(2,000,000)에 크게 못 미친다
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_underfunded"] is True
    assert body["status"] == "draft"  # 등록 자체는 막히지 않는다


@pytest.mark.django_db
def test_negative_prize_is_rejected_with_422_not_500(client, category, landing_type):
    """PositiveIntegerField의 DB CHECK에 그대로 부딪히면 422가 아니라 500이 난다."""
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-negative")

    response = client.post(
        "/api/contests",
        data={
            "title": "음수 상금",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": -1000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_requirement_grade_must_be_required_or_optional(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-3")

    response = client.post(
        "/api/contests",
        data={
            "title": "잘못된 등급",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [{"text": "이상한 등급", "grade": "urgent"}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_category_and_deliverable_type_are_separate_axes(client):
    """같은 문자열을 이름으로 써도 서로 다른 테이블/축이라 섞이지 않는다."""

    category = Category.objects.create(name="게임")
    deliverable_type = DeliverableType.objects.create(name="게임", minimum_prize=1_000_000)

    categories = client.get("/api/contests/categories").json()
    deliverable_types = client.get("/api/contests/deliverable-types").json()

    assert any(c["id"] == category.id and c["name"] == "게임" for c in categories)
    assert any(
        d["id"] == deliverable_type.id and d["name"] == "게임" for d in deliverable_types
    )
    # 서로 다른 기본키 공간 — 이름이 같다고 같은 레코드를 가리키지 않는다.
    assert Category._meta.db_table != DeliverableType._meta.db_table


@pytest.mark.django_db
def test_anonymous_can_list_and_read_published_but_not_draft(
    client, category, landing_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-4")

    created = client.post(
        "/api/contests",
        data={
            "title": "비공개 초안",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()
    draft_id = created["id"]

    # draft는 목록에 없다. 목록은 페이지네이션돼 {"items": [...], "count": N} 로 온다.
    listing = client.get("/api/contests").json()
    assert all(c["id"] != draft_id for c in listing["items"])

    # draft는 익명 상세 조회에서 404.
    anon_detail = client.get(f"/api/contests/{draft_id}")
    assert anon_detail.status_code == 404

    # #9가 결제 확인 후 뒤집을 상태를 여기선 ORM으로 흉내낸다(운영 훅 검증).
    Contest.objects.filter(id=draft_id).update(status=Contest.Status.PUBLISHED)

    listing_after_publish = client.get("/api/contests").json()
    assert any(c["id"] == draft_id for c in listing_after_publish["items"])
    assert listing_after_publish["count"] >= 1

    detail_after_publish = client.get(f"/api/contests/{draft_id}")
    assert detail_after_publish.status_code == 200


@pytest.mark.django_db
def test_owner_can_view_own_draft_but_stranger_cannot(client, category, landing_type):
    owner_pair = _login(client, uid="owner-sponsor", email="owner@example.com")
    _verify(client, owner_pair["access"], ci="owner-ci-1")

    created = client.post(
        "/api/contests",
        data={
            "title": "소유자만 보는 초안",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(owner_pair["access"]),
    ).json()
    draft_id = created["id"]

    owner_view = client.get(f"/api/contests/{draft_id}", **_auth_header(owner_pair["access"]))
    assert owner_view.status_code == 200

    stranger_pair = _login(client, uid="stranger", email="stranger@example.com")
    stranger_view = client.get(
        f"/api/contests/{draft_id}", **_auth_header(stranger_pair["access"])
    )
    assert stranger_view.status_code == 404


@pytest.mark.django_db
def test_contest_detail_is_owner_reflects_the_viewer(client, category, landing_type):
    """#164 — 공개 상세의 "제출하러 가기" CTA가 자기 Contest를 감추는 유일한 근거.

    익명(SSR 공개 상세는 Authorization을 보내지 않는다, ADR-0015)에게는
    Sponsor 본인이어도 항상 False다. 로그인해 다시 부르면(BFF를 거치는 인증
    구역 호출을 흉내낸다) 본인에게만 True, 남에게는 False.
    """

    owner_pair = _login(client, uid="cta-owner", email="cta-owner@example.com")
    _verify(client, owner_pair["access"], ci="cta-owner-ci-1")

    created = client.post(
        "/api/contests",
        data={
            "title": "공개 CTA 확인용",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(owner_pair["access"]),
    ).json()
    contest_id = created["id"]
    Contest.objects.filter(id=contest_id).update(status=Contest.Status.PUBLISHED)

    anon_detail = client.get(f"/api/contests/{contest_id}").json()
    assert anon_detail["is_owner"] is False

    owner_detail = client.get(
        f"/api/contests/{contest_id}", **_auth_header(owner_pair["access"])
    ).json()
    assert owner_detail["is_owner"] is True

    stranger_pair = _login(client, uid="cta-stranger", email="cta-stranger@example.com")
    stranger_detail = client.get(
        f"/api/contests/{contest_id}", **_auth_header(stranger_pair["access"])
    ).json()
    assert stranger_detail["is_owner"] is False


@pytest.mark.django_db
def test_contest_detail_has_own_submission_reflects_the_viewer(client, category, landing_type):
    """#245 — 공개 상세의 제출 CTA가 "이미 냈다"를 판정하는 유일한 근거.

    `is_owner`와 같은 자리·같은 이유로 계산된다: 익명에게는 항상 False, 아직
    내지 않은 로그인 사용자에게도 False, 실제로 제출한 사람에게만 True다.
    """

    from datetime import timedelta

    from django.utils import timezone

    from tests.test_source_readings import _publish_contest, _submit, _verified_user

    deadline_at = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="hos-sponsor",
        sponsor_ci="hos-sponsor-ci",
        deadline_at=deadline_at,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    contest_id = contest["id"]

    anon_detail = client.get(f"/api/contests/{contest_id}").json()
    assert anon_detail["has_own_submission"] is False

    dev = _verified_user(client, "hos-dev", "hos-dev-ci")
    before_submit = client.get(
        f"/api/contests/{contest_id}", **_auth_header(dev["access"])
    ).json()
    assert before_submit["has_own_submission"] is False

    _submit(client, dev, contest_id, requirement_id=contest["requirements"][0]["id"])

    after_submit = client.get(
        f"/api/contests/{contest_id}", **_auth_header(dev["access"])
    ).json()
    assert after_submit["has_own_submission"] is True

    stranger = _verified_user(client, "hos-stranger", "hos-stranger-ci")
    stranger_detail = client.get(
        f"/api/contests/{contest_id}", **_auth_header(stranger["access"])
    ).json()
    assert stranger_detail["has_own_submission"] is False
