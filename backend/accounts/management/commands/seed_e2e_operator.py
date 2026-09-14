"""운영자 앱 e2e 전용 Operator 시드 (#63).

`create_operator`(부트스트랩 명령, accounts/management/commands/create_operator.py)
는 이미 있는 이름이면 실패한다 — 사람이 한 번 쓰는 명령이라 그게 맞다. 하지만
`frontend/e2e/lib/seed.ts`가 매 스펙 실행마다 같은 계정으로 로그인해야 하므로,
여기서는 있으면 갱신하고 없으면 만드는 멱등한 버전을 따로 둔다
(`backend/contests/management/commands/seed_e2e_contests.py`와 같은 원칙).

**서로소 불변식(ADR-0018)은 여기서도 지켜야 한다**(코드리뷰 지적) — 처음에는
"멱등 시드는 create_operator의 계약(이미 있으면 거부)에 안 맞으니 그 함수를
안 쓴다"고 판단했는데, 그 대가로 `User.objects.get_or_create` 뒤에 바로
`is_staff=True`를 놓아 **이미 있는 계정이면 무엇이든** Operator로 승격시키는
길을 열어 버렸다 — 우연히 참가자 계정과 같은 이름으로 이 명령을 부르면(또는
소셜 로그인이 그 사용자 이름을 먼저 선점하면) 소셜 계정을 가진 사용자가 그대로
Operator가 된다. `accounts.operators.assert_can_become_operator`가 정확히 이
경로를 막으려고 있는 함수라, 승격 직전에 그 함수를 거친다 — "이미 존재하면
거부"라는 create_operator의 계약만 우회하고, 서로소 불변식 자체는 그대로 지킨다.
"""

from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.operators import OperatorInvariantError, assert_can_become_operator


class Command(BaseCommand):
    help = "e2e 스펙이 로그인할 Operator 계정을 멱등하게 만든다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--username", default="e2e-operator")
        parser.add_argument("--password", default="e2e-operator-pw-9134-xyz")
        parser.add_argument("--superuser", action="store_true")

    def handle(self, *args, **options) -> None:
        # 고정된 기본 비밀번호("e2e-operator-pw-9134-xyz")를 쓰는 명령이 운영
        # 이미지에 그대로 들어간다 — 배포 환경에서 실행되면 그 자체로 알려진
        # 자격증명의 Operator 계정이 생긴다(코드리뷰 지적). dev·CI에서만 돈다.
        if settings.IS_DEPLOYED_ENVIRONMENT:
            raise CommandError(
                f"CODEMIT_DEPLOYMENT_TARGET={settings.CODEMIT_DEPLOYMENT_TARGET} 인데 "
                "이 명령을 실행하려 했다 — seed_e2e_operator 는 e2e 전용이라 배포 "
                "환경에서 실행할 수 없다(고정된 기본 비밀번호를 쓴다)."
            )

        User = get_user_model()
        username: str = options["username"]
        password: str = options["password"]
        superuser: bool = bool(options["superuser"])

        operator = User.objects.filter(username=username).first()
        if operator is not None:
            # 참가자 → 운영자 방향의 서로소 불변식(ADR-0018). 이미 Operator인
            # 계정(소셜 계정이 없다)은 그대로 통과한다 — 이 명령을 반복 실행해
            # 비밀번호·등급을 갱신하는 것이 정상 경로다.
            try:
                assert_can_become_operator(operator)
            except OperatorInvariantError as exc:
                raise CommandError(str(exc)) from exc
        else:
            operator = User(username=username)

        operator.is_staff = True
        operator.is_superuser = superuser
        operator.is_active = True
        # **이미 같은 비밀번호면 다시 설정하지 않는다** (#157). Django 는 비밀번호가
        # 바뀌면 세션 인증 해시로 그 계정의 **살아 있는 세션을 전부** 무효화한다.
        # 이 명령은 멱등하다고 적혀 있고 실제로 반복 호출되는데(공용 계정을 워커마다
        # 한 번씩 심는다), 매번 해시를 새로 쓰면 옆 워커가 방금 로그인한 세션이
        # 그 자리에서 죽는다 — 화면은 그저 로그인으로 튕기고 원인은 여기다.
        # 직렬 실행에서는 프로세스당 한 번만 심어 드러나지 않았다.
        if not operator.check_password(password):
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
