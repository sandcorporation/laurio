"""Verification — 휴대폰 본인확인 + 만 19세 게이트 + CI/DI (#7).

`Verification`은 `Authentication`과 다른 것이다(ADR-0011) — accounts 앱은 "누구 것인가"만
답하고, 이 앱은 "실재하는 성인 본인인가"를 답한다. dev/test는 Fake 어댑터로 네트워크 없이
결정적으로 동작한다(ADR-0007).
"""

from datetime import date

import pytest
from django.test import override_settings

from verification.adapters import FakeVerificationAdapter, VerificationResult
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

    # timezone.now().date() 가 아니라 localdate() 다. 프로덕션의 나이 게이트는
    # KST 기준 "오늘"로 판정하는데(verification/api.py, ADR-0011), 여기서 UTC 날짜를
    # 쓰면 KST 00:00~09:00 사이에는 테스트가 하루를 앞당겨 계산해 매일 9시간씩
    # 빨간불이 된다 — 원래 고치려던 그 시차 버그를 테스트가 되풀이하는 꼴이다.
    today = timezone.localdate()
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

    today = timezone.localdate()
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


@pytest.mark.django_db
def test_adult_is_verified_correctly_across_the_utc_kst_date_gap(client):
    """UTC 23:30(6/14)은 KST로는 6/15 08:30 — 날짜만 UTC로 읽으면 아직 생일 전이라고
    오판해 성인을 9시간 동안 거부하는 버그가 있었다(ADR-0011). timezone.localdate()가
    KST 기준으로 날짜를 계산하는지 시계를 그 창 안에 고정해 확인한다.
    """
    from datetime import datetime, timezone as dt_timezone
    from unittest.mock import patch

    # 이 순간 UTC 날짜는 6/14 이지만 KST(UTC+9) 날짜는 이미 6/15 이다.
    pinned_utc_instant = datetime(2024, 6, 14, 23, 30, tzinfo=dt_timezone.utc)
    birth_date_of_someone_turning_19_today_in_kst = "2005-06-15"

    pair = _login(client, uid="kst-boundary", email="kst@example.com")

    with patch("django.utils.timezone.now", return_value=pinned_utc_instant):
        response = client.post(
            "/api/verification/verify",
            data={
                "verification_token": _fake_token(
                    "케이에스티",
                    birth_date_of_someone_turning_19_today_in_kst,
                    "ci-kst-1",
                    "di-kst-1",
                )
            },
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"


@pytest.mark.django_db
def test_downgrading_to_underage_clears_previously_stored_ci_and_di(client):
    """재확인으로 성인 → 미성년 판정이 뒤집히면 이미 저장돼 있던 CI/DI도 지워야 한다.

    미성년자로 판정된 사람은 플랫폼 신원(CI/DI)을 남길 이유가 없다(Verification 모델
    docstring과 동일한 원칙).
    """
    pair = _login(client, uid="downgrade-subject", email="downgrade@example.com")

    first = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "한때성인", "1990-01-01", "ci-downgrade-1", "di-downgrade-1"
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert first.json()["status"] == "verified"

    record = Verification.objects.get(user__social_accounts__provider_uid="downgrade-subject")
    assert record.ci_encrypted != ""
    assert record.ci_hash != ""
    assert record.di_encrypted != ""

    from datetime import timedelta

    from django.utils import timezone

    today = timezone.localdate()
    clearly_minor_birth = today - timedelta(days=365 * 10)

    second = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "사실은미성년",
                clearly_minor_birth.isoformat(),
                "ci-downgrade-1",
                "di-downgrade-1",
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert second.json()["status"] == "underage"

    record.refresh_from_db()
    assert record.status == Verification.Status.UNDERAGE
    assert record.ci_encrypted == ""
    assert record.ci_hash == ""
    assert record.di_encrypted == ""


# --- 어댑터 선택이 resolve_adapter를 쓴다 (#83) --------------------------------


class _DottedPathTestVerificationAdapter(FakeVerificationAdapter):
    """`VERIFICATION_ADAPTER_MODE`에 dotted path로 지목됐을 때 실제로 이 클래스가
    쓰인다는 것을 증명하기 위한 테스트 전용 더블(#83).

    토큰 파싱은 그대로 물려받되, 결과의 real_name에 이 클래스만 낼 수 있는
    마커를 남긴다 — `VERIFICATION_ADAPTER_MODE="fake"`였다면 절대 나올 수 없는
    값이므로, DB에 저장된 값만으로 `resolve_adapter`가 이 dotted path를 실제로
    import해 썼다는 것을 확인할 수 있다.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        result = super().resolve(verification_token)
        return VerificationResult(
            real_name="DOTTED-PATH-MARKER",
            birth_date=result.birth_date,
            ci=result.ci,
            di=result.di,
        )


@pytest.mark.django_db
def test_verification_adapter_mode_resolves_a_dotted_path_to_a_real_class(client):
    pair = _login(client)

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification._DottedPathTestVerificationAdapter"
        )
    ):
        response = client.post(
            "/api/verification/verify",
            data={
                "verification_token": _fake_token(
                    "홍길동", "1990-05-15", "ci-dotted-path-1", "di-dotted-path-1"
                )
            },
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"

    record = Verification.objects.get(user__social_accounts__provider_uid="verify-subject")
    assert record.real_name == "DOTTED-PATH-MARKER"
