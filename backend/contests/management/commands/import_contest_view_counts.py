"""배포 직후 한 번 — Redis에 이미 쌓인 조회수를 `Contest.view_count`(DB)로 옮긴다
(#446, spec #444).

`contests.view_flush`의 정기 스캔은 **그 이후에 바뀐** Contest만 옮긴다 — 이 기능이
배포되기 전부터 Redis에 쌓여 있던 숫자는 누구도 "바뀌었다"고 표시한 적이 없어 그 스캔의
후보에 절대 오르지 않는다. 이 명령이 그 최초 한 번을 메운다: DB에 있는 Contest 전부의
Redis 값을 한 번에 읽어(`contests.view_tracking.get_view_counts`), 그 값이 있는 것만
`Contest.view_count`를 고친다.

**멱등하다.** 두 번 돌려도 안전하다 — 이미 옮긴 뒤에는 Redis 값과 DB 값이 같아 두 번째
실행은 아무것도 바꾸지 않는다. staging에서 실수로 한 번 더 돌려도 데이터가 틀어지지
않는다는 뜻이라, 배포 스크립트가 실행 여부를 따로 추적할 필요가 없다.

**정기 스캔과 로직을 나누지 않는다.** 옮기는 규칙(값이 있는 id만 고친다, 한 SQL문으로
고친다)은 `contests.view_flush`가 이미 갖고 있다 — 여기서 다시 쓰면 그 규칙이 두 벌이
되어 한쪽만 고쳐질 위험이 생긴다. 대신 이 명령은 **DB에 있는 Contest 전부**를 「바뀐
공모전」으로 표시만 해 두고, 그 자리에서 옮기기 스캔을 한 번 직접 돌려 결과를 즉시
보여준다 — 사람이 명령 하나만 실행하면 되고, 운영에서는 다음 정기 실행을 기다릴
필요도 없다.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from contests.models import Contest
from contests.view_flush import SCAN_NAME
from contests.view_flush_store import get_changed_contests_store
from core.scans import run_scan


class Command(BaseCommand):
    help = "Redis 에 이미 쌓인 공모전 조회수를 Contest.view_count(DB) 로 한 번에 옮긴다."

    def handle(self, *args, **options) -> None:
        contest_ids = list(Contest.objects.values_list("id", flat=True))
        if not contest_ids:
            self.stdout.write(json.dumps({"contest_count": 0, "result": None}, ensure_ascii=False))
            return

        store = get_changed_contests_store()
        for contest_id in contest_ids:
            store.mark_changed(contest_id)

        result = run_scan(SCAN_NAME)

        self.stdout.write(
            json.dumps({"contest_count": len(contest_ids), "result": result}, ensure_ascii=False)
        )
