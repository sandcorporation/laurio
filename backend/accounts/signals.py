"""계정이 닫히거나 휴면이 될 때 기능 앱이 따라 정리할 자리 (ADR-0052, #512).

공유층(`accounts`)이 기능 앱(`classroom` 등)을 직접 부르면 앱 경계(ADR-0037,
`tests/test_app_boundaries.py`)를 넘는다. 그래서 계정 쪽은 「이런 일이 있었다」만
알리고, 그 계정에 묶인 것을 정리하는 일은 받는 쪽이 한다 — 지금은 강의실의
「연결된 앱」 회수가 받는다(`classroom.apps`).

둘 다 보내는 쪽의 트랜잭션 안에서 보낸다 — 받는 쪽이 실패하면 탈퇴·파기도 함께
되돌아간다(연결이 남은 채 계정만 닫히는 상태를 만들지 않는다).
"""

from django.dispatch import Signal

#: 탈퇴가 실행됐다(`accounts.withdrawal.execute_withdrawal`). 인자: `user`.
user_withdrawn = Signal()

#: 휴면으로 신원이 파기됐다(`accounts.dormancy`). 인자: `user`.
user_became_dormant = Signal()
