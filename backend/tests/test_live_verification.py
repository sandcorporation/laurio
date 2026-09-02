"""포트원 V2 통합인증 실물 어댑터의 live 테스트 (#85, ADR-0007).

`tests/live.py`가 제공하는 배선(`@live_vendor` 마커 + `require_live_credential`
자격증명 skip)을 그대로 따른다 — `tests/test_live_adapters.py`가 남긴 모양이다.

포트원 V2 본인인증은 브라우저 SDK가 인증창을 띄워야 identityVerificationId가
생긴다. 이 저장소의 자동화만으로는 그 창을 열 수 없으므로(사람이 인증창을 실제로
통과해야 한다), 두 개의 identityVerificationId를 환경변수로 미리 준비해 두고
그 값을 조회하는 것까지만 이 테스트가 검증한다:

- `PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID`: dev에서 사람이 한 번 인증창을
  걸어 완료한 identityVerificationId 하나.
- `PORT_ONE_V2_LIVE_IDENTITY_VERIFICATION_ID_SAME_PERSON`: 같은 사람이 **다시**
  인증창을 걸어 완료한 두 번째 identityVerificationId — "같은 사람이 두 번
  인증하면 같은 CI가 온다"를 검증하려면 두 번째 id가 필요하다.

둘 다 없으면(신선한 체크아웃·CI가 늘 그렇다) 두 테스트 모두 skip된다. 단언은
값이 아니라 모양이다 — 실제 CI 값은 매 환경마다 다르고 비교 대상도 아니다.
"""

from __future__ import annotations

from verification.adapters import PortOneV2VerificationAdapter

from .live import live_vendor, require_live_credential


def _require_portone_credentials() -> None:
    require_live_credential("PORT_ONE_V2_STORE_ID")
    require_live_credential("PORT_ONE_V2_SECRET_KEY")


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
