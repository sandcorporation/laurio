"""과제 e2e(#242) 전용 — 이미 연 과제 하나의 `deadline_at`을 실제 시간이 아니라
과거로 직접 옮긴다.

**배경.** `assignment.spec.ts`는 마감 후 채점을 확인해야 하는데, 예전에는 마감을
실제로 45초+2초 벽시계로 흘려보냈다(`page.waitForTimeout`) — `test.setTimeout(150_000)`
예산의 3분의 1이 순수 대기였다. CI 러너 하나에서 e2e 잡 여럿이 프로덕션 빌드를 상대로
도는 환경이라 남는 여유가 얇았고, 예산이 다하면 그 순간 진행 중이던 아무 호출에서나
`Test timeout of 150000ms exceeded`가 났다(관측된 자리는 우연히 매번 `setInputFiles`).

CLAUDE.md("tick 은 시간을 앞당기지 않는다 … 며칠 걸리는 시나리오를 몇 초에 보려면
데이터의 시각을 과거로 옮긴다")와 같은 이유로, 시계(`core.clock.Clock`/`ClockOverride`,
ADR-0003)를 흔들지 않고 **이 과제 하나의** `deadline_at`만 UPDATE한다.
`ClockOverride`는 프로세스 전역 단일 행이라(pk=1) 건드리면 같은 e2e 잡에서 병렬로
도는 다른 스펙들의 스캔·전이까지 함께 틀어진다 — `seed_e2e_operator_queues.py`가
이미 겪은 사고와 같은 모양이다(그 파일의 `DEADLINE_OFFSET` 주석: 전역 스캔 반경을
건드려 DB의 Contest를 전부 전이시켜 버린 적이 있다). 행 하나만 UPDATE하면 그 반경이
이 과제로 좁혀진다.

**공개 `PATCH /api/assignments/{id}`(`update_assignment`)를 쓰지 않는 이유는 #209
때문이다.** 첫 제출이 과제 내용(마감 포함)을 잠근다 — 제출이 1건이라도 있으면 그
엔드포인트가 409로 거부한다. 이 시드가 다루는 흐름은 정확히 "학생의 제출이 이미 끝난
뒤 마감을 과거로 옮긴다"이므로 그 잠금을 우회해야 하고, 다른 `seed_e2e_*` 명령들도
이미 관리 명령이 공개 API의 잠금·검증을 거치지 않고 ORM으로 직접 데이터를 조립한다 —
새 장치가 아니라 이 저장소가 이미 쓰는 것과 같은 모양이다.

배포 환경에서는 돌지 않는다 — 다른 `seed_e2e_*` 명령과 같은 이유(e2e 전용 백도어가
운영 이미지에 살아 있으면 안 된다).
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from contests.models import Contest


class Command(BaseCommand):
    help = "이미 연 과제 하나의 deadline_at을 실제 시간이 아니라 과거로 직접 옮긴다(e2e 전용, #242)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--assignment-id",
            dest="assignment_id",
            type=int,
            required=True,
            help="마감을 과거로 옮길 Assignment(Contest, kind=ASSIGNMENT)의 id.",
        )

    def handle(self, *args, **options) -> None:
        if settings.IS_DEPLOYED_ENVIRONMENT:
            raise CommandError(
                f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 인데 "
                "이 명령을 실행하려 했다 — seed_e2e_expire_assignment_deadline 은 "
                "e2e 전용이라 배포 환경에서 실행할 수 없다."
            )

        assignment_id = options["assignment_id"]
        # 1분 전 — 실시간 기준으로 이미 확실히 지난 값이면 충분하다. 스캔은
        # `deadline_at <= as_of`(`as_of`는 `Clock.now()`, 오버라이드가 없으므로 실제
        # 현재 시각)만 보므로 더 과거로 밀 이유가 없다.
        deadline_at = timezone.now() - timedelta(minutes=1)

        updated = Contest.objects.filter(id=assignment_id, kind=Contest.Kind.ASSIGNMENT).update(
            deadline_at=deadline_at
        )
        if updated == 0:
            raise CommandError(f"Assignment id={assignment_id} 를 찾을 수 없다.")

        # 마지막 줄에 JSON 한 덩어리 — 다른 seed_e2e_* 명령과 같은 관용구
        # (`core/api.py`의 `e2e_seed`가 이 줄만 파싱한다).
        self.stdout.write(json.dumps({"deadline_at": deadline_at.isoformat()}))
