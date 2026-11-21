"""공모전 상장(스펙 #1071) — 개최자 표면: 미리보기(#1126), 발급·목록·받기·묶음·취소·다시 발급(#1127).

미리보기는 발급본과 같은 틀로 그리되 「미리보기」 표시를 얹고 상장 번호·QR 자리에 예시 값을
쓴다. 저장하지 않는다. 발급 규칙은 `services.py` 에 있다.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest, ContestSubmission
from core.banned_words import BannedWordViolation, find_banned_word_violation
from core.clock import Clock
from core.contest_switch import require_contest_product_enabled

from . import services
from .models import Certificate
from .rendering import CertificateSheet, CertificateText, render_certificate_pdf, verify_url
from .schemas import (
    CertificateBoardOut,
    CertificateDefaultsOut,
    CertificateIssueIn,
    CertificateOut,
    CertificateRecipientOut,
    CertificateTextIn,
)

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


def _award_date_range(contest: Contest, today: date) -> tuple[date, date]:
    return timezone.localtime(contest.deadline_at).date(), today + timedelta(days=AWARD_DATE_FUTURE_DAYS)


def _today() -> date:
    return timezone.localtime(Clock.now()).date()


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

    earliest, latest = _award_date_range(contest, today)
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
    today = _today()
    text = _clean_text(contest, payload, today=today)
    sheet = CertificateSheet(
        text=text,
        contest_title=contest.title,
        number=f"{today.year}-{contest.id:04d}-000",
        verify_url=verify_url(PREVIEW_TOKEN),
        preview=True,
    )
    return _pdf_response(render_certificate_pdf(sheet), "certificate-preview.pdf")


def _certificate_out(certificate: Certificate) -> CertificateOut:
    return CertificateOut(
        id=certificate.id,
        number=certificate.number,
        submission_id=certificate.submission_id,
        award_name=certificate.award_name,
        recipient_name=certificate.recipient_name,
        body=certificate.body,
        giver_name=certificate.giver_name,
        giver_title=certificate.giver_title,
        award_date=certificate.award_date,
        issued_at=certificate.issued_at,
        cancelled_at=certificate.cancelled_at,
        replaced_by_id=certificate.replaced_by_id,
        verify_url=verify_url(certificate.token),
    )


def _rule_error(error: services.CertificateRuleError) -> HttpError:
    return HttpError(error.status, error.message)


@router.get("/contests/{contest_id}/certificates", auth=jwt_auth, response=CertificateBoardOut)
def certificate_board(request: HttpRequest, contest_id: int):
    """발급 화면 한 벌 — 칸 기본값, 발급할 수 있는 사람, 발급한 것."""

    contest = _get_closed_owned_contest(request, contest_id)
    certificates = list(Certificate.objects.filter(contest=contest).order_by("-id"))
    valid_by_submission = {c.submission_id: c.id for c in certificates if c.is_valid}
    submissions = ContestSubmission.objects.filter(contest=contest).select_related("developer").order_by("id")
    giver_name, giver_title = services.giver_defaults(contest)
    earliest, latest = _award_date_range(contest, _today())
    return CertificateBoardOut(
        defaults=CertificateDefaultsOut(
            giver_name=giver_name, giver_title=giver_title, award_date_min=earliest, award_date_max=latest
        ),
        recipients=[
            CertificateRecipientOut(
                submission_id=s.id,
                default_recipient_name=s.developer.display_name[:20],
                certificate_id=valid_by_submission.get(s.id),
            )
            for s in submissions
        ],
        certificates=[_certificate_out(c) for c in certificates],
    )


@router.post("/contests/{contest_id}/certificates", auth=jwt_auth, response={201: list[CertificateOut]})
def issue_certificates(request: HttpRequest, contest_id: int, payload: CertificateIssueIn):
    contest = _get_closed_owned_contest(request, contest_id)
    today = _today()
    requests = [
        services.IssueRequest(submission_id=item.submission_id, text=_clean_text(contest, item.text, today=today))
        for item in payload.items
    ]
    try:
        issued = services.issue_certificates(contest=contest, issuer=request.auth_user, requests=requests)
    except services.CertificateRuleError as error:
        raise _rule_error(error) from error
    return 201, [_certificate_out(c) for c in issued]


def _owned_certificate(contest: Contest, certificate_id: int) -> Certificate:
    certificate = Certificate.objects.filter(contest=contest, id=certificate_id).first()
    if certificate is None:
        raise HttpError(404, "상장을 찾을 수 없습니다.")
    return certificate


@router.get("/contests/{contest_id}/certificates/bundle.pdf", auth=jwt_auth)
def download_bundle(request: HttpRequest, contest_id: int):
    """유효한 상장 전부를 한 파일로 — 저장하지 않는다."""

    contest = _get_closed_owned_contest(request, contest_id)
    certificates = list(Certificate.objects.filter(contest=contest, cancelled_at__isnull=True).order_by("id"))
    if not certificates:
        raise HttpError(404, "발급한 상장이 없습니다.")
    try:
        pdf = services.bundle_pdf(certificates)
    except services.CertificateRuleError as error:
        raise _rule_error(error) from error
    return _pdf_response(pdf, f"certificates-{contest.id}.pdf")


@router.get("/contests/{contest_id}/certificates/{certificate_id}/pdf", auth=jwt_auth)
def download_certificate(request: HttpRequest, contest_id: int, certificate_id: int):
    contest = _get_closed_owned_contest(request, contest_id)
    certificate = _owned_certificate(contest, certificate_id)
    try:
        pdf = services.read_pdf(certificate)
    except services.CertificateRuleError as error:
        raise _rule_error(error) from error
    return _pdf_response(pdf, f"certificate-{certificate.number}.pdf")


@router.post("/contests/{contest_id}/certificates/{certificate_id}/cancel", auth=jwt_auth, response=CertificateOut)
def cancel_certificate(request: HttpRequest, contest_id: int, certificate_id: int):
    contest = _get_closed_owned_contest(request, contest_id)
    try:
        certificate = services.cancel_certificate(
            contest=contest, certificate_id=certificate_id, actor=request.auth_user
        )
    except services.CertificateRuleError as error:
        raise _rule_error(error) from error
    return _certificate_out(certificate)


@router.post(
    "/contests/{contest_id}/certificates/{certificate_id}/reissue",
    auth=jwt_auth,
    response={201: CertificateOut},
)
def reissue_certificate(request: HttpRequest, contest_id: int, certificate_id: int, payload: CertificateTextIn):
    contest = _get_closed_owned_contest(request, contest_id)
    text = _clean_text(contest, payload, today=_today())
    try:
        certificate = services.reissue_certificate(
            contest=contest, certificate_id=certificate_id, text=text, issuer=request.auth_user
        )
    except services.CertificateRuleError as error:
        raise _rule_error(error) from error
    return 201, _certificate_out(certificate)
