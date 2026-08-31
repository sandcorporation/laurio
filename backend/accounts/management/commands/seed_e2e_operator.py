"""운영자 앱 e2e 전용 Operator 시드 (#63).

`create_operator`(부트스트랩 명령, accounts/management/commands/create_operator.py)
는 이미 있는 이름이면 실패한다 — 사람이 한 번 쓰는 명령이라 그게 맞다. 하지만
`frontend/e2e/lib/seed.ts`가 매 스펙 실행마다 같은 계정으로 로그인해야 하므로,
여기서는 있으면 갱신하고 없으면 만드는 멱등한 버전을 따로 둔다
(`backend/contests/management/commands/seed_e2e_contests.py`와 같은 원칙).

`accounts.operators.create_operator`를 호출하지 않는 이유: 그 함수는 "이미
존재하면 거부"가 핵심 계약이라 멱등 시드에 맞지 않는다. 서로소 불변식·비밀번호
정책 검증은 이 명령의 관심사가 아니다 — 그건 `backend/tests/test_operators.py`가
이미 지킨다. 여기서는 오직 "로그인 가능한 Operator 계정이 결정적으로 존재한다"만
보장한다.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "e2e 스펙이 로그인할 Operator 계정을 멱등하게 만든다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--username", default="e2e-operator")
        parser.add_argument("--password", default="e2e-operator-pw-9134-xyz")
        parser.add_argument("--superuser", action="store_true")

    def handle(self, *args, **options) -> None:
        User = get_user_model()
        username: str = options["username"]
        password: str = options["password"]
        superuser: bool = bool(options["superuser"])

        operator, _created = User.objects.get_or_create(username=username)
        operator.is_staff = True
        operator.is_superuser = superuser
        operator.is_active = True
        operator.set_password(password)
        operator.save()

        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — frontend/e2e/lib/seed.ts의
        # seedE2eContests와 같은 관용구(uv run이 남기는 진행 로그가 앞에 섞여도
        # 마지막 줄만 파싱하면 된다).
        self.stdout.write(
            json.dumps(
                {"id": operator.id, "username": operator.username, "is_superuser": operator.is_superuser}
            )
        )
