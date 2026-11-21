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


def _embedded_fonts(pdf: bytes) -> list[str]:
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    # 서브셋 접두(`ABCDEF+`)는 담긴 글자에 따라 바뀐다 — 이름만 본다.
    return sorted(str(font["/BaseFont"]).split("+", 1)[-1] for font in page["/Resources"]["/Font"].values())


def test_sheets_drawn_one_after_another_each_carry_their_own_text_and_both_fonts(client, closed):
    """글꼴 준비를 프로세스에서 한 번만 한다(#1196) — 앞 장의 글자·글꼴이 뒤 장에 새지 않는다."""

    sponsor, contest, deadline = closed
    names = ["김첫째", "박둘째", "이셋째"]

    pdfs = [_preview(client, sponsor["access"], contest["id"], _fields(deadline, recipient_name=name)) for name in names]

    for name, response in zip(names, pdfs, strict=True):
        assert response.status_code == 200, response.content
        text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text().replace(" ", "")
        assert name in text
        assert [other for other in names if other != name and other in text] == []
        assert _embedded_fonts(response.content) == ["Certificate-Serif", "Certificate-Serif-Bold"]


def test_drawing_again_does_not_load_the_fonts_again(closed, monkeypatch):
    """한 장 그리기가 매번 woff 두 개(3MB)를 풀어 0.3초를 쓰던 것(#1196) — 두 번째부터는 글꼴을 다시 풀지 않는다.

    시간으로 재면 실행기 속도에 흔들린다(CI 가 이 머신의 세 배 느렸다) — woff 를 푸는 횟수를 센다.
    """

    from datetime import date

    from weasyprint.text import fonts

    from certificates import rendering

    sheet = rendering.CertificateSheet(
        text=rendering.CertificateText(
            award_name="최우수상",
            recipient_name="김코드밋",
            body="위 사람은 뛰어난 완성도로 우수한 성과를 거두었기에 이 상장을 수여합니다.",
            giver_name="홍길동",
            giver_title="심사위원장",
            award_date=date(2026, 11, 21),
        ),
        contest_title="상장 공모전",
        number="2026-0001-001",
        verify_url=rendering.verify_url("token"),
    )
    rendering.render_certificate_pdf(sheet)

    unpacked: list[object] = []
    real_ttfont = fonts.TTFont

    def counting_ttfont(*args: object, **kwargs: object) -> object:
        unpacked.append(args)
        return real_ttfont(*args, **kwargs)

    monkeypatch.setattr(fonts, "TTFont", counting_ttfont)
    rendering.render_certificate_pdf(sheet)
    rendering.render_certificate_pdf(sheet)

    assert unpacked == []


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
