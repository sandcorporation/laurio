"""이의 심판 e2e(#67) 전용 — 한 Contest의 원장 분개 개수를 조회한다.

시딩이 아니라 조회지만 다른 `seed_e2e_operator_*` 명령들과 같은 디렉터리·실행
관용구(uv run manage.py, 마지막 줄에 JSON 한 덩어리, 배포 환경 거부)를 그대로
따르고, `seed_e2e_operator_appeal._ruler_client()`를 재사용한다.

**존재 이유.** #67 AC는 "재심판 시도가 409로 거절된다"에서 멈추지 않고 "정정
분개가 하나 더 생기지 않았음을 원장에서 실제로 확인"하라고 요구한다(원장은
append-only라 잘못 남은 정정은 지울 수 없다). e2e가 이 명령을 심판 전후로 불러
분개 개수가 그대로인지 비교한다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from contests.models import Contest

from .seed_e2e_operator_appeal import _ruler_client
from .seed_e2e_operator_queues import _refuse_in_deployed_environment


class Command(BaseCommand):
    help = "한 Contest의 원장 분개 개수를 운영자 세션으로 조회한다(#67 e2e 전용)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--contest-id", type=int, required=True)

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment()

        contest = Contest.objects.get(id=options["contest_id"])
        client = _ruler_client()
        response = client.get(f"/api/ledger/contests/{contest.ledger_id}/entries")
        assert response.status_code == 200, response.content
        entries = response.json()

        self.stdout.write(json.dumps({"count": len(entries)}))
