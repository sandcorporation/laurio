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

        unknown_order_id = f"laurio-live-test-{uuid.uuid4()}"
        assert adapter.query_status(order_id=unknown_order_id) == "pending"
        assert adapter.query_refund_status(order_id=unknown_order_id) == "pending"
