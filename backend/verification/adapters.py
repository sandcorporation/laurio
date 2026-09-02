"""본인확인 어댑터 인터페이스 (ADR-0007, #83) + 포트원 V2 실물 어댑터 (#85).

인터페이스(`VerificationAdapter`)와 dev/test용 `FakeVerificationAdapter`,
실물인 `PortOneV2VerificationAdapter`를 함께 둔다. 실제 구현체는 이
`VerificationAdapter` 계약만 만족시키면 된다.

어댑터 선택은 `core.adapters.resolve_adapter`를 쓴다 — scoring이 이미 쓰는 것과
같은 선택 방식이다(#83). `VERIFICATION_ADAPTER_MODE`가 `"fake"`면 Fake를, 아니면
그 값을 dotted path로 보고 실제 클래스를 import한다(dev에서 실물을 켜려면
`verification.adapters.PortOneV2VerificationAdapter`로 지목하면 된다).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

import requests
from django.conf import settings

from core.adapters import resolve_adapter

logger = logging.getLogger(__name__)


class VerificationAdapterError(Exception):
    """제공자가 본인확인 토큰을 거부했거나 파싱할 수 없을 때."""


class VerificationMissingCIError(VerificationAdapterError):
    """본인확인 응답에 CI가 없을 때(#84).

    `VerificationAdapterError`의 하위 타입이므로 `verification.api.verify`의
    기존 예외 처리에 새 분기 없이 그대로 걸린다. CI 없는 응답은 정상 운영에서
    나오면 안 된다 — 실제 벤더(KG이니시스 통합인증)는 카카오 인증에서만 CI를
    주지 않고, 이 플랫폼은 카카오를 본인확인 수단에서 뺐다(ADR-0024). 그래서
    이 예외가 실제로 터졌다면 사용자 잘못이 아니라 벤더 콘솔의 인증 수단 설정이
    되돌려졌다는 뜻이다 — 호출자가 ERROR로 로그를 남겨야 한다.
    """


@dataclass(frozen=True)
class VerificationResult:
    """본인확인 결과 계약.

    `ci`가 빈 문자열이면 생성 자체가 실패한다(#84) — `Verification.set_ci("")`가
    `HMAC(key, "")`라는 정상적인 64자 hex를 만들어, CI 없는 사용자 전원이 같은
    해시를 갖고 서로 남남인 Sponsor와 Developer가 동일인으로 오차단되는 결함의
    근본 원인을 계약 타입 단계에서 막는다. 지금 있는 어댑터도, 나중에 누가
    추가하는 어댑터도 이 가드를 우회할 수 없다.
    """

    real_name: str
    birth_date: date
    ci: str
    di: str

    def __post_init__(self) -> None:
        if not self.ci:
            raise VerificationMissingCIError(
                "본인확인 응답에 CI가 없다 — CI를 주지 않는 인증 수단은 본인확인으로 "
                "인정하지 않는다(ADR-0024)."
            )


@runtime_checkable
class VerificationAdapter(Protocol):
    def resolve(self, verification_token: str) -> VerificationResult: ...


class FakeVerificationAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작한다.

    토큰 형식: ``"<실명>|<YYYY-MM-DD>|<ci>|<di>"``.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        parts = verification_token.split("|")
        if len(parts) != 4:
            raise VerificationAdapterError(
                "fake verification token must be '<name>|<YYYY-MM-DD>|<ci>|<di>'"
            )
        real_name, birth_iso, ci, di = parts
        if not real_name or not ci or not di:
            raise VerificationAdapterError("fake verification token missing fields")
        try:
            birth_date = date.fromisoformat(birth_iso)
        except ValueError as exc:
            raise VerificationAdapterError("fake verification token has an invalid date") from exc
        return VerificationResult(real_name=real_name, birth_date=birth_date, ci=ci, di=di)


class PortOneV2VerificationAdapter:
    """포트원(PortOne) V2 통합인증 실물 어댑터 (#85, ADR-0007).

    채널은 KG이니시스 통합인증이다. 브라우저 SDK가 인증창을 띄워
    identityVerificationId를 돌려주면(이 어댑터가 받는 `verification_token`이
    바로 그 값이다), 서버는 그 id로 포트원에 서버-투-서버 조회를 한다
    (``GET /identity-verifications/{id}``) — 서버가 받는 콜백 URL이 없어
    도메인·TLS 없이 dev에서 끝까지 걸을 수 있다(MinIO가 dev에서 이미 실물인
    것과 같은 모양).

    자격증명(`PORT_ONE_V2_STORE_ID`, `PORT_ONE_V2_SECRET_KEY`)은 환경변수에서만
    읽는다 — 저장소에 들어가지 않는다. 둘 중 하나라도 없으면 인스턴스를 만들 수
    없다: dev에서는 그 자리에서 바로 드러나고, 배포 환경에서는
    `core.adapters.check_adapter_mode`(부팅 가드)가 이 생성 실패를 잡아 부팅
    자체를 거부한다.
    """

    _API_BASE = "https://api.portone.io"
    _TIMEOUT_SECONDS = 10

    def __init__(self) -> None:
        store_id = os.environ.get("PORT_ONE_V2_STORE_ID") or ""
        secret_key = os.environ.get("PORT_ONE_V2_SECRET_KEY") or ""
        if not store_id or not secret_key:
            raise VerificationAdapterError(
                "PORT_ONE_V2_STORE_ID/PORT_ONE_V2_SECRET_KEY 가 설정되지 않았다 — "
                "실물 본인확인 어댑터는 자격증명 없이 동작할 수 없다."
            )
        self._store_id = store_id
        self._secret_key = secret_key

    def resolve(self, verification_token: str) -> VerificationResult:
        """`verification_token`을 포트원 identityVerificationId로 보고 서버-투-서버 조회한다.

        벤더가 인증 실패·만료·존재하지 않는 식별자를 답하면(4xx/5xx, 또는
        status가 "VERIFIED"가 아님) `VerificationAdapterError`로 옮겨진다 — 이
        메서드가 500을 내는 경로는 없다. CI가 없는 응답은 여기서 따로 검사하지
        않는다 — `VerificationResult` 생성 시점에 `VerificationMissingCIError`
        (#84)가 그대로 터진다.
        """

        identity_verification_id = verification_token
        try:
            response = requests.get(
                f"{self._API_BASE}/identity-verifications/{identity_verification_id}",
                params={"storeId": self._store_id},
                headers={"Authorization": f"PortOne {self._secret_key}"},
                timeout=self._TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise VerificationAdapterError(f"포트원 본인확인 조회 호출이 실패했다: {exc}") from exc

        if response.status_code == 404:
            raise VerificationAdapterError("포트원에 존재하지 않는 본인확인 식별자다.")
        if response.status_code >= 400:
            raise VerificationAdapterError(
                f"포트원 본인확인 조회가 {response.status_code}를 반환했다: {response.text}"
            )

        try:
            payload: Any = response.json()
        except ValueError as exc:
            logger.error("포트원 본인확인 응답이 JSON이 아니다: %s", response.text)
            raise VerificationAdapterError("포트원 본인확인 응답을 해석할 수 없다.") from exc

        if not isinstance(payload, dict):
            logger.error("포트원 본인확인 응답이 객체가 아니다: %r", payload)
            raise VerificationAdapterError("포트원 본인확인 응답 형식이 계약과 다르다.")

        status = payload.get("status")
        if status != "VERIFIED":
            raise VerificationAdapterError(f"포트원 본인확인이 완료되지 않았다(status={status!r}).")

        customer = payload.get("verifiedCustomer")
        if not isinstance(customer, dict):
            logger.error("포트원 본인확인 응답에 verifiedCustomer가 없다: %r", payload)
            raise VerificationAdapterError(
                "포트원 본인확인 응답 형식이 계약과 다르다(verifiedCustomer 누락)."
            )

        try:
            real_name = str(customer["name"])
            birth_date = date.fromisoformat(str(customer["birthDate"]))
        except (KeyError, ValueError) as exc:
            logger.error("포트원 본인확인 응답 필드가 계약과 다르다: %r", customer)
            raise VerificationAdapterError(
                f"포트원 본인확인 응답 형식이 계약과 다르다: {exc}"
            ) from exc

        ci = str(customer.get("ci") or "")
        di = str(customer.get("di") or "")

        # ci가 비어 있으면(카카오처럼 CI를 안 주는 인증 수단이 실수로 다시 켜진
        # 상황, ADR-0024) 여기서 VerificationResult(...)가 그 자리에서
        # VerificationMissingCIError를 던진다 — #84가 세운 불변식을 이 어댑터가
        # 다시 검사하지 않는다.
        return VerificationResult(real_name=real_name, birth_date=birth_date, ci=ci, di=di)


def get_adapter() -> VerificationAdapter:
    return resolve_adapter(
        mode=settings.VERIFICATION_ADAPTER_MODE,
        fake_factory=FakeVerificationAdapter,
        not_implemented_hint=(
            "실제 본인확인 연동은 아직 구현되지 않았다 — VerificationAdapter 계약만 "
            "만족시키는 dotted path를 VERIFICATION_ADAPTER_MODE에 설정하면 된다 "
            "(ADR-0007)."
        ),
    )
