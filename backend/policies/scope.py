"""PlatformPolicy 스코프 홀더 (#145, #123, ADR-0023).

정책은 「호출 스코프당 한 번」 읽는다 — 값마다·건마다 다시 읽으면 채점·배분·지급 경로에서 쿼리가
건수만큼 늘어난다. 전에는 그 규율을 **호출자가** 지켰다: 요청 진입점이 `get_current_policy()` 를 한 번
부르고 `policy=` 인자로 아래까지 실어 나르며, 받는 쪽은 `policy=None` 이면 스스로 읽는 폴백을 두었다.
그 실어 나르기가 시그니처 다섯 개에 번졌고 폴백은 「스코프당 한 번」을 조용히 깨는 길이었다.

이제 스코프는 **여는 쪽이 하나**다: HTTP 미들웨어가 요청마다, 스캔 뼈대(core.scans.run_scan)가 실행마다
`policy_scope()` 를 연다. 그 안에서 `current_policy()` 는 첫 호출에 한 번 읽고 그 뒤로는 같은 행을
돌려준다(게으르다 — 정책을 안 쓰는 요청은 SELECT 도 없다). 스코프 밖(관리 명령·셸·테스트 본문)에서는
매번 새로 읽는다 — 낡은 값을 들고 있을 스코프가 없기 때문이다. `update_policy` 는 write-through 다:
같은 요청 안에서 바꾼 정책이 그 요청의 나머지에 즉시 보인다.

순수 계산(`payouts.services._compute_amounts` · `_withholding_exempt_threshold` ·
`distributions.services.distribution_due_q`)은 여전히 `policy` 를 명시 인자로 받는다 — 어떤 정책으로
계산했는지가 호출 자리에서 보여야 하는 함수들이다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .models import PlatformPolicy
from .services import get_current_policy


class _Holder:
    __slots__ = ("policy",)

    def __init__(self) -> None:
        self.policy: PlatformPolicy | None = None


_holder: ContextVar[_Holder | None] = ContextVar("laurio_policy_scope", default=None)


@contextmanager
def policy_scope() -> Iterator[None]:
    """이 블록 동안 `current_policy()` 가 한 번만 읽는다. 중첩하면 안쪽이 자기 스코프를 새로 연다."""

    token = _holder.set(_Holder())
    try:
        yield
    finally:
        _holder.reset(token)


def current_policy() -> PlatformPolicy:
    """현재 정책 — 열린 스코프가 있으면 그 스코프에서 한 번 읽은 행, 없으면 지금 새로 읽은 행."""

    holder = _holder.get()
    if holder is None:
        return get_current_policy()
    if holder.policy is None:
        holder.policy = get_current_policy()
    return holder.policy


def refresh_scope(policy: PlatformPolicy) -> None:
    """정책이 바뀌었다 — 열린 스코프가 있으면 그 스코프가 앞으로 이 행을 돌려준다(write-through)."""

    holder = _holder.get()
    if holder is not None:
        holder.policy = policy
