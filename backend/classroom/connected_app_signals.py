"""탈퇴·휴면이면 그 강사의 「연결된 앱」을 곧바로 끊는다 (ADR-0052, #512).

`accounts.signals` 를 받는 쪽이다 — 공유층이 강의실을 직접 부르지 않게 한다.
"""

from __future__ import annotations

from .models import ConnectedApp
from .oauth import revoke_all_for_user


def revoke_on_withdrawal(sender, user, **kwargs) -> None:
    revoke_all_for_user(user, ConnectedApp.RevokeReason.WITHDRAWN)


def revoke_on_dormancy(sender, user, **kwargs) -> None:
    revoke_all_for_user(user, ConnectedApp.RevokeReason.DORMANT)
