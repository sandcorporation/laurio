"""벤더를 실제로 치는 선택적(live) 테스트 인프라 (#83, ADR-0007).

기본 스위트는 결정적이고 오프라인이어야 한다 — 벤더 장애나 자격증명 부재가
신선한 체크아웃을 빨갛게 만들면 안 된다. 그래서 벤더를 실제로 치는 테스트는:

1. `@live_vendor`로 표시한다 — `pyproject.toml`의 `addopts`가 기본 실행에서 이
   마커(`live_vendor`)를 제외한다(`-m "not live_vendor"`). `uv run pytest
   -m live_vendor`로만 선택 실행된다.
2. 실행되더라도 필요한 자격증명 환경변수가 비어 있으면 **실패가 아니라 skip**
   된다 — `require_live_credential`이 이 판정을 한다. CI·신선한 체크아웃은 이
   값을 갖지 않으므로 `-m live_vendor`로 직접 돌려도 빨개지지 않는다.

다음 실물 어댑터 티켓들(#85 PortOne 본인확인, #87 Toss 결제, #88 OpenAI 채점)이
이 모양을 그대로 베낀다 — `tests/test_live_adapters.py`가 그 예시다.
"""

from __future__ import annotations

import os

import pytest

live_vendor = pytest.mark.live_vendor


def require_live_credential(env_var_name: str) -> str:
    """`env_var_name`이 비어 있으면 테스트를 skip하고, 있으면 그 값을 돌려준다.

    "실패가 아니라 skip"이 핵심이다 — 자격증명이 없는 것은 이 코드의 결함이
    아니라 이 환경에서 아직 검증할 수 없다는 사실일 뿐이다.
    """

    value = os.environ.get(env_var_name) or ""
    if not value:
        pytest.skip(
            f"{env_var_name} 이 설정되지 않았다 — live 테스트는 자격증명이 있을 때만 "
            "돈다(#83). CI·신선한 체크아웃은 이 값을 갖지 않으므로 정상적으로 "
            "skip된다."
        )
    return value
