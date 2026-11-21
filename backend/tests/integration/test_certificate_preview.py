"""상장 미리보기(#1126, 스펙 #1071) — 개최자가 칸을 보내면 발급본과 같은 틀의 PDF 를 돌려준다.

시임은 HTTP 다. PDF 는 쪽 수·크기·글자로만 본다(틀의 모양은 PR 의 그림으로 본다).
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.utils import timezone
from pypdf import PdfReader

from contests.models import Category, DeliverableType

from tests.integration.test_source_readings import _auth_header, _close_contest, _publish_contest, _verified_user

PREVIEW_URL = "/api/contests/{contest_id}/certificates/preview"


@pytest.fixture(scope="module", autouse=True)
def _warm_renderer():
    # WeasyPrint 를 처음 부르는 값(시스템 라이브러리 적재)은 시험 본문 밖에서 치른다.
    import weasyprint  # noqa: F401


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.fixture
def published(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    return sponsor, contest, deadline


@pytest.fixture
def closed(client, published):
    sponsor, contest, deadline = published
    _close_contest(client, contest, deadline=deadline)
    return sponsor, contest, deadline


def _fields(deadline, **overrides) -> dict:
    fields = {
        "award_name": "최우수상",
        "recipient_name": "김코드밋",
        "body": "위 사람은 뛰어난 완성도로 우수한 성과를 거두었기에 이 상장을 수여합니다.",
        "giver_name": "홍길동",
        "giver_title": "심사위원장",
        "award_date": timezone.localtime(deadline).date().isoformat(),
    }
    fields.update(overrides)
    return fields


def _preview(client, access: str, contest_id: int, fields: dict):
    return client.post(
        PREVIEW_URL.format(contest_id=contest_id),
        data=fields,
        content_type="application/json",
        **_auth_header(access),
    )


def test_preview_is_one_landscape_a4_page_marked_as_preview(client, closed):
    sponsor, contest, deadline = closed

    response = _preview(client, sponsor["access"], contest["id"], _fields(deadline))

    assert response.status_code == 200, response.content
    assert response["Content-Type"] == "application/pdf"
    assert response["Cache-Control"] == "no-store"
    reader = PdfReader(io.BytesIO(response.content))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert (round(float(box.width)), round(float(box.height))) == (842, 595)
    text = reader.pages[0].extract_text().replace(" ", "")
    for expected in ("미리보기", "최우수상", "김코드밋", "홍길동", contest["title"].replace(" ", "")):
        assert expected in text


def test_preview_before_deadline_is_refused(client, published):
    sponsor, contest, deadline = published

    response = _preview(client, sponsor["access"], contest["id"], _fields(deadline))

    assert response.status_code == 409


def test_another_sponsors_contest_is_hidden(client, closed):
    _, contest, deadline = closed
    stranger = _verified_user(client, "stranger-1", "stranger-ci-1")

    response = _preview(client, stranger["access"], contest["id"], _fields(deadline))

    assert response.status_code == 404


def test_preview_needs_login(client, closed):
    _, contest, deadline = closed

    response = client.post(
        PREVIEW_URL.format(contest_id=contest["id"]),
        data=_fields(deadline),
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"award_name": "가" * 21},
        {"recipient_name": "가" * 21},
        {"body": "가" * 121},
        {"giver_name": "가" * 31},
        {"giver_title": "가" * 31},
        {"award_name": "   "},
        {"recipient_name": ""},
        {"giver_name": ""},
        {"body": "첫 줄\n둘째 줄"},
        {"award_name": "씨발상"},
        {"body": "씨발 잘했다"},
        {"giver_title": "씨발"},
        {"recipient_name": "운영자"},
        {"giver_name": "관리자"},
    ],
    ids=lambda o: next(iter(o)),
)
def test_fields_outside_the_limits_are_refused(client, closed, overrides):
    sponsor, contest, deadline = closed

    response = _preview(client, sponsor["access"], contest["id"], _fields(deadline, **overrides))

    assert response.status_code == 422, response.content


def test_award_date_must_fall_between_deadline_and_thirty_days_out(client, closed):
    sponsor, contest, deadline = closed
    deadline_day = timezone.localtime(deadline).date()

    too_early = _preview(
        client, sponsor["access"], contest["id"],
        _fields(deadline, award_date=(deadline_day - timedelta(days=1)).isoformat()),
    )
    too_late = _preview(
        client, sponsor["access"], contest["id"],
        _fields(deadline, award_date=(deadline_day + timedelta(days=40)).isoformat()),
    )

    assert too_early.status_code == 422
    assert too_late.status_code == 422
