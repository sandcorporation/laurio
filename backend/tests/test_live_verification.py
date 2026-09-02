"""포트원 V2 통합인증 실물 어댑터의 live 테스트 (#85, ADR-0007).

`tests/live.py`가 제공하는 배선(`@live_vendor` 마커 + `require_live_credential`
자격증명 skip)을 그대로 따른다 — `tests/test_live_adapters.py`가 남긴 모양이다.

포트원 V2 본인인증은 브라우저 SDK가 인증창을 띄워야 identityVerificationId가
생긴다. 이 저장소의 자동화만으로는 그 창을 열 수 없으므로(사람이 인증창을 실제로
통과해야 한다), 두 개의 identityVerificationId를 환경변수로 미리 준비해 두고
그 값을 조회하는 것까지만 이 테스트가 검증한다:

- `PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID`: dev에서 사람이
  `POST /verification/start`가 발급한 id로(직접 지어낸 문자열이 아니라) 인증창을
  한 번 걸어 완료한 identityVerificationId다 — `verification.api.
  _generate_identity_verification_id`가 실제로 만드는 형태 그대로여야 한다.
  그래야 이 id가 포트원의 길이 제한(#85 코드리뷰 지적 1 — 40자) 안에 들어가는지
  실제 벤더를 쳐서 확인하는 셈이 된다. 이 파일의
  `test_a_freshly_generated_id_is_accepted_by_the_real_vendor`가 그 생성 코드
  자체를 직접 부르므로, 사람이 그 규율을 안 지켜도 자동으로 걸린다.
- `PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID_SAME_PERSON`: 같은 사람이 **다시**
  인증창을 걸어 완료한 두 번째 identityVerificationId — "같은 사람이 두 번
  인증하면 같은 CI가 온다"를 검증하려면 두 번째 id가 필요하다.

둘 다 없으면(신선한 체크아웃·CI가 늘 그렇다) 두 테스트 모두 skip된다. 단언은
값이 아니라 모양이다 — 실제 CI 값은 매 환경마다 다르고 비교 대상도 아니다.
"""

from __future__ import annotations

from verification.adapters import PortOneV2VerificationAdapter, VerificationAdapterError
from verification.api import _generate_identity_verification_id

from .live import live_vendor, require_live_credential


def _require_portone_credentials() -> None:
    require_live_credential("PORT_ONE_V2_STORE_ID")
    require_live_credential("PORT_ONE_V2_SECRET_KEY")


@live_vendor
def test_a_freshly_generated_id_is_accepted_by_the_real_vendor():
    """서버가 실제로 발급하는 형태의 identityVerificationId를 실제 벤더에 그대로
    쳐서, 길이·형식이 거부되지 않는다는 것을 확인한다(#85 코드리뷰 지적 1).

    `laurio-iv-` + `secrets.token_urlsafe(24)`는 42자로 포트원 V2의 40자
    상한을 넘어 실제 벤더를 칠 때만(= 이 라이브 테스트가 아니면 아무 테스트도
    걸리지 않는 자리에서만) 깨졌었다 — dev의 Fake 경로에는 벤더의 길이 제한이
    없어 기본 스위트로는 잡을 수 없는 결함이었다.

    이 id는 실제로 어떤 인증 세션도 연 적이 없으므로 "존재하지 않는다"는
    거절(4xx)이 정상이다 — 여기서 보는 건 그 거절이 **길이·형식 문제로 인한
    거절이 아니라는 것**뿐이다. 포트원이 형식 자체를 거부했다면 그 사실이
    로그에 남으므로, 사람이 CI 로그를 보고 알아챌 수 있다.
    """
    _require_portone_credentials()

    identity_verification_id = _generate_identity_verification_id()
    assert len(identity_verification_id) <= 40

    adapter = PortOneV2VerificationAdapter()
    try:
        adapter.resolve(identity_verification_id)
    except VerificationAdapterError:
        # 존재하지 않는 식별자로 거절된 것 — 형식은 받아들여졌다는 뜻이다.
        pass


@live_vendor
def test_a_verified_portone_response_yields_a_nonempty_ci():
    _require_portone_credentials()
    identity_verification_id = require_live_credential(
        "PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID"
    )

    result = PortOneV2VerificationAdapter().resolve(identity_verification_id)

    assert result.ci
    assert result.real_name
    assert result.birth_date is not None


@live_vendor
def test_the_same_person_verifying_twice_yields_the_same_ci():
    _require_portone_credentials()
    first_id = require_live_credential("PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID")
    second_id = require_live_credential(
        "PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID_SAME_PERSON"
    )

    adapter = PortOneV2VerificationAdapter()
    first = adapter.resolve(first_id)
    second = adapter.resolve(second_id)

    assert first.ci == second.ci
