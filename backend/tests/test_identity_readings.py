"""IdentityReading — Operator가 보존된 실명을 펼친 사건과 그 기록 (#103, ADR-0022).

#101이 탈퇴 뒤 거래가 있었던 사람의 실명·생년월일을 `RetainedIdentity`로 남긴다.
이 파일은 그것을 분쟁 대응을 위해 여는 경로를 **기록과 함께**(#103) 만든다 —
`appeals`의 `SourceReading`(ADR-0022)과 같은 모양이다.

핵심 대상:

- `GET /operator/retained-identities`, `GET /operator/retained-identities/{id}` —
  접힌 채로 나간다. 실명·생년월일이 응답에 없다.
- `POST /operator/retained-identities/{id}/reveal` — 펼치면 실명·생년월일이
  나오고, 그 요청 하나가 `IdentityReading`을 정확히 하나 만든다. 누가, 언제,
  어느 행을 폈는지가 남는다.
- 열람은 사건이다 — 같은 Operator가 다시 펼치면 행이 하나 더 쌓인다.
- 인증·Origin 검증·404는 다른 운영자 엔드포인트와 같은 규율을 따른다.
- 참가자 쪽 API로는 이 값에 닿을 수 없다 — 있는지가 아니라 없는지를 단언한다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from verification.models import IdentityReading, RetainedIdentity

OPERATOR_ORIGIN = "http://testserver"
RETAINED_IDENTITIES_URL = "/api/operator/retained-identities"


def _operator_client(username="operator-1"):
    call_command("create_operator", username, password="operator-pw-9134-xyz")
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _login(client, uid="dev-1", email=None):
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


def _make_retained_identity(
    *, username: str, real_name: str = "보존된사람", birth=date(1990, 5, 17),
    reason=RetainedIdentity.Reason.SPONSOR_PAID_CONTEST, retained_because_id=1,
    retained_until=None,
) -> RetainedIdentity:
    """`RetainedIdentity`는 이 티켓이 여는 대상(전제 조건)이지 이 티켓이 만드는
    것이 아니다 — #101이 이미 만드는 값(테스트가 실제 탈퇴로 만드는 것은
    `test_withdrawal.py`가 고정한다). 여기서는 직접 만들어 전제로 둔다 —
    #102의 만료 스캔 테스트가 같은 관용구를 쓴다.
    """

    user = get_user_model().objects.create_user(username=username, email=f"{username}@example.test")
    retained_until = retained_until or (timezone.now() + timedelta(days=365))
    retained = RetainedIdentity(
        user=user,
        reason=reason,
        retained_because_id=retained_because_id,
        retained_until=retained_until,
    )
    retained.real_name = real_name
    retained.birth_date = birth
    retained.save()
    return retained


def _reveal(operator, retained_identity_id, *, origin=OPERATOR_ORIGIN):
    kwargs = {}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return operator.post(
        f"{RETAINED_IDENTITIES_URL}/{retained_identity_id}/reveal",
        content_type="application/json",
        **kwargs,
    )


# --- 펼치면 값이 나오고 기록이 남는다 -------------------------------------------


@pytest.mark.django_db
def test_revealing_retained_identity_returns_real_name_and_birth_date():
    retained = _make_retained_identity(username="reveal-target-1", real_name="이름사람", birth=date(1988, 3, 3))
    operator = _operator_client()

    response = _reveal(operator, retained.id)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["real_name"] == "이름사람"
    assert body["birth_date"] == "1988-03-03"


@pytest.mark.django_db
def test_revealing_retained_identity_creates_exactly_one_identity_reading():
    retained = _make_retained_identity(username="reveal-target-2")
    operator = _operator_client("op-reveal")

    assert IdentityReading.objects.count() == 0
    response = _reveal(operator, retained.id)
    assert response.status_code == 200

    assert IdentityReading.objects.count() == 1
    reading = IdentityReading.objects.get()
    assert reading.retained_identity_id == retained.id
    assert reading.read_by == get_user_model().objects.get(username="op-reveal")
    assert reading.read_at is not None


@pytest.mark.django_db
def test_the_same_operator_revealing_twice_creates_two_rows():
    """열람은 상태가 아니라 사건이다 — 중복 제거하지 않는다."""

    retained = _make_retained_identity(username="reveal-target-3")
    operator = _operator_client("op-repeat")

    assert _reveal(operator, retained.id).status_code == 200
    assert _reveal(operator, retained.id).status_code == 200

    assert IdentityReading.objects.count() == 2


@pytest.mark.django_db
def test_different_operators_are_recorded_under_their_own_names():
    retained = _make_retained_identity(username="reveal-target-4")
    op_a = _operator_client("op-a")
    op_b = _operator_client("op-b")

    assert _reveal(op_a, retained.id).status_code == 200
    assert _reveal(op_b, retained.id).status_code == 200

    usernames = set(IdentityReading.objects.values_list("read_by__username", flat=True))
    assert usernames == {"op-a", "op-b"}


# --- 기본은 접혀 있다 -----------------------------------------------------------


@pytest.mark.django_db
def test_listing_retained_identities_does_not_expose_real_name_or_birth_date():
    retained = _make_retained_identity(username="folded-list", real_name="목록에안보일이름")
    operator = _operator_client("op-list")

    response = operator.get(RETAINED_IDENTITIES_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["id"] == retained.id
    assert item["user_id"] == retained.user_id
    assert "real_name" not in item
    assert "birth_date" not in item
    assert "목록에안보일이름" not in response.content.decode("utf-8")
    # 목록을 여는 것만으로는 열람 기록이 남지 않는다.
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_retained_identity_detail_does_not_expose_real_name_or_birth_date():
    retained = _make_retained_identity(username="folded-detail", real_name="상세에안보일이름")
    operator = _operator_client("op-detail")

    response = operator.get(f"{RETAINED_IDENTITIES_URL}/{retained.id}")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["id"] == retained.id
    assert "real_name" not in body
    assert "birth_date" not in body
    assert "상세에안보일이름" not in response.content.decode("utf-8")
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_reveal_is_the_only_surface_that_returns_the_real_name():
    """운영자 표면 전체에서 실명을 돌려주는 것은 펼침 엔드포인트뿐이다."""

    retained = _make_retained_identity(username="scan-target", real_name="펼쳐야만보일이름")
    operator = _operator_client("op-scan")

    listing = operator.get(RETAINED_IDENTITIES_URL)
    detail = operator.get(f"{RETAINED_IDENTITIES_URL}/{retained.id}")
    for resp in (listing, detail):
        assert "펼쳐야만보일이름" not in resp.content.decode("utf-8")

    revealed = _reveal(operator, retained.id)
    assert revealed.json()["real_name"] == "펼쳐야만보일이름"


# --- 인증·Origin·404 --------------------------------------------------------


@pytest.mark.django_db
def test_revealing_without_a_session_is_401():
    retained = _make_retained_identity(username="no-session")

    client = Client()
    response = client.post(
        f"{RETAINED_IDENTITIES_URL}/{retained.id}/reveal",
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )

    assert response.status_code == 401
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_listing_without_a_session_is_401():
    _make_retained_identity(username="no-session-list")

    client = Client()
    response = client.get(RETAINED_IDENTITIES_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_revealing_with_a_non_operator_session_is_403():
    """세션은 있지만 Operator(is_staff)가 아닌 계정."""

    retained = _make_retained_identity(username="non-operator-target")

    participant = get_user_model().objects.create_user(username="plain-user-identity")
    plain = Client()
    plain.force_login(participant)

    response = _reveal(plain, retained.id)

    assert response.status_code == 403
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_without_origin_is_403():
    retained = _make_retained_identity(username="no-origin-target")
    operator = _operator_client("op-no-origin")

    response = _reveal(operator, retained.id, origin=None)

    assert response.status_code == 403
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_with_wrong_origin_is_403():
    retained = _make_retained_identity(username="wrong-origin-target")
    operator = _operator_client("op-wrong-origin")

    response = _reveal(operator, retained.id, origin="http://evil.example.com")

    assert response.status_code == 403
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_a_nonexistent_retained_identity_is_404_and_records_nothing():
    operator = _operator_client("op-404")

    response = _reveal(operator, 999_999)

    assert response.status_code == 404
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_getting_a_nonexistent_retained_identity_detail_is_404():
    operator = _operator_client("op-404-detail")

    response = operator.get(f"{RETAINED_IDENTITIES_URL}/999999")

    assert response.status_code == 404


# --- 참가자 쪽 API로는 이 값에 닿을 수 없다 (#103 AC) ----------------------------


@pytest.mark.django_db
def test_participant_jwt_cannot_reach_the_operator_reveal_endpoint():
    """참가자 인증(JWT)으로는 운영자 표면 자체에 닿지 못한다 — 세션이 아니라서
    `OperatorAuth`가 애초에 아무도 아니라고 본다(401)."""

    retained = _make_retained_identity(username="participant-cannot-reach")
    pair = _login(Client(), uid="plain-participant")

    client = Client()
    response = client.post(
        f"{RETAINED_IDENTITIES_URL}/{retained.id}/reveal",
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 401
    assert IdentityReading.objects.count() == 0


@pytest.mark.django_db
def test_withdrawn_user_cannot_authenticate_to_view_their_own_retained_identity():
    """탈퇴한 계정(`is_active=False`)은 이미 발급된 JWT로도 다음 요청부터
    익명이 된다(`accounts.middleware`) — 자기 보존 실명을 조회할 참가자 표면
    자체가 성립하지 않는다(#103 AC)."""

    from accounts.tokens import issue_token_pair

    retained = _make_retained_identity(username="withdrawn-cannot-self-view")
    pair = issue_token_pair(retained.user_id)

    retained.user.is_active = False
    retained.user.save(update_fields=["is_active"])

    client = Client()
    me = client.get("/api/accounts/me", **_auth_header(pair.access))
    assert me.status_code == 401


@pytest.mark.django_db
def test_no_participant_route_exists_for_retained_identities():
    """`/api/operator/` 접두어 밖에는 `retained-identities` 경로가 없다 — 있는지가
    아니라 없는지를 단언한다."""

    client = Client()
    for path in (
        "/api/retained-identities",
        "/api/verification/retained-identities",
        "/api/accounts/retained-identities",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
