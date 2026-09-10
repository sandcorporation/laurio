"""공모전 제품 스위치 (#271, ADR-0037) — staging 에서 공모전 표면을 내리고 과제는 남긴다.

좋은 테스트는 스위치의 구현(설정 값을 읽었는가)이 아니라 결과(꺼진 상태에서 공모전을
개최할 수 있는가)를 본다 — `CLAUDE.md` "HTTP가 유일한 시임이다". 이 파일은 세 가지를
확인한다.

1. **꺼진 상태의 백엔드**: 닫기로 한 공모전 표면 하나하나가 404를 낸다.
2. **꺼져도 열려 있어야 하는 것**: 과제 개설·초대·제출·채점·조회, 그리고 과제 화면이
   읽는 공용 참조 데이터. 너무 많이 닫는 실수는 과제가 조용히 깨지는 모양으로 나타나므로
   닫는 쪽과 같은 강도로 고정한다.
3. **스캔 등록**: 꺼진 상태에서 등록부에 공모전 전용 스캔이 없고 채점 스캔은 있는지.

**켠 상태(기본값)의 회귀는 이 파일이 다시 확인하지 않는다** — 기존 1600여 건이 스위치를
켠 채로 돌므로 그 자체가 "다시 켜면 지금과 같다"는 증거다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.assignment_category import get_assignment_category
from contests.models import Category, Contest, DeliverableType, InviteCode
from payments.models import Payment

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
ASSIGNMENTS_URL = "/api/assignments"

pytestmark = pytest.mark.django_db

OFF = override_settings(CONTEST_PRODUCT_ENABLED=False)


def _login(client, uid="user-1", email=None):
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


def _verify(client, access: str, ci: str = "sponsor-ci-1") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|sponsor-di-1"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


@pytest.fixture
def category(db):
    return Category.objects.create(name="엔터테인먼트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


@pytest.fixture
def published_contest(db, category, landing_type):
    """이미 존재하는 공모전 — 이 티켓은 데이터를 지우지 않으므로 스위치가 꺼져도
    이런 행이 staging 에 그대로 남아 있는 상태를 흉내낸다."""

    from accounts.models import SponsorProfile
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create(username="sponsor-existing")
    sponsor = SponsorProfile.objects.create(user=user)
    contest = Contest.objects.create(
        sponsor=sponsor,
        title="이미 열려 있는 공모전",
        category=category,
        prize=1_000_000,
        deadline_at=timezone.now() + timezone.timedelta(days=30),
        status=Contest.Status.PUBLISHED,
        required_minimum_prize=landing_type.minimum_prize,
    )
    contest.deliverable_types.set([landing_type])
    return contest


# --- 1. 꺼진 상태의 백엔드 — 닫기로 한 표면 전부가 404 -------------------------


@OFF
def test_off_closes_contest_browsing_surfaces(client, published_contest):
    assert client.get(CONTESTS_URL).status_code == 404
    assert client.get(f"{CONTESTS_URL}/home").status_code == 404
    assert client.get(f"{CONTESTS_URL}/{published_contest.id}").status_code == 404
    assert client.post(f"{CONTESTS_URL}/{published_contest.id}/views").status_code == 404


@OFF
def test_off_closes_contest_hosting_flow(client, category, landing_type):
    pair = _login(client, uid="sponsor-off-1")
    _verify(client, pair["access"], ci="sponsor-ci-off-1")
    headers = _auth_header(pair["access"])

    assert (
        client.post(
            f"{CONTESTS_URL}/quote",
            data={"deliverable_type_ids": [landing_type.id]},
            content_type="application/json",
        ).status_code
        == 404
    )

    create_response = client.post(
        CONTESTS_URL,
        data={
            "title": "꺼진 동안의 개최 시도",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 404

    assert client.get(f"{CONTESTS_URL}/mine", **headers).status_code == 404


@OFF
def test_off_closes_contest_edit_payment_and_ai_grill_surfaces(client, published_contest):
    from accounts.models import SponsorProfile

    pair = _login(client, uid="sponsor-off-owner")
    sponsor = SponsorProfile.objects.get(user__username="sponsor-existing")
    # draft 로 하나 더 만들어 소유자 편집 표면(update/requirement/image/AI grill)을
    # 같은 소유자로 확인한다 — 위 published_contest 픽스처는 이미 공개된 행이라
    # DRAFT 전용 게이트를 확인할 수 없다.
    draft = Contest.objects.create(
        sponsor=sponsor,
        title="꺼진 동안의 draft",
        category=published_contest.category,
        prize=1_000_000,
        deadline_at=timezone.now() + timezone.timedelta(days=30),
        status=Contest.Status.DRAFT,
    )
    # sponsor-existing 으로 로그인해야 소유자 판정을 통과한다.
    owner_pair = _login(client, uid="sponsor-existing")
    headers = _auth_header(owner_pair["access"])

    assert (
        client.patch(
            f"{CONTESTS_URL}/{draft.id}",
            data={"title": "고쳐보려는 시도"},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{CONTESTS_URL}/{draft.id}/requirement-chat/messages",
            data={"message": "체크리스트 제안해줘"},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    assert (
        client.get(f"{CONTESTS_URL}/{draft.id}/requirement-chat/messages", **headers).status_code
        == 404
    )
    assert (
        client.post(
            f"{CONTESTS_URL}/{draft.id}/requirements",
            data={"text": "요구사항", "grade": "required"},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{CONTESTS_URL}/{draft.id}/images/upload-url",
            data={"content_type": "image/png", "byte_size": 100},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            PAYMENTS_URL,
            data={"contest_id": draft.id},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{CONTESTS_URL}/{published_contest.id}/extend-judging-period",
            data={},
            content_type="application/json",
            **headers,
        ).status_code
        == 404
    )
    reopen_response = client.post(
        f"{CONTESTS_URL}/{published_contest.id}/reopen",
        data={"prize": 1_000_000, "deadline_at": "2030-01-01T00:00:00Z"},
        content_type="application/json",
        **headers,
    )
    assert reopen_response.status_code == 404


@OFF
def test_off_closes_confirm_payment(client, published_contest):
    from accounts.models import SponsorProfile

    pair = _login(client, uid="sponsor-existing")
    payment = Payment.objects.create(
        contest=published_contest,
        prize_amount=published_contest.prize,
        listing_fee_amount=0,
        status=Payment.Status.REQUESTED,
    )
    response = client.post(
        f"{PAYMENTS_URL}/{payment.order_id}/confirm",
        data={},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 404


# --- 2. 꺼져도 열려 있어야 하는 것 — 과제와 공용 참조 데이터 --------------------


@OFF
def test_off_keeps_assignment_reference_data_open(client, landing_type):
    response = client.get(f"{CONTESTS_URL}/deliverable-types")
    assert response.status_code == 200
    assert any(item["id"] == landing_type.id for item in response.json())

    category_response = client.get(f"{CONTESTS_URL}/categories")
    assert category_response.status_code == 200


@OFF
def test_off_keeps_full_assignment_lifecycle_working(client, landing_type):
    """과제 개설·초대·제출·조회가 스위치와 무관하게 끝까지 돈다(#271 user story 4/10)."""

    from django.core.management import call_command
    from django.test import Client

    root_password = "operator-pw-switch-9931"
    call_command("create_operator", "root-switch", password=root_password, superuser=True)
    operator_client = Client()
    op_login = operator_client.post(
        "/api/operator/login",
        data={"username": "root-switch", "password": root_password},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert op_login.status_code == 200, op_login.content

    pair = _login(client, uid="teacher-switch-1")
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    username = me.json()["username"]

    grant = operator_client.post(
        "/api/operator/assignment-permissions/grant",
        data={"username": username, "reason": "스위치 테스트"},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert grant.status_code == 200, grant.content

    headers = _auth_header(pair["access"])
    create_response = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": "스위치 꺼진 동안의 과제",
            "deliverable_type_ids": [landing_type.id],
            "description": "설명",
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 201, create_response.content
    assignment_id = create_response.json()["id"]

    open_response = client.post(f"{ASSIGNMENTS_URL}/{assignment_id}/open", **headers)
    assert open_response.status_code == 200, open_response.content
    invite_code = open_response.json()["invite_code"]
    assert invite_code

    mine_response = client.get(f"{ASSIGNMENTS_URL}/mine", **headers)
    assert mine_response.status_code == 200
    assert len(mine_response.json()) == 1

    invite_response = client.get(f"{ASSIGNMENTS_URL}/invite/{invite_code}")
    assert invite_response.status_code == 200

    # 제출은 `submissions.api`(다른 앱)가 갖고 있다 — 주소가 `/contests/`로
    # 시작해도 이 스위치와 무관하다(#271).
    developer_pair = _login(client, uid="developer-switch-1")
    developer_user_id = client.get(
        "/api/accounts/me", **_auth_header(developer_pair["access"])
    ).json()["id"]
    import uuid as _uuid

    submit_response = client.post(
        f"{CONTESTS_URL}/{assignment_id}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": f"submission:{assignment_id}:{developer_user_id}:source/{_uuid.uuid4().hex}",
                }
            ],
            "invite_code": invite_code,
        },
        content_type="application/json",
        **_auth_header(developer_pair["access"]),
    )
    assert submit_response.status_code == 201, submit_response.content

    submissions_response = client.get(f"{ASSIGNMENTS_URL}/{assignment_id}/submissions", **headers)
    assert submissions_response.status_code == 200
    assert len(submissions_response.json()) == 1


# --- 3. 스캔 등록 — 공모전 전용 스캔은 등록부에서 사라지고 채점은 남는다 --------


CONTEST_ONLY_SCAN_NAMES = (
    "payment-refund-request",
    "payment-refund-reconcile",
    "distribution-create",
    "distribution-share-payout",
    "payout-awaits-you",
    "seller-registration-recovery",
    "handover-release",
)

SHARED_SCAN_NAMES = (
    "submission-scoring",
    "repository-visibility",
    "identity-dormancy-purge",
    "retained-identity-purge",
    "assignment-close",
)


@OFF
def test_off_removes_contest_only_scans_from_tick():
    response = client_post_tick()
    scans = response.json()["scans"]
    for name in CONTEST_ONLY_SCAN_NAMES:
        assert name not in scans, f"{name} 가 스위치 꺼진 tick 에 여전히 나온다"
    for name in SHARED_SCAN_NAMES:
        assert name in scans, f"{name} 가 스위치 꺼진 tick 에서 사라졌다"


@OFF
@pytest.mark.parametrize("name", CONTEST_ONLY_SCAN_NAMES)
def test_off_rejects_direct_scan_call_as_unregistered(client, name):
    response = client.post(f"/api/internal/scans/{name}", **_internal_headers())
    assert response.status_code == 404


def test_on_by_default_keeps_contest_only_scans_registered():
    response = client_post_tick()
    scans = response.json()["scans"]
    for name in CONTEST_ONLY_SCAN_NAMES:
        assert name in scans, f"{name} 가 기본값(켜짐)에서 등록부에 없다"


def client_post_tick():
    from django.test import Client

    client = Client()
    response = client.post("/api/internal/tick", **_internal_headers())
    assert response.status_code == 200, response.content
    return response
