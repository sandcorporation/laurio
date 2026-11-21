"""상장 발급·목록·받기·묶음·취소·다시 발급(#1127, 스펙 #1071 「발급 규칙」).

시임은 HTTP 다. 한 장을 그리는 데 CPU 0.4초가 들어, 실제 렌더는 맨 앞 시험 하나만 쓰고
나머지는 빈 한 쪽 PDF 로 바꿔 둔다(틀은 #1126 시험이 본다).
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from contests.models import Category, DeliverableType

from tests.integration.test_source_readings import (
    _auth_header,
    _close_contest,
    _publish_contest,
    _submit,
    _verified_user,
)

BASE = "/api/contests/{contest_id}/certificates"
ME_NOTIFICATIONS = "/api/notifications/me"


@pytest.fixture(scope="module", autouse=True)
def _warm_renderer():
    import weasyprint  # noqa: F401


@pytest.fixture
def blank_renderer(monkeypatch):
    """한 장을 빈 A4 가로 한 쪽으로 — 번호를 쪽 메타데이터에 실어 묶음 순서를 볼 수 있게."""

    def fake_render(sheet) -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=842, height=595)
        writer.add_metadata({"/Title": sheet.number})
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    monkeypatch.setattr("certificates.rendering.render_certificate_pdf", fake_render)


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.fixture
def world(client, category, landing_type):
    """마감이 지난 공모전 하나와 제출자 둘, 제출하지 않은 사람 하나."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    devs = [_verified_user(client, f"dev-{i}", f"dev-ci-{i}") for i in (1, 2)]
    submissions = [_submit(client, dev, contest["id"], requirement_id=requirement_id) for dev in devs]
    outsider = _verified_user(client, "dev-3", "dev-ci-3")
    _close_contest(client, contest, deadline=deadline)
    return {
        "sponsor": sponsor,
        "contest": contest,
        "deadline": deadline,
        "devs": devs,
        "submissions": submissions,
        "outsider": outsider,
    }


def _text(world, **overrides) -> dict:
    text = {
        "award_name": "최우수상",
        "recipient_name": "김코드밋",
        "body": "위 사람은 뛰어난 완성도로 우수한 성과를 거두었기에 이 상장을 수여합니다.",
        "giver_name": "홍길동",
        "giver_title": "심사위원장",
        "award_date": timezone.localtime(world["deadline"]).date().isoformat(),
    }
    text.update(overrides)
    return text


def _url(world, suffix: str = "") -> str:
    return BASE.format(contest_id=world["contest"]["id"]) + suffix


def _issue(client, world, items, *, access=None):
    return client.post(
        _url(world),
        data={"items": items},
        content_type="application/json",
        **_auth_header(access or world["sponsor"]["access"]),
    )


def _item(world, index: int, **overrides) -> dict:
    return {"submission_id": world["submissions"][index]["id"], "text": _text(world, **overrides)}


def _board(client, world) -> dict:
    response = client.get(_url(world), **_auth_header(world["sponsor"]["access"]))
    assert response.status_code == 200, response.content
    return response.json()


def _notification_types(client, dev) -> list[str]:
    response = client.get(ME_NOTIFICATIONS, **_auth_header(dev["access"]))
    assert response.status_code == 200, response.content
    return [n["notification_type"] for n in response.json()["items"]]


def test_issued_certificate_is_stored_once_and_downloads_as_the_rendered_sheet(
    client, world, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = _issue(client, world, [_item(world, 0, recipient_name="이첫째")])

    assert response.status_code == 201, response.content
    [issued] = response.json()
    year = timezone.localtime(timezone.now()).year
    assert issued["number"] == f"{year}-{world['contest']['id']:04d}-001"
    assert issued["verify_url"].rsplit("/c/", 1)[1] and len(issued["verify_url"].rsplit("/", 1)[1]) == 22

    pdf = client.get(_url(world, f"/{issued['id']}/pdf"), **_auth_header(world["sponsor"]["access"]))
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    text = PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text().replace(" ", "")
    assert "이첫째" in text
    assert issued["number"] in text
    assert "미리보기" not in text

    assert _notification_types(client, world["devs"][0]) == ["certificate_issued"]
    assert _notification_types(client, world["devs"][1]) == []


def test_board_lists_submitters_defaults_and_issued(client, world, blank_renderer):
    board = _board(client, world)
    assert [r["certificate_id"] for r in board["recipients"]] == [None, None]
    assert board["defaults"]["giver_title"] == ""
    assert board["defaults"]["award_date_min"] == timezone.localtime(world["deadline"]).date().isoformat()
    assert board["certificates"] == []

    issued = _issue(client, world, [_item(world, 0, giver_name="박심사", giver_title="대표")]).json()

    board = _board(client, world)
    assert board["defaults"]["giver_name"] == "박심사"
    assert board["defaults"]["giver_title"] == "대표"
    assert [r["certificate_id"] for r in board["recipients"]] == [issued[0]["id"], None]
    assert [c["number"] for c in board["certificates"]] == [issued[0]["number"]]


def test_issue_several_at_once_and_bundle_them_in_order(client, world, blank_renderer):
    issued = _issue(client, world, [_item(world, 0), _item(world, 1, recipient_name="최둘째")]).json()
    assert [c["number"][-3:] for c in issued] == ["001", "002"]

    bundle = client.get(_url(world, "/bundle.pdf"), **_auth_header(world["sponsor"]["access"]))

    assert bundle.status_code == 200
    assert bundle["Cache-Control"] == "no-store"
    assert len(PdfReader(io.BytesIO(bundle.content)).pages) == 2


def test_bundle_without_certificates_is_404(client, world):
    response = client.get(_url(world, "/bundle.pdf"), **_auth_header(world["sponsor"]["access"]))
    assert response.status_code == 404


def test_cancel_frees_the_slot_and_sends_nothing(client, world, blank_renderer, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        [first] = _issue(client, world, [_item(world, 0)]).json()
        cancelled = client.post(_url(world, f"/{first['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))

    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled_at"] is not None
    assert _notification_types(client, world["devs"][0]) == ["certificate_issued"]

    again = client.post(_url(world, f"/{first['id']}/cancel"), **_auth_header(world["sponsor"]["access"]))
    assert again.status_code == 409

    [second] = _issue(client, world, [_item(world, 0)]).json()
    assert second["number"][-3:] == "002"
    board = _board(client, world)
    assert board["recipients"][0]["certificate_id"] == second["id"]


def test_reissue_cancels_and_points_to_the_new_number(
    client, world, blank_renderer, django_capture_on_commit_callbacks
):
    [first] = _issue(client, world, [_item(world, 0)]).json()

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            _url(world, f"/{first['id']}/reissue"),
            data=_text(world, award_name="우수상"),
            content_type="application/json",
            **_auth_header(world["sponsor"]["access"]),
        )

    assert response.status_code == 201, response.content
    new = response.json()
    assert new["number"][-3:] == "002"
    assert new["award_name"] == "우수상"
    certificates = {c["id"]: c for c in _board(client, world)["certificates"]}
    assert certificates[first["id"]]["cancelled_at"] is not None
    assert certificates[first["id"]]["replaced_by_id"] == new["id"]
    assert "certificate_reissued" in _notification_types(client, world["devs"][0])

    stale = client.post(
        _url(world, f"/{first['id']}/reissue"),
        data=_text(world),
        content_type="application/json",
        **_auth_header(world["sponsor"]["access"]),
    )
    assert stale.status_code == 409


def test_one_valid_certificate_per_person(client, world, blank_renderer):
    assert _issue(client, world, [_item(world, 0)]).status_code == 201

    assert _issue(client, world, [_item(world, 0)]).status_code == 409
    assert _issue(client, world, [_item(world, 1), _item(world, 1)]).status_code == 422


def test_only_submitters_of_this_contest_can_receive(client, world, blank_renderer):
    response = _issue(client, world, [{"submission_id": 999_999, "text": _text(world)}])
    assert response.status_code == 422


def test_text_rules_apply_to_every_item(client, world, blank_renderer):
    response = _issue(client, world, [_item(world, 0), _item(world, 1, recipient_name="운영자")])

    assert response.status_code == 422
    assert _board(client, world)["certificates"] == []


def test_before_deadline_is_refused(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type, deadline_at=deadline)

    response = client.get(BASE.format(contest_id=contest["id"]), **_auth_header(sponsor["access"]))

    assert response.status_code == 409


def test_other_people_cannot_reach_the_surface(client, world, blank_renderer):
    [issued] = _issue(client, world, [_item(world, 0)]).json()
    dev = world["devs"][0]

    assert client.get(_url(world), **_auth_header(dev["access"])).status_code == 404
    assert _issue(client, world, [_item(world, 1)], access=dev["access"]).status_code == 404
    assert client.get(_url(world, f"/{issued['id']}/pdf"), **_auth_header(dev["access"])).status_code == 404
    assert client.post(_url(world, f"/{issued['id']}/cancel"), **_auth_header(dev["access"])).status_code == 404
