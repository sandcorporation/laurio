"""Verification API — 휴대폰 본인확인, 만 19세 게이트, CI 동일인 조회.

`Verification`은 `Authentication`(accounts 앱)과 다른 개념이다: 여기서는 실명·생년월일·
CI를 확보해 "이 사람이 실재하는 성인 본인인가"를 답한다.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import PhoneContact
from accounts.phone import InvalidPhoneNumberError
from core.adapters import is_fake_adapter_binding

from .adapters import VerificationAdapterError, VerificationMissingCIError, get_adapter
from .age import is_adult
from .models import Verification, VerificationRequest
from .schemas import (
    CiLookupIn,
    CiLookupOut,
    CiLookupMatchOut,
    VerificationStartOut,
    VerificationStatusOut,
    VerifyIn,
)

logger = logging.getLogger(__name__)

router = Router(tags=["verification"])

# identityVerificationId 하나가 유효한 최대 시간(#85 코드리뷰 지적 4). 이게 없으면
# 실패한(또는 도중에 포기한) 시도가 VerificationRequest에 무기한 쌓이고, 그 값이
# 무기한 재사용 가능한 상태로 남는다 — 사람이 인증창을 실제로 여닫는 데 걸리는
# 시간을 넉넉히 잡아도 30분이면 충분하다.
_PENDING_VERIFICATION_TTL = timedelta(minutes=30)


def _generate_identity_verification_id() -> str:
    """서버가 발급하는 identityVerificationId(#85 코드리뷰 지적 1·4).

    포트원 V2의 가맹점 지정 식별자 길이 상한은 40자다(#85 코드리뷰 지적 1) —
    ``"codemit-iv-" + secrets.token_urlsafe(24)``는 42자로 그 상한을 넘어 dev
    Fake 경로에서는 절대 안 걸리고 staging/prod에서 실제 벤더를 칠 때만
    깨졌다. `secrets.token_urlsafe(18)`은 24자라 접두어(10자)를 더해도 34자로
    여유 있게 들어간다.
    """

    return f"codemit-iv-{secrets.token_urlsafe(18)}"


def _to_status_out(verification: Verification | None) -> VerificationStatusOut:
    if verification is None:
        return VerificationStatusOut(status="unverified")
    return VerificationStatusOut(
        status=verification.status,
        reason=verification.reason or None,
        verified_at=verification.verified_at,
    )


@router.post("/verification/start", response=VerificationStartOut, auth=jwt_auth)
def start_verification(request: HttpRequest):
    """실물 본인확인에 쓸 identityVerificationId를 서버가 발급해 요청자에게 귀속시킨다.

    브라우저 SDK는 이 값을 그대로 실어 인증창을 연다 — 리다이렉트 URL과 브라우저
    히스토리에 노출되는 값이다. `verify()`는 실물 어댑터를 쓸 때 이 값이 실제로
    요청자 본인에게 발급된 것인지 확인한 뒤에만 완료 처리한다(#85 코드리뷰 지적
    1) — 그렇지 않으면 노출된 남의 identityVerificationId를 다른 계정이 그대로
    제출해 그 사람의 CI/DI로 VERIFIED가 되는 계정 탈취(미성년자의 성년 게이트
    통과, 실소유자의 자전거래 오차단)가 가능하다.
    """
    # 이 사용자의 이전 미완료 시도는 새 시도로 대체한다(#85 코드리뷰 지적 4) —
    # 재시도·창 닫고 다시 시도 같은 흔한 경로가 계속 새 행을 쌓지 않는다.
    VerificationRequest.objects.filter(user=request.auth_user).delete()

    identity_verification_id = _generate_identity_verification_id()
    VerificationRequest.objects.create(
        user=request.auth_user, identity_verification_id=identity_verification_id
    )
    return VerificationStartOut(identity_verification_id=identity_verification_id)


@router.post("/verification/verify", response=VerificationStatusOut, auth=jwt_auth)
def verify(request: HttpRequest, payload: VerifyIn):
    """휴대폰 본인확인을 완료 처리한다. 만 19세 미만이면 verified가 되지 않는다."""

    token = payload.verification_token

    # 실물 어댑터를 쓸 때만 발급 기록을 확인한다(#85 코드리뷰 지적 1) — Fake
    # 어댑터의 토큰은 사용자가 직접 지어내는 자기완결적 문자열이라(FakeVerificationAdapter)
    # 귀속시킬 대상 자체가 없고, tests/test_verification.py를 비롯한 기존 스위트
    # 전체가 /verification/start 없이 바로 verify를 호출하는 전제로 짜여 있다.
    #
    # `settings.VERIFICATION_ADAPTER_MODE == "fake"` 리터럴 비교가 아니라
    # `is_fake_adapter_binding`을 쓴다(#85 코드리뷰 지적 5) — 배포 부팅 가드
    # (config/settings.py)는 이미 "...FakeVerificationAdapter"처럼 dotted path가
    # 가리키는 클래스명이 Fake로 시작하기만 해도 fake로 본다. 이 검사가 리터럴
    # "fake"만 보면, 그런 dotted path로 바인딩된 배포 환경에서는 두 판정이
    # 어긋나 이 소유권 확인이 항상 걸려 본인확인 자체가 영구히 불가능해진다.
    pending_request: VerificationRequest | None = None
    if not is_fake_adapter_binding(settings.VERIFICATION_ADAPTER_MODE):
        # 만료된 요청은 존재해도 없는 것과 같다(#85 코드리뷰 지적 4) — TTL이
        # 지나면 같은 이유(403)로 거절되고, 아래에서 함께 지워 정리된다.
        pending_request = VerificationRequest.objects.filter(
            user=request.auth_user,
            identity_verification_id=token,
            created_at__gte=timezone.now() - _PENDING_VERIFICATION_TTL,
        ).first()
        if pending_request is None:
            raise HttpError(
                403,
                "본인이 발급받지 않았거나 만료된 본인확인 요청입니다. 처음부터 다시 "
                "시도해 주세요.",
            )

    try:
        result = get_adapter().resolve(token)
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

    # 한 계정의 신원은 다른 사람의 것으로 바뀌지 않는다(#99, ADR-0025) — 이미
    # 확정된 CI가 있는데 다른 CI로 재확인이 들어오면 신원 전체(실명·생년월일·
    # 상태)를 손대지 않고 거부한다. 정당하게 CI가 바뀌는 경우(주민등록번호
    # 변경)와 계정 탈취 복구는 이 스펙 범위 밖이다 — 고객센터 경로가 생기기
    # 전까지는 거부가 기본이다.
    if verification.would_change_identity(result.ci):
        # 이 분기가 실제로 걸리는 건 두 가지 경우뿐이다: 계정을 탈취한 사람이
        # 자기 신원으로 재확인을 시도했거나, 정당한 소유자가 CI가 바뀌는 사유로
        # 재확인을 시도한 것이다. 둘 다 드물어야 정상이므로 ERROR로 남겨
        # 운영자가 계정 탈취 시도를 알아챌 수 있게 한다.
        logger.error(
            "본인확인 시도의 CI가 기존에 확정된 신원과 다르다(user_id=%s) — 계정 탈취 "
            "시도이거나 정당한 CI 변경(주민등록번호 변경 등) 요청일 수 있다. 두 경우 "
            "모두 이 저장소는 아직 처리 경로가 없어 거부한다(#98 범위 밖).",
            request.auth_user.id,
        )
        raise HttpError(
            409,
            "이미 다른 신원으로 본인확인이 완료된 계정입니다. 본인 확인 정보가 바뀌었다면"
            "(주민등록번호 변경, 계정 탈취 복구 등) 운영자에게 문의해 주세요.",
        )

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

    # 본인확인 응답이 휴대폰 번호를 함께 줬으면 알림 채널(#51)이 실제로 쓸
    # PhoneContact를 채운다 — 이 프로젝트에서 연락 가능한 번호를 확보하는
    # 유일한 지점이다(ADR-0011이 이미 휴대폰 본인확인을 요구한다). 성인
    # (VERIFIED)일 때만 채운다 — 미성년자(UNDERAGE)는 CI/DI를 남길 이유가
    # 없는 것과 같은 이유로(#51 2차 코드리뷰 지적 4) 전화번호도 남기지
    # 않는다: 재확인으로 인한 다운그레이드를 포함해, 이미 저장돼 있던
    # PhoneContact가 있다면 함께 지운다 — 그 계정에는 삭제 경로가 따로
    # 없으므로 여기서 지우지 않으면 영구히 잔존한다.
    #
    # **VERIFIED인데 벤더가 phoneNumber를 안 준 경우는 삭제 대상이 아니다**
    # (#51 3차 코드리뷰 지적 2 — 2차 수정의 `else` 분기가 UNDERAGE와 이
    # 경우를 하나로 묶어, 재확인 때마다 벤더가 phoneNumber를 생략하면 이미
    # 저장돼 있던 정상 번호까지 조용히 지웠다. verify()가 PhoneContact를
    # 채우는 유일한 지점이므로, 그 계정은 영구히 SMS를 못 받게 된다). "없다고
    # 막지 않는다"는 바로 아래 주석의 의도는 "본인확인을 막지 않는다"였지
    # "기존 값을 지운다"가 아니었다 — 세 경우(성공+번호 있음/성공+번호
    # 없음/미성년)를 명시적으로 분기해 이 둘을 다시 섞지 않는다. 벤더가 이
    # 필드를 비워 보내는 경우도 있으므로(포트원 계약상 필수가 아니다) 있을
    # 때만 저장한다 — 없다고 본인확인 자체를 막지 않는다. 정규화가 거부하는
    # 값(#51 코드리뷰 지적 4, 사실상 벤더가 이상한 형식을 준 경우)도 같은
    # 이유로 본인확인 완료 자체를 막지 않고 로그만 남긴다.
    if verification.status == Verification.Status.VERIFIED:
        if result.phone_number:
            try:
                PhoneContact.objects.update_or_create(
                    user=request.auth_user, defaults={"phone_number": result.phone_number}
                )
            except InvalidPhoneNumberError:
                logger.error(
                    "본인확인 응답의 휴대폰 번호 형식이 올바르지 않다(user_id=%s) — "
                    "PhoneContact를 채우지 못했다. 본인확인 자체는 그대로 완료된다.",
                    request.auth_user.id,
                )
        # else: 벤더가 phoneNumber를 안 줬다 — 기존에 저장된 번호가 있다면
        # 그대로 둔다(지우지 않는다).
    else:
        # UNDERAGE — CI/DI를 지우는 것과 같은 이유로 PhoneContact도 지운다.
        PhoneContact.objects.filter(user=request.auth_user).delete()

    # 1회용이다 — 성공적으로 소비된 identityVerificationId는 재사용할 수 없다.
    # 실패(벤더 거절 등)한 시도는 여기 도달하지 않으므로 같은 id로 재시도할 수
    # 있게 남겨 둔다.
    if pending_request is not None:
        pending_request.delete()
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
