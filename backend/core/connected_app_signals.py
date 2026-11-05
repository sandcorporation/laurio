"""탈퇴·휴면이면 그 계정의 「연결된 앱」을 범위를 가리지 않고 곧바로 끊는다 (ADR-0052, #512, #870).

`accounts.signals` 를 받는 쪽이다. 처음에는 강의실에 있었고, 허락이 공유층으로 올라오며(#870) 함께 왔다.
"""

from __future__ import annotations

from .models import ConnectedApp
from .oauth import revoke_all_for_user


def revoke_on_withdrawal(sender, user, **kwargs) -> None:
    revoke_all_for_user(user, ConnectedApp.RevokeReason.WITHDRAWN)


def revoke_on_dormancy(sender, user, **kwargs) -> None:
    revoke_all_for_user(user, ConnectedApp.RevokeReason.DORMANT)
