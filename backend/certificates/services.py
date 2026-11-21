"""상장 발급·취소·다시 발급(#1127, 스펙 #1071 「발급 규칙」).

- 받는 사람은 그 공모전의 제출자다. 한 사람은 유효한(취소되지 않은) 상장을 하나만 가진다.
- 유효한 상장 수는 제출자 수를 넘지 않는다 — 위 두 규칙이 이미 보장하지만 따로 센다.
- 발급 때 PDF 를 한 번 그려 오브젝트 저장소에 둔다. 발급본은 바뀌지 않는다.
- 번호 `YYYY-CCCC-NNN` 의 일련번호는 공모전 행을 잠근 채 센다(취소된 것까지 — 번호는 다시 쓰지 않는다).
- 알림은 커밋 뒤에 보낸다(발급·다시 발급만, 취소만 하면 보내지 않는다 — G4).
"""

from __future__ import annotations

import io
import secrets
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from contests.models import Contest, ContestSubmission
from core.clock import Clock
from notifications.models import NotificationType
from notifications.services import notify_safely
from storage.adapters import Bucket, get_storage_adapter

from . import rendering
from .models import Certificate

PDF_CONTENT_TYPE = "application/pdf"


class CertificateRuleError(Exception):
    """발급 규칙 위반 — API 가 `status` 와 문구 그대로 돌려준다."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class IssueRequest:
    submission_id: int
    text: rendering.CertificateText


def _lock_contest(contest: Contest) -> Contest:
    return Contest.objects.select_for_update().get(pk=contest.pk)


def _next_serial(contest: Contest) -> int:
    return Certificate.objects.filter(contest=contest).count() + 1


def _create(
    *,
    contest: Contest,
    submission: ContestSubmission,
    text: rendering.CertificateText,
    issuer,
    serial: int,
) -> Certificate:
    now = Clock.now()
    number = f"{timezone.localtime(now).year}-{contest.id:04d}-{serial:03d}"
    token = secrets.token_urlsafe(16)
    sheet = rendering.CertificateSheet(
        text=text,
        contest_title=contest.title,
        number=number,
        verify_url=rendering.verify_url(token),
    )
    pdf = rendering.render_certificate_pdf(sheet)
    object_key = f"certificates/{contest.id}/{number}.pdf"
    get_storage_adapter().write_object(
        object_key, pdf, bucket=Bucket.PRIVATE, content_type=PDF_CONTENT_TYPE
    )
    return Certificate.objects.create(
        contest=contest,
        submission=submission,
        recipient_id=submission.user_id,
        number=number,
        token=token,
        award_name=text.award_name,
        recipient_name=text.recipient_name,
        body=text.body,
        giver_name=text.giver_name,
        giver_title=text.giver_title,
        award_date=text.award_date,
        pdf_object_key=object_key,
        issued_at=now,
        issued_by=issuer,
    )


def _notify_on_commit(certificate: Certificate, notification_type: str) -> None:
    context = {
        "contest_id": certificate.contest_id,
        "contest_title": certificate.contest.title,
        "certificate_id": certificate.id,
    }
    recipient = certificate.recipient
    transaction.on_commit(
        lambda: notify_safely(
            recipient=recipient, notification_type=notification_type, context=context
        )
    )


def issue_certificates(*, contest: Contest, issuer, requests: list[IssueRequest]) -> list[Certificate]:
    submission_ids = [r.submission_id for r in requests]
    if len(set(submission_ids)) != len(submission_ids):
        raise CertificateRuleError(422, "같은 사람을 두 번 고를 수 없습니다.")

    with transaction.atomic():
        contest = _lock_contest(contest)
        submissions = {
            s.id: s
            for s in ContestSubmission.objects.filter(contest=contest, id__in=submission_ids)
        }
        if len(submissions) != len(submission_ids):
            raise CertificateRuleError(422, "이 공모전에 제출한 사람에게만 발급할 수 있습니다.")

        recipients = {s.user_id for s in submissions.values()}
        # 탈퇴한 사람(#1130)에게는 새로 발급하지 않는다 — 이름과 PDF 를 파기한 사람이다.
        if ContestSubmission.objects.filter(id__in=submission_ids, user__is_active=False).exists():
            raise CertificateRuleError(409, "탈퇴한 사람에게는 발급할 수 없습니다.")
        if Certificate.objects.filter(
            contest=contest, recipient_id__in=recipients, cancelled_at__isnull=True
        ).exists():
            raise CertificateRuleError(409, "이미 상장을 받은 사람이 있습니다.")

        valid = Certificate.objects.filter(contest=contest, cancelled_at__isnull=True).count()
        submitters = ContestSubmission.objects.filter(contest=contest).count()
        if valid + len(requests) > submitters:
            raise CertificateRuleError(409, "상장 수는 제출자 수를 넘을 수 없습니다.")

        serial = _next_serial(contest)
        issued: list[Certificate] = []
        for offset, request in enumerate(requests):
            certificate = _create(
                contest=contest,
                submission=submissions[request.submission_id],
                text=request.text,
                issuer=issuer,
                serial=serial + offset,
            )
            _notify_on_commit(certificate, NotificationType.CERTIFICATE_ISSUED)
            issued.append(certificate)
    return issued


def _locked_valid(contest: Contest, certificate_id: int) -> Certificate:
    certificate = (
        Certificate.objects.select_for_update()
        .filter(contest=contest, id=certificate_id)
        .first()
    )
    if certificate is None:
        raise CertificateRuleError(404, "상장을 찾을 수 없습니다.")
    if not certificate.is_valid:
        raise CertificateRuleError(409, "이미 취소된 상장입니다.")
    return certificate


def cancel_certificate(*, contest: Contest, certificate_id: int, actor) -> Certificate:
    with transaction.atomic():
        contest = _lock_contest(contest)
        certificate = _locked_valid(contest, certificate_id)
        certificate.cancelled_at = Clock.now()
        certificate.cancelled_by = actor
        certificate.save(update_fields=["cancelled_at", "cancelled_by"])
    return certificate


def reissue_certificate(
    *, contest: Contest, certificate_id: int, text: rendering.CertificateText, issuer
) -> Certificate:
    """취소하고 새 번호로 다시 발급한다 — 옛 행의 `replaced_by` 가 새 행을 가리킨다."""

    with transaction.atomic():
        contest = _lock_contest(contest)
        old = _locked_valid(contest, certificate_id)
        if not old.pdf_object_key:
            raise CertificateRuleError(409, WITHDRAWN_MESSAGE)
        old.cancelled_at = Clock.now()
        old.cancelled_by = issuer
        old.save(update_fields=["cancelled_at", "cancelled_by"])
        new = _create(
            contest=contest,
            submission=old.submission,
            text=text,
            issuer=issuer,
            serial=_next_serial(contest),
        )
        old.replaced_by = new
        old.save(update_fields=["replaced_by"])
        _notify_on_commit(new, NotificationType.CERTIFICATE_REISSUED)
    return new


#: 받는 사람이 탈퇴해 이름과 PDF 를 파기한 상장(#1130) — 파일이 없고 다시 발급할 수도 없다.
WITHDRAWN_MESSAGE = "받는 사람이 탈퇴해 상장 파일이 없습니다."


def read_pdf(certificate: Certificate) -> bytes:
    if not certificate.pdf_object_key:
        raise CertificateRuleError(404, WITHDRAWN_MESSAGE)
    pdf = get_storage_adapter().read_object(certificate.pdf_object_key, bucket=Bucket.PRIVATE)
    if pdf is None:
        raise CertificateRuleError(404, "상장 파일을 찾을 수 없습니다.")
    return pdf


def bundle_pdf(certificates: list[Certificate]) -> bytes:
    """여러 장을 한 파일로 잇는다 — 저장하지 않는다."""

    from pypdf import PdfWriter

    writer = PdfWriter()
    for certificate in certificates:
        writer.append(io.BytesIO(read_pdf(certificate)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def giver_defaults(contest: Contest) -> tuple[str, str]:
    """수여자 칸 기본값(G5) — 그 공모전의 마지막 발급본, 없으면 개최자 표시 이름."""

    last = Certificate.objects.filter(contest=contest).order_by("-id").first()
    if last is not None:
        return last.giver_name, last.giver_title
    return contest.sponsor.display_name[:30], ""
