"""forkserver 가 `_PRELOAD` 의 마지막으로 읽는 검사(#701, `tests/boot_process.py`).

forkserver 는 미리 읽을 모듈이 `ImportError` 를 내면 말없이 넘어가고, 설정을 읽는
모듈을 실수로 넣으면 기본 설정으로 평가해 둔 채 자식에게 물려준다 — 그러면
부팅 가드를 시험하는 자식이 가드를 다시 태우지 못한다. 둘 다 여기서 막는다:
앞의 모듈이 전부 읽혔고, 설정은 아직 아무도 건드리지 않았다.
"""

import sys

from django.conf import settings

from tests.boot_process import _PRELOAD

_missing = [name for name in _PRELOAD[: _PRELOAD.index(__name__)] if name not in sys.modules]
if _missing:
    raise RuntimeError(f"forkserver 가 미리 읽지 못한 모듈: {_missing}")
if settings.configured or "config.settings" in sys.modules:
    raise RuntimeError("forkserver 에서 미리 읽은 모듈이 설정을 건드렸다 — `_PRELOAD` 에서 빼야 한다")
