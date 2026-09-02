"""토스 지급대행 실물 어댑터 — Seller 등록 + 실지급 (#57, ADR-0007, ADR-0008, ADR-0020).

`payments.adapters_toss.TossPGAdapter`가 세운 규율을 그대로 물려받는다 — 벤더가
명시적으로 거절한 결과는 예외가 아니라 정해진 값으로 돌려주고, 네트워크
불확실성(타임아웃·5xx·일반 `requests.RequestException`)은 전부 "모른다"로
통일하며, 벤더가 우리가 모르는 상태 문자열이나 JSON이 아닌 본문을 주면 임의로
뭉개지 않고 예외를 던진다.

## 이 파일이 다루는 두 어댑터

`TossSellerAdapter`(`SellerAdapter` 계약)는 `Developer`를 지급대행사의 Seller로
등록한다. `TossPayoutAdapter`(`PayoutAdapter` 계약)는 실제 이체를 요청·확인한다.
둘 다 `payouts.adapters`가 정의한 Protocol만 만족시키면 되고, 호출부
(`payouts.services`)는 이 파일의 존재를 모른다(ADR-0007).

## JWE 암호화 (`TossPayments-api-security-mode: ENCRYPTION`)

셀러 등록·수정·지급 요청 세 API는 요청 본문을 JWE(RFC 7516) compact
serialization으로 암호화해야 한다 — 벤더 문서가 명시하는 파라미터는 `alg="dir"`
(보안 키를 그대로 대칭키로 쓴다, 별도 키 감싸기 없음), `enc="A256GCM"`(보안 키가
64자 hex=32바이트라 AES-256-GCM과 키 길이가 맞는다), 헤더에 요청 생성 시각
(`iat`)과 재전송 방지용 임의값(`nonce`)을 싣는다. `cryptography` 패키지의
`AESGCM`으로 표준 JWE를 직접 구현한다(RFC가 규정하는 AAD는 JWE Protected
Header를 base64url로 인코딩한 바이트 그대로다) — 별도 JWE 라이브러리를 새
의존성으로 들이지 않는다.

## Seller 등록에 필요한 신원 정보를 어디서 가져오는가

`businessType=INDIVIDUAL`의 `individual` 객체는 이름·이메일·전화번호를
요구한다(#57 추가 인수조건). 이 정보들은 서로 다른 세 곳에 흩어져 있다 —
실명은 `verification.models.Verification`(포트원 본인확인 결과), 이메일은
`accounts` User, 전화번호는 이 도메인 어디에도 없던 값이라 이 티켓이
`payouts.models.Seller.phone_number_encrypted`로 새로 들였다(별도 제출
엔드포인트, `payouts.services.submit_seller_phone`). `FakeSellerAdapter`처럼
`policies.services.get_current_policy()`를 스스로 읽는 기존 관용구를 그대로
따라, 이 어댑터도 `register()` 안에서 직접 조회한다 — `SellerAdapter.register`
계약(Protocol)을 바꾸지 않는다.

셋 중 하나라도 비어 있으면(가장 흔하게는 전화번호 — 제출을 아직 받지 못한
경우) 벤더를 부르지 않고 `SellerRegistrationResult(status="pending")`을
돌려준다 — `Seller.Status.PENDING`의 기존 문서("아직 등록을 시도하지
않았거나")가 정확히 이 경우를 가리킨다.

## 실이체(`TossPayoutAdapter`) 순서 문제 — 실물을 붙이며 알게 된 것 (ADR-0008 보완)

토스의 실제 이체 API는 이미 등록된 `sellerId`를 요구하는데, 이 저장소의 기존
순서(#50, ADR-0020)는 Payout이 먼저 확정되고 *그 뒤에* Seller 등록이
시작된다 — Payout이 처음 확정되는 순간에는 아직 `sellerId`가 없다. 그래서
`TossPayoutAdapter.confirm()`은 두 갈래로 나뉜다: 이 Developer의 Seller가 아직
지급 가능 상태(READY_STATUSES)가 아니면 벤더를 부르지 않고 "paid"(Laurio 내부
확정 — 원장 분개 + Seller 등록 착수)만 돌려주고, 이미 지급 가능 상태면 그제서야
실제로 벤더에 이체를 요청한다. `payouts.services._request_real_transfer_if_ready`가
Seller가 나중에 준비되는 시점(재시도·`seller.changed` 웹훅)에 `confirm()`을
한 번 더 불러 그제서야 실제 이체를 시도한다 — 이 설계는 발견 사실이라
ADR-0008에도 남겨 둔다.

## `payout.changed`/`seller.changed` 웹훅 서명

토스 문서: 이 두 웹훅에만 서명 헤더(`tosspayments-webhook-signature`)가 붙는다.
`{WEBHOOK_PAYLOAD}:{tosspayments-webhook-transmission-time}`을 보안 키로
HMAC-SHA256 해싱한 값이 서명 헤더의 `v1:` 뒤 두 값(base64) 중 하나와
일치해야 한다(키 롤오버 대비로 두 값이 온다). `payments.webhook_security`가
쓰는 우리 자체 Fake 전용 스킴과는 다른, 벤더가 실제로 쓰는 스킴이라 이 파일에
따로 둔다 — `payouts.api`의 실물 웹훅 엔드포인트가 이 함수로 검증한다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .adapters import PayoutError, PayoutTimeoutError, SellerError, SellerRegistrationResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.tosspayments.com"
_TIMEOUT_SECONDS = 10

# 이 코드가 우리 쪽 설정 문제(자격증명·요청 자체가 잘못됨)라고 판단하는 HTTP
# 상태다 — `payments.adapters_toss`와 같은 판단 기준이다.
_OUR_INTEGRATION_ERROR_STATUSES = {401, 403}

# 벤더가 실제로 확인해 준 Seller 상태 흐름(ADR-0020) — 여기 없는 문자열을
# 받으면 임의로 뭉개지 않고 예외를 던진다.
_SELLER_STATUS_MAP = {
    "APPROVAL_REQUIRED": "approval_required",
    "PARTIALLY_APPROVED": "partially_approved",
    "KYC_REQUIRED": "under_review",
    "UNDER_REVIEW": "under_review",
    "APPROVED": "approved",
    "REJECTED": "rejected",
    "DENIED": "rejected",
}

# 실이체 상태(벤더 문서: REQUESTED → IN_PROGRESS → COMPLETED/FAILED).
_PAID_PAYOUT_STATUSES = {"COMPLETED"}
_FAILED_PAYOUT_STATUSES = {"FAILED"}
_PENDING_PAYOUT_STATUSES = {"REQUESTED", "IN_PROGRESS"}


# --- JWE (RFC 7516) compact serialization, alg=dir / enc=A256GCM ------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def jwe_encrypt(payload: dict[str, Any], *, secure_key_hex: str) -> str:
    """`payload`를 토스가 요구하는 JWE compact serialization으로 암호화한다.

    `alg="dir"`이라 암호화된 키 파트는 항상 빈 문자열이다(직접 대칭키를
    쓴다는 뜻). AAD(추가 인증 데이터)는 RFC 7516이 규정하는 그대로 — JWE
    Protected Header를 base64url로 인코딩한 문자열을 ASCII 바이트로 취급한
    값이다.
    """

    secure_key = bytes.fromhex(secure_key_hex)
    header = {
        "alg": "dir",
        "enc": "A256GCM",
        "iat": datetime.now(timezone.utc).astimezone().isoformat(),
        "nonce": uuid4().hex,
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))

    iv = os.urandom(12)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    aad = header_b64.encode("ascii")
    ciphertext_and_tag = AESGCM(secure_key).encrypt(iv, plaintext, aad)
    # cryptography의 AESGCM.encrypt는 (암호문 || 16바이트 태그)를 이어붙여
    # 돌려준다 — JWE compact serialization은 이 둘을 별도 세그먼트로 나눈다.
    ciphertext, tag = ciphertext_and_tag[:-16], ciphertext_and_tag[-16:]

    return ".".join(
        [
            header_b64,
            "",  # JWE Encrypted Key — alg=dir이라 항상 비어 있다.
            _b64url_encode(iv),
            _b64url_encode(ciphertext),
            _b64url_encode(tag),
        ]
    )


def jwe_decrypt(token: str, *, secure_key_hex: str) -> dict[str, Any]:
    """토스가 `ENCRYPTION` 모드로 돌려준 JWE 응답 본문을 복호화한다."""

    parts = token.split(".")
    if len(parts) != 5:
        raise SellerError(f"토스 JWE 응답의 세그먼트 수가 5가 아니다({len(parts)}개).")

    header_b64, _encrypted_key_b64, iv_b64, ciphertext_b64, tag_b64 = parts
    secure_key = bytes.fromhex(secure_key_hex)
    iv = _b64url_decode(iv_b64)
    ciphertext = _b64url_decode(ciphertext_b64)
    tag = _b64url_decode(tag_b64)
    aad = header_b64.encode("ascii")

    try:
        plaintext = AESGCM(secure_key).decrypt(iv, ciphertext + tag, aad)
    except Exception as exc:  # noqa: BLE001 - 복호화 실패는 전부 같은 SellerError로 통일한다
        raise SellerError(f"토스 JWE 응답을 복호화할 수 없다: {exc}") from exc

    try:
        return json.loads(plaintext)
    except ValueError as exc:
        raise SellerError("토스 JWE 응답을 복호화했지만 JSON이 아니다.") from exc


# --- payout.changed / seller.changed 웹훅 서명 검증 ---------------------------------


def verify_toss_webhook_signature(
    *, payload: bytes, transmission_time: str, signature_header: str | None, secure_key: str
) -> bool:
    """`tosspayments-webhook-signature` 헤더를 검증한다.

    헤더 값은 `v1:{base64_1},v1:{base64_2}` 형태(키 롤오버 대비 두 값) — 그중
    하나라도 우리가 계산한 HMAC-SHA256과 일치하면 통과시킨다. `secure_key`가
    비어 있거나 헤더가 없으면 무조건 거부한다.
    """

    if not signature_header or not secure_key:
        return False

    expected = hmac.new(
        secure_key.encode("utf-8"),
        f"{payload.decode('utf-8')}:{transmission_time}".encode("utf-8"),
        hashlib.sha256,
    ).digest()

    for raw_entry in signature_header.split(","):
        entry = raw_entry.strip()
        if not entry.startswith("v1:"):
            continue
        candidate_b64 = entry[len("v1:") :]
        try:
            candidate = base64.b64decode(candidate_b64)
        except (ValueError, TypeError):
            continue
        if hmac.compare_digest(expected, candidate):
            return True
    return False


# --- 공용 HTTP 헬퍼 -----------------------------------------------------------------


def _basic_auth_headers(secret_key: str, *, api_version: str) -> dict[str, str]:
    credentials = b64encode(f"{secret_key}:".encode()).decode()
    return {
        "Authorization": f"Basic {credentials}",
        "TossPayments-api-version": api_version,
    }


def _safe_json(response: requests.Response) -> dict | None:
    try:
        return response.json()
    except ValueError:
        return None


# --- Seller 등록 어댑터 --------------------------------------------------------------


class TossSellerAdapter:
    """`SELLER_ADAPTER_MODE=payouts.adapters_toss.TossSellerAdapter`로 켠다.

    인자 없이 생성된다 — 자격증명은 전부 환경(`TOSS_API_SECRET_KEY`,
    `TOSS_API_SECURE_KEY`)에서 읽는다. 둘 중 하나라도 비어 있으면 즉시
    `ImproperlyConfigured`를 던진다(`payments.adapters_toss.TossPGAdapter`와
    같은 원칙) — 배포 환경에서는 `core.adapters.check_adapter_mode`가 이 생성
    실패를 잡아 부팅 자체를 거부한다.
    """

    def __init__(self) -> None:
        secret_key = settings.TOSS_API_SECRET_KEY
        if not secret_key:
            raise ImproperlyConfigured(
                "TOSS_API_SECRET_KEY 가 비어 있다 — SELLER_ADAPTER_MODE 를 실물 토스 "
                "Seller 어댑터로 켜려면 환경에 시크릿 키를 반드시 주입해야 한다(#57)."
            )
        secure_key = settings.TOSS_API_SECURE_KEY
        if not secure_key:
            raise ImproperlyConfigured(
                "TOSS_API_SECURE_KEY 가 비어 있다 — Seller 등록은 JWE 암호화 (ENCRYPTION "
                "보안 모드) 가 필수이고, 이 키가 그 암호화·웹훅 서명 검증에 함께 쓰인다(#57)."
            )
        self._secret_key = secret_key
        self._secure_key = secure_key
        self._api_version = settings.TOSS_API_VERSION

    def _headers(self) -> dict[str, str]:
        headers = _basic_auth_headers(self._secret_key, api_version=self._api_version)
        headers["Content-Type"] = "application/jwt"
        headers["TossPayments-api-security-mode"] = "ENCRYPTION"
        return headers

    def _resolve_identity(self, developer_id: int) -> tuple[str, str, str]:
        """(실명, 이메일, 전화번호)를 조회한다. 하나라도 없으면 빈 문자열이다.

        `FakeSellerAdapter`가 `policy`를 스스로 읽는 것과 같은 관용구 —
        `SellerAdapter.register` 계약(Protocol)에 이 세 값을 위한 매개변수를
        더하지 않는다.
        """

        from accounts.models import DeveloperProfile
        from verification.models import Verification

        from .models import Seller

        try:
            developer = DeveloperProfile.objects.select_related("user").get(pk=developer_id)
        except DeveloperProfile.DoesNotExist as exc:
            raise SellerError(f"Developer#{developer_id}를 찾을 수 없다.") from exc

        email = developer.user.email or ""

        real_name = ""
        verification = Verification.objects.filter(
            user_id=developer.user_id, status=Verification.Status.VERIFIED
        ).first()
        if verification is not None:
            real_name = verification.real_name

        phone = ""
        seller_row = Seller.objects.filter(developer_id=developer_id).first()
        if seller_row is not None:
            phone = seller_row.phone_number

        return real_name, email, phone

    def register(
        self,
        *,
        developer_id: int,
        simulate: str | None = None,
        policy: Any = None,
    ) -> SellerRegistrationResult:
        # simulate/policy는 Fake 전용 시나리오 선택 값이다 — 실물 어댑터는 쓰지
        # 않는다(주간 한도는 벤더 응답이 알려준다).
        del simulate, policy

        real_name, email, phone = self._resolve_identity(developer_id)
        if not (real_name and email and phone):
            missing = [
                name
                for name, value in (("실명", real_name), ("이메일", email), ("전화번호", phone))
                if not value
            ]
            logger.info(
                "Seller 등록에 필요한 정보가 아직 없어 등록을 시도하지 않는다"
                "(developer_id=%s, 누락=%s).",
                developer_id,
                missing,
            )
            return SellerRegistrationResult(seller_id="", status="pending", weekly_limit_amount=None)

        ref_seller_id = f"laurio-developer-{developer_id}"
        body = {
            "refSellerId": ref_seller_id,
            "businessType": "INDIVIDUAL",
            "individual": {"name": real_name, "email": email, "phone": phone},
        }
        encrypted_body = jwe_encrypt(body, secure_key_hex=self._secure_key)

        try:
            response = requests.post(
                f"{_BASE_URL}/v1/sellers",
                data=encrypted_body,
                headers=self._headers(),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise SellerError(
                f"토스 Seller 등록 요청이 타임아웃됐다(developer_id={developer_id})."
            ) from exc
        except requests.RequestException as exc:
            raise SellerError(
                f"토스 Seller 등록 요청이 네트워크 오류로 실패했다"
                f"(developer_id={developer_id}): {exc}"
            ) from exc

        return self._parse_seller_response(response, developer_id=developer_id)

    def _parse_seller_response(
        self, response: requests.Response, *, developer_id: int
    ) -> SellerRegistrationResult:
        if response.status_code >= 400:
            body = _safe_json(response)
            code = body.get("code") if body else None
            message = body.get("message") if body else response.text
            if response.status_code in _OUR_INTEGRATION_ERROR_STATUSES:
                raise SellerError(
                    f"토스 Seller 등록이 우리 쪽 설정 문제로 거부됐다"
                    f"(developer_id={developer_id}, code={code}): {message}"
                )
            logger.info(
                "토스 Seller 등록이 거절됐다(developer_id=%s, code=%s): %s",
                developer_id,
                code,
                message,
            )
            return SellerRegistrationResult(seller_id="", status="rejected", weekly_limit_amount=None)

        raw_body = response.text
        if raw_body and raw_body.strip().count(".") == 4:
            # ENCRYPTION 모드 요청은 암호화된 응답을 받는다(compact JWE — 점 4개로
            # 나뉜 5세그먼트).
            body = jwe_decrypt(raw_body.strip(), secure_key_hex=self._secure_key)
        else:
            body = _safe_json(response)
            if body is None:
                raise SellerError(
                    f"토스 Seller 등록 응답이 JSON도 JWE도 아니다(developer_id={developer_id})."
                )

        vendor_status = body.get("status")
        status = _SELLER_STATUS_MAP.get(vendor_status)
        if status is None:
            logger.error(
                "토스 Seller 등록 응답에 알 수 없는 status가 왔다(developer_id=%s): %r",
                developer_id,
                vendor_status,
            )
            raise SellerError(
                f"토스 Seller 등록 응답의 status를 알 수 없다(developer_id={developer_id}): "
                f"{vendor_status!r}"
            )

        seller_id = body.get("sellerId") or body.get("refSellerId") or ""
        weekly_limit = None
        if status == "partially_approved":
            weekly_limit_body = body.get("weeklyLimit") or {}
            weekly_limit = weekly_limit_body.get("amount")

        return SellerRegistrationResult(
            seller_id=seller_id, status=status, weekly_limit_amount=weekly_limit
        )


# --- 실이체 어댑터 -------------------------------------------------------------------


class TossPayoutAdapter:
    """`PAYOUT_ADAPTER_MODE=payouts.adapters_toss.TossPayoutAdapter`로 켠다.

    `confirm()`의 두 갈래 동작은 모듈 독스트링의 "실이체 순서 문제" 절을 참고 —
    Seller가 아직 지급 가능 상태가 아니면 벤더를 부르지 않고 "paid"(Laurio 내부
    확정)만 돌려주고, 이미 준비돼 있으면 실제로 이체를 요청한다.
    """

    def __init__(self) -> None:
        secret_key = settings.TOSS_API_SECRET_KEY
        if not secret_key:
            raise ImproperlyConfigured(
                "TOSS_API_SECRET_KEY 가 비어 있다 — PAYOUT_ADAPTER_MODE 를 실물 토스 "
                "지급대행 어댑터로 켜려면 환경에 시크릿 키를 반드시 주입해야 한다(#57)."
            )
        secure_key = settings.TOSS_API_SECURE_KEY
        if not secure_key:
            raise ImproperlyConfigured(
                "TOSS_API_SECURE_KEY 가 비어 있다 — 지급 요청 API도 JWE 암호화가 "
                "필수다(#57)."
            )
        self._secret_key = secret_key
        self._secure_key = secure_key
        self._api_version = settings.TOSS_API_VERSION

    def _headers(self, *, idempotency_key: str) -> dict[str, str]:
        headers = _basic_auth_headers(self._secret_key, api_version=self._api_version)
        headers["Content-Type"] = "application/jwt"
        headers["TossPayments-api-security-mode"] = "ENCRYPTION"
        headers["Idempotency-Key"] = idempotency_key
        return headers

    def _resolve_seller(self, idempotency_key: str):
        """이 지급 요청의 수취인 Seller를 조회한다. 없으면 None."""

        from .models import Payout, Seller

        try:
            payout = Payout.objects.select_related(
                "handover__award__submission__developer",
                "distribution_share__submission__developer",
            ).get(idempotency_key=idempotency_key)
        except Payout.DoesNotExist as exc:
            raise PayoutError(
                f"idempotency_key={idempotency_key}에 해당하는 Payout을 찾을 수 없다."
            ) from exc

        if payout.handover_id is not None:
            developer = payout.handover.award.submission.developer
        else:
            developer = payout.distribution_share.submission.developer

        return payout, Seller.objects.filter(developer=developer).first()

    def request_payout(self, *, idempotency_key: str, amount: int) -> Any:
        from .adapters import PayoutRequestResult

        # 실제 벤더 호출은 confirm()에서만 한다 — request_payout() 시점에는
        # Seller가 존재하지 않는 것이 정상 경로다(모듈 독스트링 참고).
        del amount
        return PayoutRequestResult(idempotency_key=idempotency_key, accepted=True)

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        del simulate  # Fake 전용 — 실물 어댑터는 쓰지 않는다.

        from .models import Seller

        payout, seller = self._resolve_seller(idempotency_key)
        if seller is None or seller.status not in Seller.READY_STATUSES:
            # Seller가 아직 지급 가능 상태가 아니다 — 실제 이체를 요청할 수
            # 없다. Laurio 내부 확정(원장 분개 + Seller 등록 착수)만 진행한다.
            return "paid"

        return self._request_real_payout(payout, seller)

    def _request_real_payout(self, payout, seller) -> str:
        body = {
            "refPayoutId": str(payout.idempotency_key),
            "sellerId": seller.seller_id,
            "amount": payout.net_amount,
            "scheduleType": "EXPRESS",
        }
        encrypted_body = jwe_encrypt(body, secure_key_hex=self._secure_key)

        try:
            response = requests.post(
                f"{_BASE_URL}/v2/payouts",
                data=encrypted_body,
                headers=self._headers(idempotency_key=str(payout.idempotency_key)),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PayoutTimeoutError(
                f"토스 지급 요청이 타임아웃됐다(idempotency_key={payout.idempotency_key}) — "
                "실제 결과는 query_status로 확정해야 한다."
            ) from exc
        except requests.RequestException as exc:
            raise PayoutTimeoutError(
                f"토스 지급 요청이 네트워크 오류로 실패했다"
                f"(idempotency_key={payout.idempotency_key}): {exc} — "
                "실제 결과는 query_status로 확정해야 한다."
            ) from exc

        if response.status_code >= 500:
            raise PayoutTimeoutError(
                f"토스가 지급 요청에서 서버 오류를 응답했다"
                f"(idempotency_key={payout.idempotency_key}, status={response.status_code}) — "
                "실제 결과는 query_status로 확정해야 한다."
            )

        if response.status_code >= 400:
            body_json = _safe_json(response)
            code = body_json.get("code") if body_json else None
            message = body_json.get("message") if body_json else response.text
            if response.status_code in _OUR_INTEGRATION_ERROR_STATUSES:
                raise PayoutError(
                    f"토스 지급 요청이 우리 쪽 설정 문제로 거부됐다"
                    f"(idempotency_key={payout.idempotency_key}, code={code}): {message}"
                )
            logger.info(
                "토스 지급 요청이 거절됐다(idempotency_key=%s, code=%s): %s",
                payout.idempotency_key,
                code,
                message,
            )
            return "failed"

        response_body = self._decode_response_body(response)
        vendor_status = response_body.get("status")
        if vendor_status in _PAID_PAYOUT_STATUSES:
            return "paid"
        if vendor_status in _FAILED_PAYOUT_STATUSES:
            return "failed"
        if vendor_status in _PENDING_PAYOUT_STATUSES:
            raise PayoutTimeoutError(
                f"토스 지급 요청이 아직 진행 중이다(idempotency_key={payout.idempotency_key}, "
                f"status={vendor_status}) — query_status로 확정해야 한다."
            )
        logger.error(
            "토스 지급 요청 응답에 알 수 없는 status가 왔다(idempotency_key=%s): %r",
            payout.idempotency_key,
            vendor_status,
        )
        raise PayoutError(
            f"토스 지급 요청 응답의 status를 알 수 없다(idempotency_key={payout.idempotency_key}): "
            f"{vendor_status!r}"
        )

    def _decode_response_body(self, response: requests.Response) -> dict:
        raw_body = response.text
        if raw_body and raw_body.strip().count(".") == 4:
            try:
                return jwe_decrypt(raw_body.strip(), secure_key_hex=self._secure_key)
            except SellerError as exc:
                raise PayoutError(str(exc)) from exc
        body = _safe_json(response)
        if body is None:
            raise PayoutError("토스 지급 요청 응답이 JSON도 JWE도 아니다.")
        return body

    def query_status(self, *, idempotency_key: str) -> str:
        from .models import Seller

        payout, seller = self._resolve_seller(idempotency_key)
        if seller is None or seller.status not in Seller.READY_STATUSES:
            return "pending"

        try:
            response = requests.get(
                f"{_BASE_URL}/v2/payouts/{idempotency_key}",
                headers=_basic_auth_headers(self._secret_key, api_version=self._api_version),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PayoutTimeoutError(
                f"토스 지급 조회 요청이 타임아웃됐다(idempotency_key={idempotency_key})."
            ) from exc
        except requests.RequestException as exc:
            raise PayoutTimeoutError(
                f"토스 지급 조회 요청이 네트워크 오류로 실패했다"
                f"(idempotency_key={idempotency_key}): {exc}"
            ) from exc

        if response.status_code == 404:
            return "pending"
        if response.status_code >= 400:
            body = _safe_json(response)
            raise PayoutError(
                f"토스 지급 조회가 실패했다(idempotency_key={idempotency_key}, "
                f"status={response.status_code}): {body}"
            )

        body = self._decode_response_body(response)
        vendor_status = body.get("status")
        if vendor_status in _PAID_PAYOUT_STATUSES:
            return "paid"
        if vendor_status in _FAILED_PAYOUT_STATUSES:
            return "failed"
        if vendor_status in _PENDING_PAYOUT_STATUSES:
            return "pending"
        logger.error(
            "토스 지급 조회 응답에 알 수 없는 status가 왔다(idempotency_key=%s): %r",
            idempotency_key,
            vendor_status,
        )
        raise PayoutError(
            f"토스 지급 조회 응답의 status를 알 수 없다(idempotency_key={idempotency_key}): "
            f"{vendor_status!r}"
        )
