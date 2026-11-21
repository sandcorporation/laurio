"""받는 사람의 상장(#1130, 스펙 #1071 결정 5·G6).

받는 사람은 내 상장 목록을 보고, PDF 를 받고, 확인 페이지를 닫았다 열 수 있다. 남의 상장은
존재를 숨긴다(404). 탈퇴하면 확인 페이지가 닫히고 이름이 지워진다.
"""

from __future__ import annotations

import io

from accounts.withdrawal import execute_withdrawal
from certificates.models import Certificate
from django.contrib.auth import get_user_model
from pypdf import PdfReader
from storage.adapters import Bucket, get_storage_adapter

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

MINE = "/api/certificates/mine"
PDF = "/api/certificates/{id}/pdf"
VISIBILITY = "/api/certificates/{id}/visibility"
VERIFY = "/api/certificates/verify/{token}"


def _mine(client, user):
    return client.get(MINE, **_auth_header(user["access"]))


def _set_hidden(client, user, certificate_id: int, hidden: bool):
    return client.post(
        VISIBILITY.format(id=certificate_id),
        data={"hidden": hidden},
        content_type="application/json",
        **_auth_header(user["access"]),
    )


def _verify_state(client, certificate_id: int) -> str:
    token = Certificate.objects.get(id=certificate_id).token
    return client.get(VERIFY.format(token=token)).json()["state"]


def test_recipient_sees_own_certificates_only(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    first, second = world["devs"]

    response = _mine(client, first)

    assert response.status_code == 200, response.content
    [row] = response.json()
    assert row == {
        "id": issued["id"],
        "submission_id": world["submissions"][0]["id"],
        "contest_id": world["contest"]["id"],
        "contest_title": world["contest"]["title"],
        "number": issued["number"],
        "award_name": "최우수상",
        "state": "valid",
        "hidden": False,
        "verify_url": issued["verify_url"],
    }
    assert _mine(client, second).json() == []


def test_mine_requires_login(client):
    assert client.get(MINE).status_code == 401


def test_cancelled_shows_as_cancelled_and_reissued_old_one_is_dropped(client, world, blank_renderer):
    sponsor = world["sponsor"]["access"]
    [first] = _issue(client, world, [_item(world, 0)]).json()
    [second] = _issue(client, world, [_item(world, 1)]).json()
    client.post(_url(world, f"/{first['id']}/cancel"), **_auth_header(sponsor))
    new = client.post(
        _url(world, f"/{second['id']}/reissue"),
        data=_text(world, award_name="대상"),
        content_type="application/json",
        **_auth_header(sponsor),
    ).json()

    [cancelled] = _mine(client, world["devs"][0]).json()
    [reissued] = _mine(client, world["devs"][1]).json()

    assert (cancelled["id"], cancelled["state"]) == (first["id"], "cancelled")
    assert (reissued["id"], reissued["state"], reissued["award_name"]) == (new["id"], "valid", "대상")


def test_recipient_downloads_the_same_pdf_and_others_cannot(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    first, second = world["devs"]
    by_sponsor = client.get(_url(world, f"/{issued['id']}/pdf"), **_auth_header(world["sponsor"]["access"]))

    mine = client.get(PDF.format(id=issued["id"]), **_auth_header(first["access"]))

    assert mine.status_code == 200
    assert mine["Content-Type"] == "application/pdf"
    assert mine.content == by_sponsor.content
    for stranger in (second, world["sponsor"], world["outsider"]):
        assert client.get(PDF.format(id=issued["id"]), **_auth_header(stranger["access"])).status_code == 404


def test_cancelled_certificate_pdf_is_refused(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    client.post(_url(world, f"/{issued['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))

    response = client.get(PDF.format(id=issued["id"]), **_auth_header(world["devs"][0]["access"]))

    assert response.status_code == 409


def test_recipient_closes_and_reopens_the_verify_page(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    dev = world["devs"][0]

    closed = _set_hidden(client, dev, issued["id"], True)

    assert closed.status_code == 200, closed.content
    assert closed.json()["hidden"] is True
    assert _verify_state(client, issued["id"]) == "hidden"

    reopened = _set_hidden(client, dev, issued["id"], False)

    assert reopened.json()["hidden"] is False
    assert _verify_state(client, issued["id"]) == "valid"


def test_others_cannot_close_someone_elses_verify_page(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()

    for stranger in (world["devs"][1], world["sponsor"]):
        assert _set_hidden(client, stranger, issued["id"], True).status_code == 404
    assert _verify_state(client, issued["id"]) == "valid"


def _withdraw(world, index: int, capture):
    user = get_user_model().objects.get(id=world["devs"][index]["user_id"])
    with capture(execute=True):
        execute_withdrawal(user)


def test_withdrawal_erases_name_and_pdf_and_keeps_the_row(
    client, world, blank_renderer, django_capture_on_commit_callbacks
):
    sponsor = world["sponsor"]["access"]
    [issued] = _issue(client, world, [_item(world, 0, recipient_name="이첫째")]).json()
    [other] = _issue(client, world, [_item(world, 1)]).json()
    key = Certificate.objects.get(id=issued["id"]).pdf_object_key
    assert get_storage_adapter().read_object(key, bucket=Bucket.PRIVATE) is not None

    _withdraw(world, 0, django_capture_on_commit_callbacks)

    certificate = Certificate.objects.get(id=issued["id"])
    assert (certificate.number, certificate.award_name) == (issued["number"], "최우수상")
    assert certificate.recipient_name == ""
    assert certificate.pdf_object_key == ""
    assert certificate.recipient_hidden_at is not None
    assert get_storage_adapter().read_object(key, bucket=Bucket.PRIVATE) is None
    assert _verify_state(client, issued["id"]) == "hidden"
    assert _verify_state(client, other["id"]) == "valid"

    download = client.get(_url(world, f"/{issued['id']}/pdf"), **_auth_header(sponsor))
    assert download.status_code == 404
    assert "탈퇴" in download.json()["detail"]
    board = client.get(_url(world), **_auth_header(sponsor)).json()
    flags = {row["id"]: row["pdf_available"] for row in board["certificates"]}
    assert flags == {issued["id"]: False, other["id"]: True}
    reissue = client.post(
        _url(world, f"/{issued['id']}/reissue"),
        data=_text(world),
        content_type="application/json",
        **_auth_header(sponsor),
    )
    assert reissue.status_code == 409
    assert "탈퇴" in reissue.json()["detail"]


def test_bundle_skips_withdrawn_recipients(client, world, blank_renderer, django_capture_on_commit_callbacks):
    sponsor = world["sponsor"]["access"]
    _issue(client, world, [_item(world, 0, recipient_name="이첫째"), _item(world, 1, recipient_name="김둘째")])

    _withdraw(world, 0, django_capture_on_commit_callbacks)

    bundle = client.get(_url(world, "/bundle.pdf"), **_auth_header(sponsor))
    assert bundle.status_code == 200
    assert len(PdfReader(io.BytesIO(bundle.content)).pages) == 1


def test_bundle_with_ids_rejects_a_withdrawn_recipients_certificate(
    client, world, blank_renderer, django_capture_on_commit_callbacks
):
    sponsor = world["sponsor"]["access"]
    first, second = _issue(
        client, world, [_item(world, 0, recipient_name="이첫째"), _item(world, 1, recipient_name="김둘째")]
    ).json()
    _withdraw(world, 0, django_capture_on_commit_callbacks)

    response = client.get(_url(world, f"/bundle.pdf?ids={first['id']},{second['id']}"), **_auth_header(sponsor))

    assert response.status_code == 400
    assert first["number"] in response.json()["detail"]
    assert "탈퇴" in response.json()["detail"]


def test_withdrawn_submitter_cannot_receive_a_new_certificate(
    client, world, blank_renderer, django_capture_on_commit_callbacks
):
    _withdraw(world, 0, django_capture_on_commit_callbacks)

    response = _issue(client, world, [_item(world, 0)])

    assert response.status_code == 409
    assert not Certificate.objects.exists()


def test_failed_pdf_delete_does_not_block_withdrawal(
    client, world, blank_renderer, django_capture_on_commit_callbacks, monkeypatch, caplog
):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    adapter = get_storage_adapter()

    def broken(*args, **kwargs):
        raise OSError("저장소가 닫혔다")

    monkeypatch.setattr(type(adapter), "delete_object", broken)

    _withdraw(world, 0, django_capture_on_commit_callbacks)

    assert not get_user_model().objects.get(id=world["devs"][0]["user_id"]).is_active
    assert Certificate.objects.get(id=issued["id"]).pdf_object_key == ""
    assert "상장 PDF 를 지우지 못했다" in caplog.text


def test_e2e_seed_issues_one_certificate_to_a_fresh_submitter(db, blank_renderer):
    import io
    import json

    from django.core.management import call_command

    out = io.StringIO()
    call_command("seed_e2e_certificate", run_id="t", stdout=out)
    payload = json.loads(out.getvalue().strip().splitlines()[-1])

    certificate = Certificate.objects.get(id=payload["certificate_id"])
    assert certificate.recipient.username == payload["developer_uid"]
    assert certificate.token == payload["token"]
    assert certificate.cancelled_at is None and certificate.recipient_hidden_at is None
    # `seed_e2e_contests` 의 정리(`[E2E` 접두어 공모전 통째 삭제)에 걸리면 상장의 PROTECT 가 그 정리를 깨뜨린다.
    assert not certificate.contest.title.startswith("[E2E")
    assert certificate.submission.product == "contest"  # 내 참가 현황은 공모전 제출만 보인다
