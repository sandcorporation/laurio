"""이의 심판 e2e(#67) 전용 — 한 Contest의 원장 분개 개수를 조회한다.

시딩이 아니라 조회지만 다른 `seed_e2e_operator_*` 명령들과 같은 디렉터리·실행
관용구(uv run manage.py, 마지막 줄에 JSON 한 덩어리, 배포 환경 거부)를 그대로
따른다.

**존재 이유.** #67 AC는 "재심판 시도가 409로 거절된다"에서 멈추지 않고 "정정
분개가 하나 더 생기지 않았음을 원장에서 실제로 확인"하라고 요구한다(원장은
append-only라 잘못 남은 정정은 지울 수 없다). e2e가 이 명령을 심판 전후로 불러
분개 개수가 그대로인지 비교한다.

**HTTP(운영자 세션)를 거치지 않고 ORM으로 직접 센다.** 처음에는 `_ruler_client()`
로 `/api/ledger/contests/{id}/entries`를 쳤는데, `_ruler_client()`는
`seed_e2e_operator --superuser`를 불러 고정 비밀번호 superuser 계정을 만들거나
(이미 비활성화됐다면) **되살린다**(코드리뷰 지적) — 체인 5가 "e2e가 개발자
계정을 잠근다"로 지적받아 고친 것과 정확히 같은 부류의 부작용이다. 이 명령은
개수를 세는 도구일 뿐 시딩이 아니므로, 그런 부작용 없이 `JournalEntry`를
직접 세는 편이 맞다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from contests.models import Contest
from ledger.models import JournalEntry

from .seed_e2e_operator_queues import _refuse_in_deployed_environment


class Command(BaseCommand):
    help = "한 Contest의 원장 분개 개수를 센다(#67 e2e 전용, ORM 직접 조회)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--contest-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment("count_ledger_entries")

        contest = Contest.objects.get(id=options["contest_id"])
        count = JournalEntry.objects.filter(contest_id=contest.ledger_id).count()

        self.stdout.write(json.dumps({"count": count}))
