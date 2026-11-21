"""운영자 표면 — 공모전 하나의 상장 목록과 취소(스펙 #1071 「화면 · 운영자 앱」, #1131).

개최자 표면(`api.py`)과 달리 마감·소유를 따지지 않는다 — 운영자는 어느 공모전이든 발급본을
보고 취소할 수 있다. 취소는 받는 사람에게 알리지 않는다(스펙 G4): 받는 사람의 제출 화면에
「취소됨」으로만 보인다. 다시 발급은 개최자 몫이라 여기에 없다.
"""

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from contests.models import Contest
from core.operator_auth import OperatorAuth

from . import services
from .models import Certificate
from .rendering import verify_url

operator_router = Router(tags=["operator", "certificates"], auth=OperatorAuth())

STATUS_VALID = "valid"
STATUS_CANCELLED = "cancelled"
STATUS_REISSUED = "reissued"


class OperatorCertificateOut(Schema):
    id: int
    number: str
    #: 발급 때 적은 받는 사람 이름 — 받는 사람이 탈퇴하면 비어 있다.
    recipient_name: str
    award_name: str
    #: `valid` 유효 / `cancelled` 취소 / `reissued` 취소하고 새 번호로 다시 발급됨.
    status: str
    issued_at: str
    cancelled_at: str | None
    #: 받는 사람이 확인 페이지를 닫았거나 탈퇴해 이름이 가려진 상태.
    page_hidden: bool
    verify_url: str


class OperatorCertificateListOut(Schema):
    contest_id: int
    contest_title: str
    certificates: list[OperatorCertificateOut]


def _status(certificate: Certificate) -> str:
    if certificate.is_valid:
        return STATUS_VALID
    return STATUS_REISSUED if certificate.replaced_by_id is not None else STATUS_CANCELLED


def _serialize(certificate: Certificate) -> OperatorCertificateOut:
    return OperatorCertificateOut(
        id=certificate.id,
        number=certificate.number,
        recipient_name=certificate.recipient_name,
        award_name=certificate.award_name,
        status=_status(certificate),
        issued_at=certificate.issued_at.isoformat(),
        cancelled_at=certificate.cancelled_at.isoformat() if certificate.cancelled_at else None,
        page_hidden=certificate.recipient_hidden_at is not None,
        verify_url=verify_url(certificate.token),
    )


def _contest_or_404(contest_id: int) -> Contest:
    contest = Contest.objects.filter(id=contest_id).first()
    if contest is None:
        raise HttpError(404, "공모전을 찾을 수 없습니다.")
    return contest


@operator_router.get("/contests/{contest_id}/certificates", response=OperatorCertificateListOut)
def list_contest_certificates(request: HttpRequest, contest_id: int):
    contest = _contest_or_404(contest_id)
    certificates = Certificate.objects.filter(contest=contest).order_by("-id")
    return OperatorCertificateListOut(
        contest_id=contest.id,
        contest_title=contest.title,
        certificates=[_serialize(c) for c in certificates],
    )


@operator_router.post(
    "/contests/{contest_id}/certificates/{certificate_id}/cancel", response=OperatorCertificateOut
)
def cancel_contest_certificate(request: HttpRequest, contest_id: int, certificate_id: int):
    contest = _contest_or_404(contest_id)
    try:
        certificate = services.cancel_certificate(
            contest=contest, certificate_id=certificate_id, actor=request.user
        )
    except services.CertificateRuleError as error:
        raise HttpError(error.status, error.message) from error
    return _serialize(certificate)
