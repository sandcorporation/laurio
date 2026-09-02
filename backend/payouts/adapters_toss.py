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

# 실이체 4xx 중 "한도·rate limit"류로 보이는 벤더 코드 키워드(코드리뷰 지적
# 2) — 정확한 코드 목록은 토스가 공개 문서에 못박아 두지 않아, 코드 문자열에
# 이 키워드 중 하나가 포함되면 일시적 거절로 본다(대소문자 무시). Seller
# 등록 쪽이 이미 "한도 초과"를 UNDER_REVIEW(실패 아님)로 다루는 것과 같은
# 판단을 실이체 쪽에도 일관되게 적용한다. staging에서 실제 코드값을 확인하면
# 이 키워드 집합을 정확한 코드 목록으로 좁혀야 한다(#57 알아둘 것).
_PAYOUT_RETRYABLE_CODE_KEYWORDS = ("LIMIT", "RATE", "TOO_MANY", "THROTTL")


def _looks_like_retryable_payout_code(code: str | None) -> bool:
    if not code:
        return False
    upper = code.upper()
    return any(keyword in upper for keyword in _PAYOUT_RETRYABLE_CODE_KEYWORDS)


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

    **`secure_key`는 hex 디코드한 32바이트를 그대로 HMAC 키로 쓴다**(코드리뷰
    지적 11) — JWE 암호화(`jwe_encrypt`)가 같은 "보안 키"를 hex→bytes로
    해석하는 것과 정확히 같은 규칙이다. 토스 공식 문서(지급대행 가이드
    "보안 키" 절)는 웹훅 서명 문서의 "보안 키" 링크가 그 절을 직접
    가리키게 해 두 용도가 같은 정의를 공유함을 명시하고, 실제로도
    64자 hex 문자열을 UTF-8 그대로 쓰면 32바이트가 아니라 64바이트 키가 되어
    JWE 쪽 키 길이 요구(A256GCM=32바이트)와 애초에 값 자체가 달라진다 — 같은
    설정값 하나를 두 갈래로 다르게 해석하는 경로를 남기지 않는다.
    """

    if not signature_header or not secure_key:
        return False

    try:
        key_bytes = bytes.fromhex(secure_key)
    except ValueError:
        return False

    expected = hmac.new(
        key_bytes,
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


def _validate_secure_key(secure_key: str, *, mode_setting_name: str) -> None:
    """`TOSS_API_SECURE_KEY`가 실제로 64자 hex인지 부팅 시점에 확인한다(코드리뷰
    지적 12). "비었는가"만 보면 잘못 붙여넣은 값(길이가 다르거나 hex가 아닌
    문자 포함)이 부팅 가드를 통과하고, 첫 지급·Seller 등록 시도에서야
    `bytes.fromhex`가 `ValueError`를 던져(어댑터 계약 밖 예외 — PayoutError도
    SellerError도 아니다) 원장 트랜잭션을 롤백시키며 500이 난다."""

    if len(secure_key) != 64:
        raise ImproperlyConfigured(
            f"{mode_setting_name}가 가리키는 어댑터가 읽는 TOSS_API_SECURE_KEY의 길이가 "
            f"64가 아니다({len(secure_key)}자) — A256GCM 대칭키(32바이트)를 hex로 표현한 "
            "값이어야 한다."
        )
    try:
        bytes.fromhex(secure_key)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{mode_setting_name}가 가리키는 어댑터가 읽는 TOSS_API_SECURE_KEY가 유효한 hex "
            "문자열이 아니다."
        ) from exc


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
        _validate_secure_key(secure_key, mode_setting_name="SELLER_ADAPTER_MODE")
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

        from .models import Seller

        ref_seller_id = f"laurio-developer-{developer_id}"
        existing = Seller.objects.filter(developer_id=developer_id).first()

        if existing is not None and existing.seller_id and existing.status != Seller.Status.REJECTED:
            # 이미 이전 시도가 접수돼 seller_id를 받은 상태다(코드리뷰 지적 7)
            # — 고정된 refSellerId로 다시 POST하면 벤더가 "이미 등록된 셀러"류의
            # 4xx로 거절하고, 그 4xx는 아래 _parse_seller_response의 일반
            # 거절 처리를 거쳐 "rejected"로 잘못 매핑돼 APPROVAL_REQUIRED,
            # UNDER_REVIEW 같은 멀쩡히 진행 중인 상태를 덮어쓴다. 대신 현재
            # 상태를 조회(GET)한다 — 재시도, 재확인의 실제 경로는 등록이 아니라
            # 조회다.
            return self._query_seller_status(existing.seller_id, developer_id=developer_id)

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

    def _query_seller_status(self, seller_id: str, *, developer_id: int) -> SellerRegistrationResult:
        """이미 등록된(seller_id를 받은) Seller의 현재 상태를 GET으로 다시
        확인한다(코드리뷰 지적 7) — register()가 벤더에 새 등록을 요청하는
        게 아니라 이 메서드로 재조회하도록 갈아탄 것이 이 티켓의 핵심 수정이다.
        """

        try:
            response = requests.get(
                f"{_BASE_URL}/v1/sellers/{seller_id}",
                headers=_basic_auth_headers(self._secret_key, api_version=self._api_version),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise SellerError(
                f"토스 Seller 조회 요청이 타임아웃됐다(developer_id={developer_id})."
            ) from exc
        except requests.RequestException as exc:
            raise SellerError(
                f"토스 Seller 조회 요청이 네트워크 오류로 실패했다"
                f"(developer_id={developer_id}): {exc}"
            ) from exc

        if response.status_code == 404:
            # 벤더가 이 seller_id를 모른다 — 우리 기록과 벤더 상태가 어긋난
            # 드문 경우다. 처음부터 다시 시도할 수 있게 pending으로 돌려준다.
            return SellerRegistrationResult(seller_id="", status="pending", weekly_limit_amount=None)

        return self._parse_seller_response(response, developer_id=developer_id)

    def _parse_seller_response(
        self, response: requests.Response, *, developer_id: int
    ) -> SellerRegistrationResult:
        if response.status_code >= 500:
            # 벤더 쪽 일시 오류 — 등록이 실제로 접수됐는지 알 수 없다(코드리뷰
            # 지적 3). "rejected"로 뭉개면 재시도 없이 영구히 거절된 것으로
            # 보이고, ensure_seller_registered가 그대로 반영하면 원장까지
            # 되돌아간다(지적 6). 어댑터 장애로 던져 호출자가 기존 상태를
            # 유지하게 한다.
            raise SellerError(
                f"토스가 Seller 등록/조회에서 서버 오류를 응답했다"
                f"(developer_id={developer_id}, status={response.status_code})."
            )
        if response.status_code == 429:
            raise SellerError(
                f"토스 Seller 등록/조회가 rate limit에 걸렸다(developer_id={developer_id})."
            )

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
        _validate_secure_key(secure_key, mode_setting_name="PAYOUT_ADAPTER_MODE")
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

        from .models import Payout as PayoutModel
        from .models import Seller

        payout, seller = self._resolve_seller(idempotency_key)
        if seller is None or seller.status not in Seller.READY_STATUSES:
            # Seller가 아직 지급 가능 상태가 아니다 — 실제 이체를 요청할 수
            # 없다. Laurio 내부 확정(원장 분개 + Seller 등록 착수)만 진행한다.
            return "paid"

        claimed = self._claim_transfer_attempt(payout)
        if claimed is None:
            # 이미 다른 호출이 이 실이체를 선점했다(코드리뷰 지적 1, 4차 —
            # 실행 재현 완료). payouts.api.confirm_payout의 최초 호출과
            # payouts.services._request_real_transfer_if_ready의 재확인
            # 호출이 같은 Payout에 대해 격쳐 불려도(Seller가 이미 READY인
            # Payout은 둘 다 이 confirm()에 도달한다), 벤더에는 정확히 한
            # 번만 POST가 나가야 한다 — 두 번째 호출은 여기서 벤더를
            # 부르지 않고 현재 상태를 다시 읽어 그대로 신뢰한다.
            payout.refresh_from_db(fields=["transfer_status"])
            if payout.transfer_status == PayoutModel.TransferStatus.COMPLETED:
                return "paid"
            if payout.transfer_status == PayoutModel.TransferStatus.FAILED:
                return "failed"
            raise PayoutTimeoutError(
                f"다른 호출이 이미 이 실이체를 선점했다(idempotency_key={idempotency_key}) — "
                "query_status로 확정해야 한다."
            )

        return self._request_real_payout(claimed, seller)

    def _claim_transfer_attempt(self, payout):
        """벤더를 부르기 전에 이 시도를 선점한다(코드리뷰 지적 1, 4차) —
        `core.transitions.claim_transition`과 같은 조건부 UPDATE(WHERE
        transfer_status='old') + rowcount 관용구다. 이중 지급 방어를
        `payouts.services._request_real_transfer_if_ready`가 확인하는
        `transfer_status`에만 맡기면, 그 값을 아직 아무도 쓰지 않은 최초
        확인(payouts.api.confirm_payout의 직접 호출)이 그 검사를 거치지
        않고 벤더를 부를 수 있다 — 벤더 호출 지점(여기) 자체를 선점하는
        것만이 모든 경로를 한 곳에서 닫는다.

        선점에 성공하면(NOT_REQUESTED 또는 FAILED에서 REQUESTED로) 새
        `transfer_attempt`가 반영된 신선한 Payout을, 실패하면(다른 호출이
        이미 REQUESTED/COMPLETED로 선점해 두었다) None을 돌려준다.
        """

        from django.db.models import F

        from core.transitions import claim_transition
        from .models import Payout as PayoutModel

        won = claim_transition(
            PayoutModel,
            payout.pk,
            from_state=PayoutModel.TransferStatus.NOT_REQUESTED,
            to_state=PayoutModel.TransferStatus.REQUESTED,
            state_field="transfer_status",
            extra_fields={"transfer_attempt": F("transfer_attempt") + 1},
        ) or claim_transition(
            PayoutModel,
            payout.pk,
            from_state=PayoutModel.TransferStatus.FAILED,
            to_state=PayoutModel.TransferStatus.REQUESTED,
            state_field="transfer_status",
            extra_fields={"transfer_attempt": F("transfer_attempt") + 1},
        )
        if not won:
            return None

        payout.refresh_from_db()
        return payout

    def _request_real_payout(self, payout, seller) -> str:
        # 벤더에 보내는 참조는 우리 idempotency_key 그대로가 아니라
        # `{idempotency_key}-{transfer_attempt}`다(코드리뷰 지적 4, 4차 —
        # 실행 재현 완료). 재시도마다 같은 refPayoutId/Idempotency-Key를
        # 재사용하면, 벤더는 "이미 처리한 요청"으로 보고 예전 FAILED
        # 응답을 그대로 재생한다 — 실운영에서 영구히 복구 불가능하다.
        # `_claim_transfer_attempt`가 이 호출 직전에 transfer_attempt를
        # 이미 올려 두었다. 우리 쪽 DB 조회·웹훅 매칭은 여전히 변하지
        # 않는 `idempotency_key` 하나로만 한다 — 이 접미사는 벤더에게만 보인다.
        vendor_ref = f"{payout.idempotency_key}-{payout.transfer_attempt}"
        body = {
            "refPayoutId": vendor_ref,
            "sellerId": seller.seller_id,
            "amount": payout.net_amount,
            "scheduleType": "EXPRESS",
        }
        encrypted_body = jwe_encrypt(body, secure_key_hex=self._secure_key)

        try:
            response = requests.post(
                f"{_BASE_URL}/v2/payouts",
                data=encrypted_body,
                headers=self._headers(idempotency_key=vendor_ref),
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
            if response.status_code == 429 or _looks_like_retryable_payout_code(code):
                # 한도·rate limit류의 일시적 거절이다(코드리뷰 지적 2) — Seller
                # 쪽이 같은 사실(주간 한도 초과)을 UNDER_REVIEW로 다루는 것과
                # 같은 원칙으로, 여기서도 종결 실패("failed")로 굳히지 않는다.
                # PayoutTimeoutError를 던져 호출자가 query_status로 재확인하고,
                # 그래도 안 풀리면 다음 재시도(웹훅/재시도 엔드포인트)가 다시
                # 시도하게 한다 — READY인 Seller의 두 번째 Payout이 이 한도에
                # 걸려도 Payout.FAILED로 영구 종결되지 않는다.
                raise PayoutTimeoutError(
                    f"토스 지급 요청이 한도·rate limit으로 일시 거절됐다"
                    f"(idempotency_key={payout.idempotency_key}, code={code}) — "
                    "query_status로 재확인해야 한다."
                )
            logger.info(
                "토스 지급 요청이 거절됐다(idempotency_key=%s, code=%s): %s",
                payout.idempotency_key,
                code,
                message,
            )
            return "failed"

        response_body = self._decode_response_body(response)
        vendor_payout_id = response_body.get("id") or ""
        if vendor_payout_id:
            self._persist_vendor_payout_id(payout, vendor_payout_id)
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

    def _persist_vendor_payout_id(self, payout, vendor_payout_id: str) -> None:
        """벤더가 POST 응답으로 준 자신의 식별자를 저장한다(코드리뷰 지적 8) —
        이후 query_status가 우리 refPayoutId가 아니라 이 값으로 조회해야
        한다. 여기서만 DB에 쓴다(다른 어댑터 메서드는 읽기만 한다) — 원본
        응답을 직접 파싱한 시점에만 이 값을 알 수 있고, 이 사실을 상위
        레이어(services.py)로 되돌려줄 별도 채널이 PayoutAdapter 계약(문자열
        반환)에 없기 때문이다."""

        from .models import Payout as _Payout

        _Payout.objects.filter(pk=payout.pk).update(vendor_payout_id=vendor_payout_id)
        payout.vendor_payout_id = vendor_payout_id

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

        if not payout.vendor_payout_id:
            # POST가 응답을 받기 전에 타임아웃/네트워크 오류로 끝나 벤더가
            # 발급한 자신의 id를 아직 모른다(코드리뷰 지적 8) — 그 id로 GET을
            # 시도하면 항상 존재하지 않는 리소스를 찾게 되어 "타임아웃 뒤
            # 조회로 확정"하는 경로 자체가 성립하지 않는다. 우리 refPayoutId로
            # 조회하는 별도 경로로 폴백한다.
            return self._query_status_by_ref(payout)

        try:
            response = requests.get(
                f"{_BASE_URL}/v2/payouts/{payout.vendor_payout_id}",
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
        return self._map_payout_query_status(body.get("status"), idempotency_key=idempotency_key)

    def _query_status_by_ref(self, payout) -> str:
        """벤더가 발급한 id를 아직 모를 때(코드리뷰 지적 8), 우리 refPayoutId로
        조회를 시도하는 폴백 경로다. 토스가 이 조회 방식을 정확히 어떤 응답
        모양(단일 객체/목록)으로 주는지는 staging에서 실제로 검증되지 않았다
        — 이 티켓은 "타임아웃 뒤에도 최소한 무한정 같은 refPayoutId로 재시도할
        수 있다"는 것만 보장한다(404/빈 결과는 예외가 아니라 "pending").
        """

        try:
            response = requests.get(
                f"{_BASE_URL}/v2/payouts",
                params={"refPayoutId": f"{payout.idempotency_key}-{payout.transfer_attempt}"},
                headers=_basic_auth_headers(self._secret_key, api_version=self._api_version),
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise PayoutTimeoutError(
                f"토스 지급 조회(ref) 요청이 타임아웃됐다(idempotency_key={payout.idempotency_key})."
            ) from exc
        except requests.RequestException as exc:
            raise PayoutTimeoutError(
                f"토스 지급 조회(ref) 요청이 네트워크 오류로 실패했다"
                f"(idempotency_key={payout.idempotency_key}): {exc}"
            ) from exc

        if response.status_code == 404:
            return "pending"
        if response.status_code >= 400:
            body = _safe_json(response)
            raise PayoutError(
                f"토스 지급 조회(ref)가 실패했다(idempotency_key={payout.idempotency_key}, "
                f"status={response.status_code}): {body}"
            )

        body = self._decode_response_body(response)
        record = body
        if isinstance(body, list):
            record = body[0] if body else None
        elif isinstance(body, dict) and isinstance(body.get("list"), list):
            items = body["list"]
            record = items[0] if items else None

        if not record:
            return "pending"

        vendor_id = record.get("id") or ""
        if vendor_id:
            from .models import Payout as _Payout

            _Payout.objects.filter(pk=payout.pk).update(vendor_payout_id=vendor_id)

        return self._map_payout_query_status(record.get("status"), idempotency_key=str(payout.idempotency_key))

    def _map_payout_query_status(self, vendor_status, *, idempotency_key: str) -> str:
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
