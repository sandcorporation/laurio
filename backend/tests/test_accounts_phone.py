"""휴대폰 번호 정규화 단위 테스트 (#51 코드리뷰 지적 4)."""

from __future__ import annotations

import pytest

from accounts.phone import InvalidPhoneNumberError, normalize_phone_number


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01012345678", "01012345678"),
        ("010-1234-5678", "01012345678"),
        ("010 1234 5678", "01012345678"),
        ("+82 10-1234-5678", "01012345678"),
        ("82-10-1234-5678", "01012345678"),
    ],
)
def test_normalizes_common_formats(raw, expected):
    assert normalize_phone_number(raw) == expected


def test_strips_a_comma_instead_of_preserving_multi_recipient_injection():
    """알리고의 receiver 파라미터는 콤마로 여러 수신자를 지정한다 — 값 하나에
    콤마가 섞여 들어오면(오염된 입력) 정규화가 콤마를 숫자 아닌 문자로 걷어내
    두 번호를 이어붙인 하나의 문자열로 만든다. 그 결과는 국내 휴대폰 형식
    (10~11자리)을 넘는 길이라 InvalidPhoneNumberError로 거부된다 — 콤마가
    그대로 살아남아 벤더에 "다중 수신자"로 해석되는 경로 자체가 없다."""

    with pytest.raises(InvalidPhoneNumberError):
        normalize_phone_number("01011112222,01099998888")


@pytest.mark.parametrize(
    "raw",
    ["", "not-a-phone", "02-1234-5678", "0101234", "011111122223333"],
)
def test_rejects_non_mobile_formats(raw):
    with pytest.raises(InvalidPhoneNumberError):
        normalize_phone_number(raw)


# --- PhoneContact: 암호화 저장 + 정규화 (#51 코드리뷰 지적 3·4) ------------------


@pytest.mark.django_db
def test_phone_contact_stores_ciphertext_not_plaintext():
    from django.contrib.auth import get_user_model

    from accounts.models import PhoneContact

    user = get_user_model().objects.create_user(username="phone-owner", password="pw-12345678")
    contact = PhoneContact.objects.create(user=user, phone_number="010-1234-5678")

    assert contact.phone_number_encrypted != "01012345678"
    assert "1234" not in contact.phone_number_encrypted

    contact.refresh_from_db()
    assert contact.phone_number == "01012345678"


@pytest.mark.django_db
def test_phone_contact_rejects_an_invalid_number():
    from django.contrib.auth import get_user_model

    from accounts.models import PhoneContact
    from accounts.phone import InvalidPhoneNumberError

    user = get_user_model().objects.create_user(username="phone-owner-2", password="pw-12345678")

    with pytest.raises(InvalidPhoneNumberError):
        PhoneContact.objects.create(user=user, phone_number="not-a-phone")
