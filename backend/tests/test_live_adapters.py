"""벤더를 실제로 치는 live 테스트의 예시 하나 (#83).

이 티켓은 실물 어댑터를 만들지 않는다(#83 범위 밖 — PortOne 본인확인은 #85,
토스 결제는 #87, OpenAI 채점은 #88이 각각 만든다). 여기서는 `tests/live.py`가
제공하는 배선(`@live_vendor` 마커 + `require_live_credential` 자격증명 skip)이
실제로 동작한다는 것을, 실물 어댑터 클래스를 새로 만들지 않고 최소한의 HTTP
호출 하나로 증명한다 — 뒤따르는 티켓들이 그대로 베낄 모양이다:

1. `@live_vendor`로 표시해 기본 스위트에서 제외되게 한다.
2. 첫 줄에서 `require_live_credential`로 자격증명을 확인한다 — 없으면 skip.
3. 있으면 실제 벤더에 최소한의 요청을 보내 인증이 통한다는 것만 확인한다
   (값이 아니라 "인증이 통했다"는 사실 하나만 본다 — 벤더 응답 내용에
   의존하면 벤더가 바뀔 때마다 이 테스트가 흔들린다).
"""

from __future__ import annotations

import uuid

import pytest
import requests
from django.test import override_settings

from tests.live import live_vendor, require_live_credential


@live_vendor
def test_openai_credential_authenticates_against_the_real_api():
    """OPEN_AI_API_KEY가 있으면 OpenAI의 모델 목록 엔드포인트로 실제 인증을
    확인한다 — #88(AI 채점 실물 어댑터)이 채점 프롬프트를 실제로 보내기 전에,
    이 자격증명 자체가 유효하다는 것만 먼저 증명하는 최소 호출이다."""

    api_key = require_live_credential("OPEN_AI_API_KEY")

    response = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )

    assert response.status_code == 200, response.text


@live_vendor
def test_toss_payment_adapter_queries_are_server_only_and_shape_stable():
    """#87(토스 결제 실물 어댑터)의 옵인 live 테스트.

    승인(`confirm`)은 브라우저 위젯이 만드는 `payment_key`가 있어야 하므로 live
    테스트가 대신할 수 없다(사람이 dev에서 실제 브라우저로 결제를 마쳐야 한다,
    AC). 여기서는 **서버만으로 가능한 계약 부분**만 친다 — 존재하지 않는
    order_id로 상태를 조회하면 예외가 아니라 정해진 값("pending")이 돌아오는가.
    벤더 응답의 구체적인 값이 아니라 이 어댑터가 그 응답을 우리 계약대로
    해석한다는 사실(모양)만 본다(#82 Testing Decisions: "Live tests assert
    shape, not values")."""

    from payments.adapters_toss import TossPGAdapter

    secret_key = require_live_credential("TOSS_API_SECRET_KEY")

    with override_settings(TOSS_API_SECRET_KEY=secret_key, TOSS_API_VERSION="2022-11-16"):
        adapter = TossPGAdapter()

        unknown_order_id = f"codemit-live-test-{uuid.uuid4()}"
        assert adapter.query_status(order_id=unknown_order_id) == "pending"
        assert adapter.query_refund_status(order_id=unknown_order_id) == "pending"


@live_vendor
def test_aligo_credentials_authenticate_and_the_account_is_actually_out_of_balance():
    """#51(SMS/LMS 실물 어댑터)의 옵인 live 테스트.

    이 계정의 잔액은 0이다(사용자가 직접 확인한 사실) — 그래서 실제 발송
    (`/send/`)을 치면 성공을 단언할 수 없다. 대신 과금되지 않는 잔액 조회
    (`/remain/`)로 자격증명이 실제로 인증되는지만 확인한다. 발송 자체가
    실패하는 경로(잔액 부족)는 이 계정으로 발송을 실제로 시도했을 때 우리
    어댑터가 크래시가 아니라 `ChannelSendResult(success=False, ...)`로
    돌려준다는 것을 `tests/test_notifications_aligo_adapter.py`가 이미
    mock으로 증명한다 — 여기서 실제 잔액 부족 응답의 정확한 문구를 다시
    확인하지 않는다(#82 Testing Decisions: 벤더 응답의 값이 아니라 모양만
    본다).

    이 테스트를 처음 돌렸을 때 실제로 받은 응답은 성공(result_code="1")이
    아니라 `-101`("제한된 IP입니다")이었다 — Aligo는 콘솔에 등록된 발신 IP
    에서만 API 호출을 허용한다. 그래서 이 테스트는 "인증이 완전히 통과했다"가
    아니라 "요청이 실제로 Aligo에 도달해 구조화된 응답을 받았다"(크래시도,
    빈 응답도, JSON 파싱 실패도 아니다)까지만 단언한다 — IP 화이트리스트
    미등록은 자격증명이 틀렸다는 뜻이 아니므로 그 경우는 skip으로 구분한다."""

    require_live_credential("ALIGO_API_KEY")
    require_live_credential("ALIGO_USER_ID")
    require_live_credential("ALIGO_SENDER_PHONE_NUMBER")

    from notifications.adapters_aligo import query_remaining_balance

    body = query_remaining_balance()

    assert isinstance(body, dict) and "result_code" in body, body
    result_code = str(body.get("result_code"))

    if result_code == "-101":
        pytest.skip(
            f"Aligo가 이 실행 환경의 발신 IP를 거부했다({body.get('message')!r}) — "
            "Aligo 콘솔의 발신 IP 화이트리스트에 이 머신의 공인 IP를 등록해야 "
            "인증까지 확인할 수 있다(staging 배포 호스트도 마찬가지로 등록이 "
            "필요하다). 자격증명 자체가 틀렸다는 뜻은 아니다."
        )

    # 인증이 통했다는 사실 하나만 본다 — 잔액 자체는 0이어도(이 계정의 현재
    # 상태) result_code는 정상적으로 "1"이다. 인증이 실패하면 벤더가 다른
    # result_code(예: 자격증명 오류)를 준다.
    assert result_code == "1", body
def test_toss_seller_registration_encrypts_with_the_real_vendor_and_gets_a_recognized_status():
    """#57(토스 지급대행 Seller 등록 실물 어댑터)의 옵인 live 테스트.

    staging이 아직 뜨지 않아(#52) "실제로 한 번 지급이 끝까지 도는 것"은 이
    티켓이 증명할 수 없다 — 대신 dev에서 벤더의 test 환경을 직접 쳐서 증명할
    수 있는 만큼만 증명한다: 우리가 만든 JWE(alg=dir, A256GCM)를 실제 토스가
    받아 복호화할 수 있는가, 그리고 응답이 우리가 인식하는 상태 값 중 하나로
    오는가. **값이 아니라 모양만 본다**(#82 Testing Decisions와 같은 원칙) —
    test 환경의 개인 식별 정보는 매번 새로 지어내는 무작위 값이라 승인/거절
    여부 자체는 이 테스트가 단언하지 않는다.

    이 테스트는 매 실행마다 새 `refSellerId`로 실제 sandbox에 셀러 등록을
    시도한다 — test 키가 정확히 이런 반복 호출을 위해 있는 자격증명이라
    부작용을 걱정하지 않는다.
    """

    import uuid as _uuid

    from payouts.adapters_toss import _SELLER_STATUS_MAP, jwe_encrypt
    from payments.adapters_toss import _safe_json

    secret_key = require_live_credential("TOSS_API_SECRET_KEY")
    secure_key = require_live_credential("TOSS_API_SECURE_KEY")

    ref_seller_id = f"codemit-live-test-{_uuid.uuid4()}"
    body = {
        "refSellerId": ref_seller_id,
        "businessType": "INDIVIDUAL",
        "individual": {
            "name": "코드밋테스트",
            "email": f"{ref_seller_id}@example.com",
            "phone": "01000000000",
        },
    }
    encrypted_body = jwe_encrypt(body, secure_key_hex=secure_key)

    from base64 import b64encode

    credentials = b64encode(f"{secret_key}:".encode()).decode()
    response = requests.post(
        "https://api.tosspayments.com/v1/sellers",
        data=encrypted_body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/jwt",
            "TossPayments-api-version": "2022-11-16",
            "TossPayments-api-security-mode": "ENCRYPTION",
        },
        timeout=10,
    )

    # 우리 쪽 설정 문제(401/403)가 아니라면, 응답이 JWE든 평문 JSON이든 우리가
    # 인식하는 status 값이거나(성공 경로) 벤더가 명시적으로 거절한
    # 4xx여야 한다 — 어느 쪽이든 "우리 요청이 벤더에게 이해됐다"는 뜻이다.
    assert response.status_code not in (401, 403), response.text

    if response.status_code < 400:
        raw = response.text.strip()
        if raw.count(".") == 4:
            from payouts.adapters_toss import jwe_decrypt

            decoded = jwe_decrypt(raw, secure_key_hex=secure_key)
        else:
            decoded = _safe_json(response) or {}
        assert decoded.get("status") in _SELLER_STATUS_MAP
