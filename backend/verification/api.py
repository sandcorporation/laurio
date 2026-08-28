"""Verification API — 휴대폰 본인확인, 만 19세 게이트, CI 동일인 조회.

`Verification`은 `Authentication`(accounts 앱)과 다른 개념이다: 여기서는 실명·생년월일·
CI를 확보해 "이 사람이 실재하는 성인 본인인가"를 답한다.
"""

from __future__ import annotations

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from .adapters import VerificationAdapterError, get_adapter
from .age import is_adult
from .models import Verification
from .schemas import CiLookupIn, CiLookupOut, CiLookupMatchOut, VerificationStatusOut, VerifyIn

router = Router(tags=["verification"])


def _to_status_out(verification: Verification | None) -> VerificationStatusOut:
    if verification is None:
        return VerificationStatusOut(status="unverified")
    return VerificationStatusOut(
        status=verification.status,
        reason=verification.reason or None,
        verified_at=verification.verified_at,
    )


@router.post("/verification/verify", response=VerificationStatusOut, auth=jwt_auth)
def verify(request: HttpRequest, payload: VerifyIn):
    """휴대폰 본인확인을 완료 처리한다. 만 19세 미만이면 verified가 되지 않는다."""

    try:
        result = get_adapter().resolve(payload.verification_token)
    except VerificationAdapterError as exc:
        raise HttpError(422, f"본인확인에 실패했습니다: {exc}") from exc

    verification, _created = Verification.objects.get_or_create(user=request.auth_user)
    verification.real_name = result.real_name
    verification.birth_date = result.birth_date

    if is_adult(result.birth_date, on=timezone.now().date()):
        verification.status = Verification.Status.VERIFIED
        verification.reason = ""
        verification.set_ci(result.ci)
        verification.di = result.di
        verification.verified_at = timezone.now()
    else:
        verification.status = Verification.Status.UNDERAGE
        verification.reason = "만 19세 미만은 본인확인을 완료할 수 없습니다."
        verification.verified_at = None

    verification.save()
    return _to_status_out(verification)


@router.get("/verification/me", response=VerificationStatusOut, auth=jwt_auth)
def my_verification(request: HttpRequest):
    verification = Verification.objects.filter(user=request.auth_user).first()
    return _to_status_out(verification)


@router.post("/verification/lookup-by-ci", response=CiLookupOut, auth=jwt_auth)
def lookup_by_ci(request: HttpRequest, payload: CiLookupIn):
    """운영자 전용. CI로 동일인(중복 계정)을 판별한다 — 자기거래 탐지의 재료.

    판정(자전거래 차단) 자체는 이 티켓 범위 밖이다(#10). 여기선 조회만 제공한다.
    """

    if not request.auth_user.is_staff:
        raise HttpError(403, "운영자만 조회할 수 있습니다.")

    matches = [
        CiLookupMatchOut(user_id=v.user_id, verified_at=v.verified_at)
        for v in Verification.find_by_ci(payload.ci)
    ]
    return CiLookupOut(matches=matches)
