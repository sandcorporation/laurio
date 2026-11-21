"""운영자 상장 목록과 취소(#1131, 스펙 #1071 「화면 · 운영자 앱」).

시임은 HTTP 다. 발급은 개최자 표면으로 하고(렌더는 빈 PDF), 운영자는 세션으로 들어온다.
"""

from __future__ import annotations

import pytest
from contests.models import Contest
from django.core.management import call_command
from django.test import Client

from tests.integration.test_certificate_issue import (  # noqa: F401 — 픽스처
    _auth_header,
    _issue,
    _item,
    _notification_types,
    _url,
    blank_renderer,
    category,
    landing_type,
    world,
)

ORIGIN = "http://testserver"
PW = "operator-pw-9942-xkcd-privacy"


def _operator_client(username: str = "cert-op", *, superuser: bool = False) -> Client:
    call_command("create_operator", username, password=PW, superuser=superuser)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _list_url(world) -> str:
    return f"/api/operator/contests/{world['contest']['id']}/certificates"


def _cancel(operator: Client, world, certificate_id: int):
    return operator.post(f"{_list_url(world)}/{certificate_id}/cancel", HTTP_ORIGIN=ORIGIN)


def test_operator_lists_numbers_recipients_and_status(client, world, blank_renderer):
    first, second = _issue(
        client, world, [_item(world, 0, recipient_name="이첫째"), _item(world, 1, recipient_name="최둘째")]
    ).json()
    client.post(_url(world, f"/{second['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))
    reissued = client.post(
        _url(world, f"/{first['id']}/reissue"),
        data={k: _item(world, 0, recipient_name="이첫째")["text"][k] for k in _item(world, 0)["text"]},
        content_type="application/json",
        **_auth_header(world["sponsor"]["access"]),
    ).json()

    response = _operator_client().get(_list_url(world))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["contest_id"] == world["contest"]["id"]
    rows = {c["number"]: c for c in body["certificates"]}
    assert [c["id"] for c in body["certificates"]] == [reissued["id"], second["id"], first["id"]]
    assert rows[first["number"]]["status"] == "reissued"
    assert rows[second["number"]]["status"] == "cancelled"
    assert rows[reissued["number"]]["status"] == "valid"
    assert rows[second["number"]]["recipient_name"] == "최둘째"


def test_operator_cancel_marks_cancelled_and_notifies_nobody(
    client, world, blank_renderer, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        [issued] = _issue(client, world, [_item(world, 0)]).json()
    operator = _operator_client()

    with django_capture_on_commit_callbacks(execute=True):
        response = _cancel(operator, world, issued["id"])

    assert response.status_code == 200, response.content
    assert response.json()["status"] == "cancelled"
    assert _notification_types(client, world["devs"][0]) == ["certificate_issued"]
    assert _cancel(operator, world, issued["id"]).status_code == 409
    # 자리가 비어 개최자가 새로 발급할 수 있다.
    assert _issue(client, world, [_item(world, 0)]).status_code == 201


def test_operator_cancel_of_unknown_certificate_or_contest_is_404(client, world):
    operator = _operator_client()
    assert _cancel(operator, world, 999_999).status_code == 404
    assert operator.get("/api/operator/contests/999999/certificates").status_code == 404


def test_only_operators_get_in(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()

    assert Client().get(_list_url(world)).status_code == 401
    # 개최자·개발자의 토큰으로는 운영자 표면에 들어가지 못한다.
    sponsor = world["sponsor"]["access"]
    assert client.get(_list_url(world), **_auth_header(sponsor)).status_code == 401
    assert client.post(f"{_list_url(world)}/{issued['id']}/cancel", HTTP_ORIGIN=ORIGIN, **_auth_header(sponsor)).status_code == 401
    # 상장은 그대로다.
    board = client.get(_url(world), **_auth_header(sponsor)).json()
    assert board["certificates"][0]["cancelled_at"] is None


def test_certificate_seed_is_cleared_by_the_next_run_without_a_protected_error(db, monkeypatch):
    """#1131 — 상장이 달린 시드 공모전은 `Certificate` 의 PROTECT 때문에 상장을 먼저 지워야 한다."""

    import io
    import json

    from pypdf import PdfWriter

    from certificates.models import Certificate

    def blank(sheet) -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=842, height=595)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    monkeypatch.setattr("certificates.rendering.render_certificate_pdf", blank)

    def run(run_id: str) -> dict:
        out = io.StringIO()
        call_command("seed_e2e_operator_certificates", run_id=run_id, stdout=out)
        return json.loads(out.getvalue().strip().splitlines()[-1])

    first = run("cert-run-1")
    assert len(first["certificates"]) == 2
    assert Certificate.objects.filter(contest_id=first["contest_id"]).count() == 2

    second = run("cert-run-2")

    assert not Contest.objects.filter(pk=first["contest_id"]).exists()
    assert not Certificate.objects.filter(contest_id=first["contest_id"]).exists()
    assert Certificate.objects.filter(contest_id=second["contest_id"]).count() == 2
