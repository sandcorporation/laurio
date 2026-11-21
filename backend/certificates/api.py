"""공모전 상장(스펙 #1071) — 개최자 미리보기(#1126).

미리보기는 발급본과 같은 틀로 그리되 「미리보기」 표시를 얹고 상장 번호·QR 자리에 예시 값을
쓴다. 저장하지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest
from core.banned_words import BannedWordViolation, find_banned_word_violation
from core.clock import Clock
from core.contest_switch import require_contest_product_enabled

from .rendering import CertificateSheet, CertificateText, render_certificate_pdf, verify_url
from .schemas import CertificateTextIn

router = Router(tags=["certificates"])

#: 수여 날짜는 마감일부터 오늘+30일까지(스펙 「입력 제한」).
AWARD_DATE_FUTURE_DAYS = 30

#: 미리보기의 확인 주소 자리 — 실제 토큰(22자)과 같은 길이의 예시 값.
PREVIEW_TOKEN = "x" * 22

_FIELD_LABELS = {
    "award_name": "상 이름",
    "recipient_name": "받는 사람 이름",
    "body": "본문",
    "giver_name": "수여자 이름",
    "giver_title": "직함",
}
_REQUIRED = ("award_name", "recipient_name", "giver_name")
#: 사칭 목록까지 거는 칸 — 사람 이름 자리다. 나머지는 욕설만 본다.
_NAME_FIELDS = ("recipient_name", "giver_name")


def _get_closed_owned_contest(request: HttpRequest, contest_id: int) -> Contest:
    """개최자 본인의, 마감이 지난 공모전만 통과한다. 남의 공모전은 존재를 숨긴다(404)."""

    require_contest_product_enabled()
    contest = Contest.objects.select_related("sponsor").filter(id=contest_id).first()
    auth_user = getattr(request, "auth_user", None)
    if contest is None or auth_user is None or contest.sponsor.user_id != auth_user.id:
        raise HttpError(404, "공모전을 찾을 수 없습니다.")
    if contest.status == Contest.Status.DRAFT or Clock.now() < contest.deadline_at:
        raise HttpError(409, "상장은 마감 뒤에 발급할 수 있습니다.")
    return contest


def _clean_text(contest: Contest, payload: CertificateTextIn, *, today: date) -> CertificateText:
    values = {
        name: " ".join(getattr(payload, name).split()) if name != "body" else getattr(payload, name)
        for name in _FIELD_LABELS
    }
    if "\n" in values["body"] or "\r" in values["body"]:
        raise HttpError(422, "본문에는 줄바꿈을 넣을 수 없습니다.")
    values["body"] = " ".join(values["body"].split())

    for name in _REQUIRED:
        if not values[name]:
            raise HttpError(422, f"{_FIELD_LABELS[name]}을(를) 입력하세요.")

    for name, label in _FIELD_LABELS.items():
        if not values[name]:
            continue
        violation = find_banned_word_violation(values[name], check_impersonation=name in _NAME_FIELDS)
        if violation is BannedWordViolation.IMPERSONATION:
            raise HttpError(422, f"{label}에는 운영진을 뜻하는 말을 쓸 수 없습니다.")
        if violation is BannedWordViolation.PROFANITY:
            raise HttpError(422, f"{label}에 욕설을 쓸 수 없습니다.")

    earliest = timezone.localtime(contest.deadline_at).date()
    latest = today + timedelta(days=AWARD_DATE_FUTURE_DAYS)
    if not earliest <= payload.award_date <= latest:
        raise HttpError(
            422,
            f"수여 날짜는 {earliest.isoformat()}부터 {latest.isoformat()}까지 고를 수 있습니다.",
        )

    return CertificateText(award_date=payload.award_date, **values)


def _pdf_response(pdf: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response


@router.post("/contests/{contest_id}/certificates/preview", auth=jwt_auth)
def preview_certificate(request: HttpRequest, contest_id: int, payload: CertificateTextIn):
    contest = _get_closed_owned_contest(request, contest_id)
    today = timezone.localtime(Clock.now()).date()
    text = _clean_text(contest, payload, today=today)
    sheet = CertificateSheet(
        text=text,
        contest_title=contest.title,
        number=f"{today.year}-{contest.id:04d}-000",
        verify_url=verify_url(PREVIEW_TOKEN),
        preview=True,
    )
    return _pdf_response(render_certificate_pdf(sheet), "certificate-preview.pdf")
