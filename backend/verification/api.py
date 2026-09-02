"""Verification API — 휴대폰 본인확인, 만 19세 게이트, CI 동일인 조회.

`Verification`은 `Authentication`(accounts 앱)과 다른 개념이다: 여기서는 실명·생년월일·
CI를 확보해 "이 사람이 실재하는 성인 본인인가"를 답한다.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from .adapters import VerificationAdapterError, VerificationMissingCIError, get_adapter
from .age import is_adult
from .models import Verification
from .schemas import CiLookupIn, CiLookupOut, CiLookupMatchOut, VerificationStatusOut, VerifyIn

logger = logging.getLogger(__name__)

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
        if isinstance(exc, VerificationMissingCIError):
            # 정상 운영에서는 절대 나오면 안 되는 경로다(#84) — 실제 벤더는 카카오
            # 인증에서만 CI를 안 주고, 이 플랫폼은 카카오를 본인확인 수단에서 뺐다
            # (ADR-0024). 여기 걸렸다는 건 사용자 잘못이 아니라 벤더 콘솔의 인증
            # 수단 설정이 되돌려졌다는 뜻이므로 ERROR로 남겨 운영자가 알아채게 한다.
            logger.error(
                "본인확인 응답에 CI가 없다(user_id=%s) — 설정 회귀 가능성: 벤더 콘솔에서 "
                "CI를 주지 않는 인증 수단(예: 카카오)이 다시 활성화됐는지 확인해야 한다.",
                request.auth_user.id,
            )
            raise HttpError(
                422,
                "이 인증 수단으로는 본인확인을 완료할 수 없습니다. 다른 인증 수단으로 "
                "다시 시도해 주세요.",
            ) from exc
        raise HttpError(422, f"본인확인에 실패했습니다: {exc}") from exc

    verification, _created = Verification.objects.get_or_create(user=request.auth_user)
    verification.real_name = result.real_name
    verification.birth_date = result.birth_date

    # KST(Asia/Seoul) 기준 "오늘"이어야 한다. timezone.now().date()는 UTC 시각의 날짜를
    # 돌려주므로 00~09시 KST 사이에는 어제 날짜가 나와 생일 당일 성인이 하루 늦게
    # 성인 취급된다(ADR-0011).
    if is_adult(result.birth_date, on=timezone.localdate()):
        verification.status = Verification.Status.VERIFIED
        verification.reason = ""
        verification.set_ci(result.ci)
        verification.di = result.di
        verification.verified_at = timezone.now()
    else:
        verification.status = Verification.Status.UNDERAGE
        verification.reason = "만 19세 미만은 본인확인을 완료할 수 없습니다."
        verification.verified_at = None
        # 미성년자로 판정되면(재확인으로 인한 다운그레이드 포함) 플랫폼 신원을 남길
        # 이유가 없다 — 이미 저장돼 있던 CI/DI가 있다면 함께 지운다.
        verification.ci_encrypted = ""
        verification.ci_hash = ""
        verification.di_encrypted = ""

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
