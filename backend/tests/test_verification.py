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


def _fake_token(name: str, birth_iso: str, ci: str, di: str, phone: str = "") -> str:
    if phone:
        return f"{name}|{birth_iso}|{ci}|{di}|{phone}"
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


def _start(client, access: str) -> str:
    """`/verification/start`를 호출해 서버가 발급한 identityVerificationId를 얻는다.

    #85 코드리뷰 지적 1 — 실물(비-fake) 어댑터 모드에서는 `verify()`가 이 값이
    실제로 요청자 본인에게 발급된 것인지 확인한다. 이 파일의 dotted-path 테스트
    더블들은 실물 흐름을 흉내내므로, 이 헬퍼로 먼저 발급받은 id를 그대로
    `verification_token`으로 제출한다.
    """
    response = client.post("/api/verification/start", **_auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["identity_verification_id"]


class _DottedPathTestVerificationAdapter:
    """`VERIFICATION_ADAPTER_MODE`에 dotted path로 지목됐을 때 실제로 이 클래스가
    쓰인다는 것을 증명하기 위한 테스트 전용 더블(#83).

    실물 어댑터를 흉내내므로 `verification_token`은 `/verification/start`가
    발급한 불투명 id다(#85 코드리뷰 지적 1) — 그래서 이 어댑터는 토큰 내용을
    파싱하지 않고 고정된 응답을 돌려준다. 그 응답의 real_name에 이 클래스만
    낼 수 있는 마커를 남겨서, `VERIFICATION_ADAPTER_MODE="fake"`였다면 절대
    나올 수 없는 값이 DB에 저장된 것만으로 `resolve_adapter`가 이 dotted
    path를 실제로 import해 썼다는 것을 확인할 수 있다.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        return VerificationResult(
            real_name="DOTTED-PATH-MARKER",
            birth_date=date(1990, 5, 15),
            ci="ci-dotted-path-1",
            di="di-dotted-path-1",
        )


class _NoCIVerificationAdapter:
    """CI를 주지 않는 벤더 응답을 흉내낸다(#84).

    실제 벤더(KG이니시스 통합인증)는 카카오 인증에서만 CI를 주지 않는다 — 이
    어댑터는 "그 인증 수단 설정이 되돌려진" 상황을 재현해, `VerificationResult`가
    CI 없이는 생성 자체를 거부하는지 증명한다. 실물 어댑터를 흉내내므로
    `verification_token`은 `/verification/start`가 발급한 불투명 id다(#85 코드리뷰
    지적 1) — 토큰 내용은 파싱하지 않고 고정된 실명·생년월일만 돌려준다.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        return VerificationResult(
            real_name="노시아이", birth_date=date(1990, 1, 1), ci="", di=""
        )


@pytest.mark.django_db
def test_verification_with_missing_ci_is_rejected_and_leaves_user_unverified(client, caplog):
    """CI 없는 응답으로 본인확인을 시도하면 4xx로 거절되고 VERIFIED가 되지 않는다.

    응답 문구는 이유를 말하고 다른 인증 수단을 쓰라고 안내해야 하며, 서버 로그는
    ERROR로 이걸 사용자 잘못이 아니라 벤더 콘솔의 설정 회귀로 지목해야 한다(#84).
    """
    pair = _login(client, uid="no-ci-subject", email="no-ci@example.com")

    with override_settings(
        VERIFICATION_ADAPTER_MODE="tests.test_verification._NoCIVerificationAdapter"
    ):
        token = _start(client, pair["access"])
        import logging

        with caplog.at_level(logging.ERROR, logger="verification.api"):
            response = client.post(
                "/api/verification/verify",
                data={"verification_token": token},
                content_type="application/json",
                **_auth_header(pair["access"]),
            )

    assert 400 <= response.status_code < 500
    body = response.json()
    assert "다른 인증 수단" in body["detail"]

    assert Verification.objects.filter(
        user__social_accounts__provider_uid="no-ci-subject", status=Verification.Status.VERIFIED
    ).exists() is False

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "CI 없는 응답은 ERROR 로그를 남겨야 한다"
    assert any("설정 회귀" in r.getMessage() for r in error_records)
    assert all("사용자" not in r.getMessage() or "설정" in r.getMessage() for r in error_records)


@pytest.mark.django_db
def test_ci_less_user_cannot_submit_or_open_a_contest(client):
    """CI 없는 응답으로는 관문(Submission 제출·Contest 개최)이 열리지 않는다(#84)."""
    pair = _login(client, uid="no-ci-gate-subject", email="no-ci-gate@example.com")

    with override_settings(
        VERIFICATION_ADAPTER_MODE="tests.test_verification._NoCIVerificationAdapter"
    ):
        token = _start(client, pair["access"])
        client.post(
            "/api/verification/verify",
            data={"verification_token": token},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    me = client.get("/api/verification/me", **_auth_header(pair["access"]))
    assert me.json()["status"] == "unverified"

    create_response = client.post(
        "/api/contests",
        data={
            "title": "자전거래 회귀 방지 대회",
            "category_id": 999_999,
            "deliverable_type_ids": [999_999],
            "prize": 1_000_000,
            "deadline_at": "2999-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    # Verification 게이트가 Category/DeliverableType 존재 여부보다 먼저 걸린다
    # (contests/api.py create_contest) — 실재하지 않는 id를 넘겨도 403이 먼저 난다.
    assert create_response.status_code == 403


@pytest.mark.django_db
def test_set_ci_refuses_an_empty_value_so_ci_less_users_cannot_share_a_hash():
    """`Verification.set_ci`의 회귀 테스트(#84) — 이 파일의 다른 테스트는 전부 HTTP를
    거치지만, 이 불변식은 `VerificationResult`의 계약 가드보다 한 층 더 안쪽,
    모델 자신의 방어선이라 이 파일에서 유일하게 모델 메서드를 직접 부른다
    (`tests/test_core_adapters.py`가 `core.adapters`라는 순수 인프라 헬퍼에
    대해 같은 예외를 이미 두고 있다).

    두 `Verification` 행을 실제로 DB에 저장한다(코드리뷰 지적 — 저장하지 않은
    객체에 대한 단언은 가드가 있든 없든 항상 통과해 아무것도 증명하지 못한다).
    `set_ci("")`가 조용히 통과하면 `HMAC(key, "")`이라는 정상적인 64자 hex가
    나와, CI 없는 사용자 전원이 같은 해시를 갖고 서로 남남인 Sponsor와 Developer가
    동일인으로 오차단된다 — 이게 이 티켓이 고치는 실제 결함이다. 위의 거절
    테스트는 `VerificationResult` 계약 가드만 증명하고 이 메서드 자체는 부르지
    않으므로, `set_ci`가 다시 빈 문자열을 받아들이게 되는 회귀는 이 테스트만
    잡는다 — 가드가 사라지면 두 저장된 행 모두 `ci_hash`가 같은 값으로 채워져
    `find_by_ci("")`가 서로 남남인 둘을 같이 돌려주게 된다.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user_a = User.objects.create_user(username="ci-guard-a", email="ci-guard-a@example.com")
    user_b = User.objects.create_user(username="ci-guard-b", email="ci-guard-b@example.com")
    verification_a = Verification.objects.create(user=user_a, status=Verification.Status.VERIFIED)
    verification_b = Verification.objects.create(user=user_b, status=Verification.Status.VERIFIED)

    with pytest.raises(ValueError):
        verification_a.set_ci("")
    with pytest.raises(ValueError):
        verification_b.set_ci("")

    verification_a.refresh_from_db()
    verification_b.refresh_from_db()

    # 가드가 막아 ci_hash가 채워지지 않은 채로 DB에 남는다 — 서로 다른 사람인 두
    # 저장된 행이 이 상태로는 절대 같은 해시로 묶이지 않는다. 가드가 사라지면
    # 위의 pytest.raises가 실패해 여기 도달하지도 못하거나, 도달하더라도 두 행
    # 모두 ci_hash가 같은 값(HMAC(key, ""))으로 저장돼 아래 단언이 깨진다.
    assert verification_a.ci_hash == ""
    assert verification_b.ci_hash == ""
    assert list(Verification.find_by_ci("")) == []


@pytest.mark.django_db
def test_verification_adapter_mode_resolves_a_dotted_path_to_a_real_class(client):
    pair = _login(client)

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification._DottedPathTestVerificationAdapter"
        )
    ):
        token = _start(client, pair["access"])
        response = client.post(
            "/api/verification/verify",
            data={"verification_token": token},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"

    record = Verification.objects.get(user__social_accounts__provider_uid="verify-subject")
    assert record.real_name == "DOTTED-PATH-MARKER"


# --- identityVerificationId는 발급자에게만 귀속된다 (#85 코드리뷰 지적 1) -----------


@pytest.mark.django_db
def test_start_verification_requires_authentication(client):
    response = client.post("/api/verification/start")
    assert response.status_code == 401


@pytest.mark.django_db
def test_start_verification_issues_a_fresh_id_bound_to_the_caller(client):
    pair = _login(client)
    response = client.post("/api/verification/start", **_auth_header(pair["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["identity_verification_id"]

    from verification.models import VerificationRequest

    record = VerificationRequest.objects.get(
        identity_verification_id=body["identity_verification_id"]
    )
    assert record.user.social_accounts.filter(provider_uid="verify-subject").exists()


@pytest.mark.django_db
def test_a_leaked_identity_verification_id_cannot_be_claimed_by_a_different_account(client):
    """핵심 취약점 회귀 테스트(#85 코드리뷰 지적 1).

    identityVerificationId는 리다이렉트 URL·브라우저 히스토리로 노출될 수 있는
    값이다. 그 값을 서버가 발급자에게 귀속시켜 두지 않으면, 전혀 다른 계정이
    그 값을 그대로 `POST /verification/verify`에 제출해 원래 발급받은 사람의
    CI/DI로 VERIFIED가 될 수 있었다 — 미성년자가 성년 게이트를 통과하거나
    실소유자가 자전거래로 오차단되는 결과로 이어진다. 서버는 "요청자 본인이
    발급받은 값인가"를 확인해 이 도용을 막아야 한다.
    """
    victim = _login(client, uid="binding-victim", email="binding-victim@example.com")
    attacker = _login(client, uid="binding-attacker", email="binding-attacker@example.com")

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification._DottedPathTestVerificationAdapter"
        )
    ):
        leaked_token = _start(client, victim["access"])

        attacker_response = client.post(
            "/api/verification/verify",
            data={"verification_token": leaked_token},
            content_type="application/json",
            **_auth_header(attacker["access"]),
        )

    assert attacker_response.status_code == 403

    attacker_verification = Verification.objects.filter(
        user__social_accounts__provider_uid="binding-attacker"
    ).first()
    assert (
        attacker_verification is None
        or attacker_verification.status != Verification.Status.VERIFIED
    )


@pytest.mark.django_db
def test_verify_rejects_a_token_that_was_never_issued_in_real_adapter_mode(client):
    pair = _login(client)

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification._DottedPathTestVerificationAdapter"
        )
    ):
        response = client.post(
            "/api/verification/verify",
            data={"verification_token": "made-up-id-nobody-issued"},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_successfully_consumed_token_cannot_be_replayed(client):
    pair = _login(client)

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification._DottedPathTestVerificationAdapter"
        )
    ):
        token = _start(client, pair["access"])
        first = client.post(
            "/api/verification/verify",
            data={"verification_token": token},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )
        assert first.status_code == 200

        second = client.post(
            "/api/verification/verify",
            data={"verification_token": token},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert second.status_code == 403



class FakeDottedPathVerificationAdapter(FakeVerificationAdapter):
    """클래스명이 "Fake"로 시작하는 dotted-path 어댑터(#85 코드리뷰 지적 5).

    `VERIFICATION_ADAPTER_MODE`에 리터럴 "fake"가 아니라 이 dotted path를
    직접 지목해도(배포 부팅 가드 `is_fake_adapter_binding`이 이미 이런 값을
    fake로 본다), `verify()`의 identityVerificationId 소유권 확인이 같은
    판정을 쓰지 않으면 이 클래스를 "실물"로 오인해 `/verification/start` 없이는
    영원히 403이 난다 — 배포 가드는 통과했는데 본인확인 자체가 불가능해지는
    상황이다.
    """


@pytest.mark.django_db
def test_a_fake_named_dotted_path_does_not_require_verification_start(client):
    """리터럴 "fake"가 아니라 dotted path로 지목된 Fake 클래스도, `/verification/start`
    없이 곧장 `/verification/verify`를 부를 수 있어야 한다(#85 코드리뷰 지적 5)."""

    pair = _login(client)

    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_verification.FakeDottedPathVerificationAdapter"
        )
    ):
        response = client.post(
            "/api/verification/verify",
            data={"verification_token": _fake_token("홍길동", "1990-05-15", "ci-1", "di-1")},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "verified"



# --- 본인확인 응답의 휴대폰 번호 -> PhoneContact (#51 코드리뷰 지적 1) -----------


@pytest.mark.django_db
def test_verification_with_phone_number_populates_encrypted_phone_contact(client):
    """알림(#51)이 실제로 문자를 보낼 대상 번호가 이 프로젝트 어디에도 없었다 —
    본인확인이 이미 휴대폰으로 이루어지므로 그 응답이 채우는 것이 자연스러운
    지점이다. 여기서도 평문으로 남기지 않는다(#51 코드리뷰 지적 3)."""

    from accounts.models import PhoneContact

    pair = _login(client, uid="verify-phone-subject")

    response = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "홍길동", "1990-05-15", "ci-phone-1", "di-phone-1", phone="010-1234-5678"
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200

    contact = PhoneContact.objects.get(
        user__social_accounts__provider_uid="verify-phone-subject"
    )
    assert "1234" not in contact.phone_number_encrypted
    assert contact.phone_number == "01012345678"


@pytest.mark.django_db
def test_verification_without_phone_number_does_not_create_phone_contact(client):
    """4필드 토큰(휴대폰 번호 없음)은 기존 동작 그대로 — PhoneContact가
    만들어지지 않는다(#51은 없다고 본인확인 자체를 막지 않는다)."""

    from accounts.models import PhoneContact

    pair = _login(client, uid="verify-no-phone-subject")

    response = client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token("홍길동", "1990-05-15", "ci-no-phone", "di-no-phone")},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    assert not PhoneContact.objects.filter(
        user__social_accounts__provider_uid="verify-no-phone-subject"
    ).exists()



@pytest.mark.django_db
def test_underage_verification_with_phone_number_does_not_create_phone_contact(client):
    """#51 2차 코드리뷰 지적 4: 미성년자는 CI/DI와 같은 이유로 PhoneContact도
    남기지 않는다 — 그 계정에는 삭제 경로가 없으므로 여기서 막지 않으면
    영구히 잔존한다."""

    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import PhoneContact

    pair = _login(client, uid="verify-underage-phone-subject")

    today = timezone.localdate()
    clearly_minor_birth = today - timedelta(days=365 * 10)

    response = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "미성년자",
                clearly_minor_birth.isoformat(),
                "ci-underage-phone",
                "di-underage-phone",
                phone="010-1234-5678",
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.json()["status"] == "underage"
    assert not PhoneContact.objects.filter(
        user__social_accounts__provider_uid="verify-underage-phone-subject"
    ).exists()


@pytest.mark.django_db
def test_downgrading_to_underage_deletes_previously_stored_phone_contact(client):
    """재확인으로 성인 → 미성년 판정이 뒤집히면 이미 저장돼 있던 PhoneContact도
    지운다(위 test_downgrading_to_underage_clears_previously_stored_ci_and_di
    와 같은 시나리오, CI/DI 대신 PhoneContact를 본다)."""

    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import PhoneContact

    pair = _login(client, uid="downgrade-phone-subject", email="downgrade-phone@example.com")

    first = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "한때성인",
                "1990-01-01",
                "ci-downgrade-phone-1",
                "di-downgrade-phone-1",
                phone="010-1234-5678",
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert first.json()["status"] == "verified"
    assert PhoneContact.objects.filter(
        user__social_accounts__provider_uid="downgrade-phone-subject"
    ).exists()

    today = timezone.localdate()
    clearly_minor_birth = today - timedelta(days=365 * 10)

    second = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "사실은미성년",
                clearly_minor_birth.isoformat(),
                "ci-downgrade-phone-1",
                "di-downgrade-phone-1",
                phone="010-1234-5678",
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert second.json()["status"] == "underage"

    assert not PhoneContact.objects.filter(
        user__social_accounts__provider_uid="downgrade-phone-subject"
    ).exists()



@pytest.mark.django_db
def test_reverifying_as_adult_without_a_phone_number_preserves_the_existing_phone_contact(client):
    """#51 3차 코드리뷰 지적 2: 2차 수정의 `else` 분기가 UNDERAGE와 "VERIFIED
    인데 벤더가 phoneNumber를 안 준 경우"를 하나로 묶어, 재확인 때마다 벤더가
    이 필드를 생략하면 이미 저장돼 있던 정상 번호까지 조용히 지웠다.
    verify()가 PhoneContact를 채우는 유일한 지점이므로, 그 계정은 이후
    영구히 SMS를 못 받는다 — 성인 재확인에 phoneNumber가 없다고 기존 값을
    지우면 안 된다."""

    from accounts.models import PhoneContact

    pair = _login(client, uid="reverify-no-phone-subject")

    first = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "홍길동",
                "1990-05-15",
                "ci-reverify-1",
                "di-reverify-1",
                phone="010-1234-5678",
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert first.json()["status"] == "verified"

    contact = PhoneContact.objects.get(
        user__social_accounts__provider_uid="reverify-no-phone-subject"
    )
    assert contact.phone_number == "01012345678"

    # 재확인 — 이번에는 벤더(Fake 토큰)가 phoneNumber를 주지 않는다(4필드 토큰).
    second = client.post(
        "/api/verification/verify",
        data={
            "verification_token": _fake_token(
                "홍길동", "1990-05-15", "ci-reverify-2", "di-reverify-2"
            )
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert second.json()["status"] == "verified"

    # 기존 PhoneContact가 지워지지 않고 그대로 남아 있다.
    contact.refresh_from_db()
    assert contact.phone_number == "01012345678"
