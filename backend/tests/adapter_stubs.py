"""배포 부팅 가드 테스트 전용 stub 어댑터 (#83).

실물 벤더 클래스(#85 PortOne, #87 Toss, #57 Seller 등록, #88 OpenAI)는 아직
없다. 이 모듈은 "완전한 production/staging 환경이 부팅되는가"를 검증하는
테스트(`tests/test_deployment_config.py`)와 CI의 `deploy-check` 잡
(`.github/workflows/ci.yaml`)이 dotted path로 가리킬, 각 Protocol을 구조적으로
만족하는 최소 구현체를 담는다.

**Django 모델이나 앱 레지스트리가 필요한 것은 아무것도 임포트하지 않는다.**
부팅 가드 자체는 `django.core.checks`로 옮겨져 `django.setup()` 이후에만
평가되므로 이 제약이 더 이상 정확성 문제는 아니지만(#83 코드리뷰 지적), 이
모듈을 계속 가볍게 유지해 같은 함정을 다시 만들지 않는다.

이름이 `Fake`로 시작하면 안 된다 — `config.settings._is_fake_adapter_binding`가
그 값을 여전히 fake로 간주해 배포 가드에 걸린다. 메서드 본문은 전부
`NotImplementedError`를 던진다 — 이 stub은 "부팅 가드를 통과하는 모양"만
증명하면 되고, 실제로 호출될 일은 없다(호출되면 그 자체가 버그다 — 이
모듈은 오직 dotted path 검증용이다).
"""

from __future__ import annotations


class StubVerificationAdapter:
    """`verification.adapters.VerificationAdapter` 계약을 구조적으로 만족한다."""

    def resolve(self, verification_token: str):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")


class StubPGAdapter:
    """`payments.adapters.PGAdapter` 계약을 구조적으로 만족한다."""

    def request_payment(self, *, order_id: str, amount: int):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def confirm(self, *, order_id: str, simulate: str | None = None):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def query_status(self, *, order_id: str):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def refund(self, *, order_id: str, amount: int, simulate: str | None = None):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def query_refund_status(self, *, order_id: str):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")


class StubPayoutAdapter:
    """`payouts.adapters.PayoutAdapter` 계약을 구조적으로 만족한다."""

    def request_payout(self, *, idempotency_key: str, amount: int):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def confirm(self, *, idempotency_key: str, simulate: str | None = None):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")

    def query_status(self, *, idempotency_key: str):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")


class StubSellerAdapter:
    """`payouts.adapters.SellerAdapter` 계약을 구조적으로 만족한다."""

    def register(self, *, developer_id: int, simulate: str | None = None, policy=None):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")


class StubLLMScoringAdapter:
    """`scoring.adapters.LLMScoringAdapter` 계약을 구조적으로 만족한다."""

    model_version = "stub-boot-check-only"

    def score(self, scoring_input):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")


class StubRequirementChatAdapter:
    """`contests.requirement_chat.RequirementChatAdapter` 계약을 구조적으로 만족한다."""

    model_version = "stub-boot-check-only"

    def respond(self, chat_input):
        raise NotImplementedError("배포 가드 검증 전용 stub — 실제로 호출되면 안 된다.")
