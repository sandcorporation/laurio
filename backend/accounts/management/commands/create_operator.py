"""첫 Operator 를 만드는 부트스트랩 명령 (#42, ADR-0018/0019).

계정 관리 화면이 없으므로(ADR-0019 가 Django admin 을 내렸다) 부트스트랩 경로가
코드에 있어야 한다. 이후 Operator 는 `is_superuser` 가 운영자 API 로 만든다(#45).

**`createsuperuser` 를 쓰지 않는다.** 그 명령은 Operator 와 참가자가 서로소라는
불변식을 모르므로, 소셜 계정을 가진 `User` 를 그대로 staff 로 만들어 버린다 —
`accounts.operators` 의 주석 참고.
"""

from __future__ import annotations

from getpass import getpass

from django.core.management.base import BaseCommand, CommandError

from accounts.operators import OperatorInvariantError, create_operator


class Command(BaseCommand):
    help = "Operator 계정을 만든다(서로소 불변식과 비밀번호 정책을 강제한다)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("username")
        parser.add_argument(
            "--password",
            default=None,
            help="생략하면 입력을 받는다. CI·스크립트에서만 명시적으로 넘겨라.",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            help="Operator 를 만들고 비활성화할 수 있는 등급으로 만든다(#45).",
        )

    def handle(self, *args, **options) -> None:
        password = options.get("password") or getpass("Operator 비밀번호: ")

        try:
            operator = create_operator(
                options["username"], password, superuser=bool(options.get("superuser"))
            )
        except OperatorInvariantError as exc:
            # CommandError 로 감싼다 — 트레이스백 대신 이유만 보여주고 종료 코드 1.
            raise CommandError(str(exc)) from exc

        grade = "superuser" if operator.is_superuser else "staff"
        self.stdout.write(f"Operator 를 만들었습니다: {operator.username} ({grade})")
