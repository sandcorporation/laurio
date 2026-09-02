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
    # 본인확인 응답이 함께 주는 휴대폰 번호(#51 코드리뷰 지적 1) — 실제 벤더는
    # verifiedCustomer.phoneNumber로 이 값을 준다. 빈 문자열이면(옛 벤더 응답,
    # 또는 phoneNumber를 안 주는 인증 수단) verification.api.verify가
    # PhoneContact를 만들지 않는다 — CI와 달리 이 값이 없다고 본인확인 자체가
    # 실패하지는 않는다(통지 채널이 하나 비는 것뿐이다).
    phone_number: str = ""

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

    토큰 형식: ``"<실명>|<YYYY-MM-DD>|<ci>|<di>"`` 또는 휴대폰 번호를 더한
    ``"<실명>|<YYYY-MM-DD>|<ci>|<di>|<phone>"``(#51) — 5번째 필드는 선택이라
    기존 4필드 토큰을 쓰던 테스트가 전부 그대로 동작한다.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        parts = verification_token.split("|")
        if len(parts) not in (4, 5):
            raise VerificationAdapterError(
                "fake verification token must be "
                "'<name>|<YYYY-MM-DD>|<ci>|<di>[|<phone>]'"
            )
        real_name, birth_iso, ci, di, *rest = parts
        phone_number = rest[0] if rest else ""
        if not real_name or not ci or not di:
            raise VerificationAdapterError("fake verification token missing fields")
        try:
            birth_date = date.fromisoformat(birth_iso)
        except ValueError as exc:
            raise VerificationAdapterError("fake verification token has an invalid date") from exc
        return VerificationResult(
            real_name=real_name, birth_date=birth_date, ci=ci, di=di, phone_number=phone_number
        )


# CI 누락을 진단할 때 로그에 실어도 되는 필드 — **사람이 아니라 인증 수단을
# 가리키는 값만** 담는다. 「어느 수단으로 인증했나」가 카카오 회귀(ADR-0024)와
# 테스트 채널을 가르는 유일한 단서인데, verifiedCustomer 의 나머지 필드는 실명·
# 생년월일·전화번호라 그대로 남길 수 없다.
#
# 허용목록으로 두는 이유 — 벤더가 나중에 필드를 추가했을 때 「모르는 필드는
# 안전할 것」으로 기울면 언젠가 PII 가 로그로 샌다. 모르는 필드는 이름만 남고
# 값은 남지 않는다.
_NON_PII_DIAGNOSTIC_KEYS = ("method", "pgProvider", "operator", "channelType")


def _non_pii_diagnostics(payload: dict, customer: dict) -> list[tuple[str, str]]:
    """CI 누락 진단에 쓸, 사람을 가리키지 않는 필드만 (name, value) 로 추린다."""

    found: list[tuple[str, str]] = []
    channel = payload.get("channel")
    sources: list[dict] = [payload, customer]
    if isinstance(channel, dict):
        sources.append(channel)

    for source in sources:
        for key in _NON_PII_DIAGNOSTIC_KEYS:
            value = source.get(key)
            # 스칼라만 남긴다 — 중첩 구조에 PII 가 들어 있을 수 있다.
            if isinstance(value, str) and value and (key, value) not in found:
                found.append((key, value))
    if isinstance(channel, dict):
        channel_type = channel.get("type")
        if isinstance(channel_type, str) and channel_type:
            found.append(("channel.type", channel_type))
    return found


class PortOneV2VerificationAdapter:
    """포트원(PortOne) V2 통합인증 실물 어댑터 (#85, ADR-0007).

    채널은 KG이니시스 통합인증이다. `verification.api.start_verification`이
    발급해 요청자에게 귀속시킨 identityVerificationId를 브라우저 SDK가 그대로
    실어 인증창을 띄우면(이 어댑터가 받는 `verification_token`이 바로 그
    값이다), 서버는 그 id로 포트원에 서버-투-서버 조회를 한다
    (``GET /identity-verifications/{id}``) — 서버가 받는 콜백 URL이 없어
    도메인·TLS 없이 dev에서 끝까지 걸을 수 있다(MinIO가 dev에서 이미 실물인
    것과 같은 모양). 이 id가 실제로 호출자 본인에게 발급된 것인지 확인하는
    책임은 이 어댑터가 아니라 `verification.api.verify`에 있다(#85 코드리뷰
    지적 1) — 어댑터는 순수하게 "이 id로 포트원이 뭐라고 답하는가"만 다룬다.

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
            # requests 예외의 str()에는 요청 URL 전체(쿼리 파라미터의 storeId
            # 포함)가 그대로 들어간다 — 로그에만 남기고 예외 메시지는 일반화한다
            # (#85 코드리뷰 지적 3, 바로 아래 4xx/5xx·JSON 파싱 분기와 같은 원칙).
            logger.error("포트원 본인확인 조회 호출이 실패했다: %s", exc)
            raise VerificationAdapterError("포트원 본인확인 조회 호출이 실패했다.") from exc

        if response.status_code == 404:
            raise VerificationAdapterError("포트원에 존재하지 않는 본인확인 식별자다.")
        if response.status_code >= 400:
            # 벤더 응답 원문(response.text)은 로그에만 남긴다 — 그대로 예외
            # 메시지에 실으면 verify()가 그걸 422 detail로 사용자에게 그대로
            # 돌려준다(#85 코드리뷰 지적 6). 아래 JSON 파싱·형식 불일치 분기와
            # 같은 일반화 원칙을 이 분기에도 적용한다.
            logger.error(
                "포트원 본인확인 조회가 %s를 반환했다: %s", response.status_code, response.text
            )
            raise VerificationAdapterError(
                f"포트원 본인확인 조회가 {response.status_code}를 반환했다."
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
            # ValueError(date.fromisoformat)의 str()에는 문제가 된 원본 문자열이
            # 그대로 들어간다 — birthDate가 계약과 다른 형식이면 그 값(생년월일,
            # PII)이 예외 메시지에 실려 verify()의 422 detail로 사용자에게 그대로
            # 나갈 수 있었다(#85 코드리뷰 지적 3). customer 전체는 로그에만
            # 남기고, 사용자에게 가는 메시지는 어떤 필드가 문제인지만 말한다.
            logger.error("포트원 본인확인 응답 필드가 계약과 다르다: %r", customer)
            raise VerificationAdapterError(
                "포트원 본인확인 응답 형식이 계약과 다르다(name/birthDate)."
            ) from exc

        ci = str(customer.get("ci") or "")
        di = str(customer.get("di") or "")
        # 포트원 통합인증 응답은 verifiedCustomer.phoneNumber로 실제 연락 가능한
        # 번호를 함께 준다(#51) — verification.api.verify가 이 값으로
        # accounts.models.PhoneContact를 채운다. 벤더가 이 필드를 비워 보내도
        # 본인확인 자체는 그대로 성공한다(ci와 달리 필수 계약이 아니다).
        phone_number = str(customer.get("phoneNumber") or "")

        if not ci:
            # **벤더가 무엇을 줬는지 남긴다.** 이게 없으면 운영자는 상위
            # (`verification.api.verify`)의 "CI가 없다" 한 줄만 보고 원인을 가릴
            # 수 없다 — 콘솔에서 CI를 안 주는 인증 수단(카카오, ADR-0024)이 다시
            # 켜진 것인지, 테스트 채널이라 CI가 아예 안 내려오는 것인지, 벤더가
            # 필드 이름을 바꾼 것인지가 전부 같은 한 줄로 보인다. staging 에서
            # 실제로 이 상황을 만나 원인을 좁히지 못했다(#52).
            #
            # **값이 아니라 필드 이름과 인증 수단만 남긴다** — verifiedCustomer 는
            # 실명·생년월일·전화번호가 든 PII 덩어리이고, 이 어댑터의 다른 실패
            # 분기들이 이미 원문을 예외 메시지로 흘리지 않도록 잡혀 있다(#85
            # 코드리뷰 지적 3·6). 로그도 같은 규율을 따른다.
            logger.error(
                "포트원이 CI 없이 VERIFIED를 돌려줬다 — verifiedCustomer 필드=%s, "
                "ci=%s, di=%s, %s. 콘솔에서 CI를 주지 않는 인증 수단이 켜졌는지, "
                "테스트 채널이라 CI가 내려오지 않는지 확인해야 한다.",
                sorted(customer.keys()),
                "빈 값" if "ci" in customer else "필드 자체가 없음",
                "있음" if di else ("빈 값" if "di" in customer else "필드 자체가 없음"),
                ", ".join(
                    f"{name}={value}"
                    for name, value in _non_pii_diagnostics(payload, customer)
                )
                or "인증 수단 정보 없음",
            )

        # ci가 비어 있으면(카카오처럼 CI를 안 주는 인증 수단이 실수로 다시 켜진
        # 상황, ADR-0024) 여기서 VerificationResult(...)가 그 자리에서
        # VerificationMissingCIError를 던진다 — #84가 세운 불변식을 이 어댑터가
        # 다시 검사하지 않는다.
        return VerificationResult(
            real_name=real_name, birth_date=birth_date, ci=ci, di=di, phone_number=phone_number
        )


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
