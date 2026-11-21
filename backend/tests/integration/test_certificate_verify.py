"""공개 상장 확인(#1128, 스펙 #1071 「확인 페이지 상태 셋」).

로그인 없이 토큰 하나로 부른다. 상태마다 보여도 되는 칸만 돌아오는지를 본다 — 취소된 것은
새 상장을 가리키지 않고, 받는 사람이 닫은 것은 번호만 남는다. 없는 토큰만 404 다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils import timezone

from certificates.models import Certificate
from core.clock import Clock

from tests.integration.test_certificate_issue import (  # noqa: F401 — 픽스처
    _auth_header,
    _item,
    _issue,
    _text,
    _url,
    blank_renderer,
    category,
    landing_type,
    world,
)
from tests.integration.test_free_contest_award import _freeze

VERIFY = "/api/certificates/verify/{token}"


def _token(certificate_id: int) -> str:
    return Certificate.objects.get(id=certificate_id).token


def _verify(client, token: str):
    return client.get(VERIFY.format(token=token))


def _clock_date() -> str:
    # 발급·취소는 얼린 Clock 으로 찍힌다 — 실제 시계(localdate)와 섞으면 KST 23시대에 하루 어긋난다(#1248).
    return timezone.localtime(Clock.now()).date().isoformat()


def test_valid_certificate_shows_its_text_without_login(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0, recipient_name="이첫째")]).json()

    response = _verify(client, _token(issued["id"]))

    assert response.status_code == 200, response.content
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response.json() == {
        "state": "valid",
        "number": issued["number"],
        "contest_title": world["contest"]["title"],
        "award_name": "최우수상",
        "recipient_name": "이첫째",
        "giver_name": "홍길동",
        "giver_title": "심사위원장",
        "issued_on": _clock_date(),
        "cancelled_on": None,
        "reissued": False,
    }


def test_cancelled_certificate_shows_only_number_contest_and_date(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    client.post(_url(world, f"/{issued['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))

    body = _verify(client, _token(issued["id"])).json()

    assert body["state"] == "cancelled"
    assert body["reissued"] is False
    assert body["cancelled_on"] == _clock_date()
    assert body["contest_title"] == world["contest"]["title"]
    assert body["recipient_name"] is None and body["award_name"] is None


def test_reissued_certificate_says_so_without_pointing_at_the_new_one(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    new = client.post(
        _url(world, f"/{issued['id']}/reissue"),
        data=_text(world, award_name="우수상"),
        content_type="application/json",
        **_auth_header(world["sponsor"]["access"]),
    ).json()

    old_body = _verify(client, _token(issued["id"])).json()

    assert old_body["state"] == "cancelled"
    assert old_body["reissued"] is True
    assert new["number"] not in str(old_body)
    assert _token(new["id"]) not in str(old_body)
    assert _verify(client, _token(new["id"])).json()["award_name"] == "우수상"


def test_hidden_certificate_shows_the_number_only(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    Certificate.objects.filter(id=issued["id"]).update(recipient_hidden_at=timezone.now())

    body = _verify(client, _token(issued["id"])).json()

    assert body["state"] == "hidden"
    assert body["number"] == issued["number"]
    assert {k for k, v in body.items() if v not in (None, False)} == {"state", "number"}


def test_unknown_token_is_404(client, db):
    response = _verify(client, "x" * 22)

    assert response.status_code == 404


def test_dates_follow_frozen_clock_across_midnight(client, world, blank_renderer):
    """얼린 시계가 실제 날짜와 다른 날(이틀 뒤 KST 00:22)이어도 발급·취소 날짜는 얼린 시계를 따른다(#1248)."""
    after_midnight = timezone.make_aware(
        datetime.combine(timezone.localdate() + timedelta(days=2), time(0, 22))
    )
    _freeze(after_midnight)
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    client.post(_url(world, f"/{issued['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))

    body = _verify(client, _token(issued["id"])).json()

    assert body["cancelled_on"] == after_midnight.date().isoformat()
    assert body["cancelled_on"] != timezone.localdate().isoformat()
