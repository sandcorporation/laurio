"""Verification — 휴대폰 본인확인 + 만 19세 게이트 + CI/DI (#7).

`Verification`은 `Authentication`과 다른 것이다(ADR-0011) — accounts 앱은 "누구 것인가"만
답하고, 이 앱은 "실재하는 성인 본인인가"를 답한다. dev/test는 Fake 어댑터로 네트워크 없이
결정적으로 동작한다(ADR-0007).
"""

from datetime import date

import pytest

from verification.models import Verification


def _login(client, uid="verify-subject", email="subject@example.com"):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _fake_token(name: str, birth_iso: str, ci: str, di: str) -> str:
    return f"{name}|{birth_iso}|{ci}|{di}"


@pytest.mark.django_db
def test_verification_requires_authentication(client):
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("홍길동", "1990-01-01", "ci-1", "di-1")},
        content_type="application/json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_adult_completes_verification_and_ci_is_encrypted_at_rest(client):
    pair = _login(client)

    response = client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("홍길동", "1990-05-15", "ci-adult-1", "di-adult-1")},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified"
    assert body["verified_at"] is not None

    record = Verification.objects.get(user__social_accounts__provider_uid="verify-subject")
    assert record.status == Verification.Status.VERIFIED
    # 평문이 그대로 저장되지 않는다 — 암호문에는 원문이 부분 문자열로도 남지 않는다.
    assert "ci-adult-1" not in record.ci_encrypted
    assert "홍길동" not in record.real_name_encrypted
    # 그러나 애플리케이션 계층에서는 복호화해 원래 값을 되찾을 수 있다.
    assert record.real_name == "홍길동"
    assert record.ci == "ci-adult-1"
    assert record.birth_date == date(1990, 5, 15)


@pytest.mark.django_db
def test_underage_is_not_verified_and_gets_a_reason(client):
    pair = _login(client, uid="minor-subject", email="minor@example.com")

    # 19번째 생일이 내일인 사람 — 오늘 기준으로는 아직 만 18세다.
    from datetime import timedelta

    from django.utils import timezone

    today = timezone.now().date()
    nineteenth_birthday = today + timedelta(days=1)
    almost_19_birth = date(
        nineteenth_birthday.year - 19, nineteenth_birthday.month, nineteenth_birthday.day
    )

    response = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "미성년", almost_19_birth.isoformat(), "ci-minor-1", "di-minor-1"
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "underage"
    assert body["reason"]
    assert body["verified_at"] is None

    record = Verification.objects.get(user__social_accounts__provider_uid="minor-subject")
    assert record.status == Verification.Status.UNDERAGE
    # 미성년자는 플랫폼 CI를 남기지 않는다.
    assert record.ci_encrypted == ""


@pytest.mark.django_db
def test_exactly_19_years_old_today_is_adult(client):
    from django.utils import timezone

    today = timezone.now().date()
    exactly_19 = date(today.year - 19, today.month, today.day)
    pair = _login(client, uid="exactly-19", email="e19@example.com")

    response = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "정확히19", exactly_19.isoformat(), "ci-exact-1", "di-exact-1"
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


@pytest.mark.django_db
def test_my_verification_status_can_be_queried(client):
    pair = _login(client)

    before = client.get("/api/verification/me", **_auth_header(pair["access"]))
    assert before.status_code == 200
    assert before.json()["status"] == "unverified"

    client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("조회자", "1985-03-03", "ci-q-1", "di-q-1")},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    after = client.get("/api/verification/me", **_auth_header(pair["access"]))
    assert after.status_code == 200
    assert after.json()["status"] == "verified"


@pytest.mark.django_db
def test_ci_lookup_finds_the_same_person_across_accounts(client):
    """두 다른 User가 같은 CI로 확인되면 CI 조회에서 함께 잡힌다 (자전거래 탐지 재료)."""

    from django.contrib.auth import get_user_model

    pair_a = _login(client, uid="person-a", email="a@example.com")
    pair_b = _login(client, uid="person-b", email="b@example.com")

    shared_ci = "shared-ci-value"
    client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("갑", "1980-01-01", shared_ci, "di-a")},
        content_type="application/json",
        **_auth_header(pair_a["access"]),
    )
    client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("을", "1981-02-02", shared_ci, "di-b")},
        content_type="application/json",
        **_auth_header(pair_b["access"]),
    )

    User = get_user_model()
    staff = User.objects.create_user(username="staff-op", email="staff@example.com")
    staff.is_staff = True
    staff.save()
    from accounts.tokens import issue_token_pair

    staff_pair = issue_token_pair(staff.id)

    response = client.post(
        "/api/verification/lookup-by-ci",
        data={"ci": shared_ci},
        content_type="application/json",
        **_auth_header(staff_pair.access),
    )

    assert response.status_code == 200
    matches = response.json()["matches"]
    assert len(matches) == 2


@pytest.mark.django_db
def test_ci_lookup_requires_staff(client):
    pair = _login(client)

    response = client.post(
        "/api/verification/lookup-by-ci",
        data={"ci": "whatever"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_verify_rejects_malformed_token(client):
    pair = _login(client)

    response = client.post(
        "/api/verification/verify",
        data={"verification_token": "not-a-valid-token"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422
