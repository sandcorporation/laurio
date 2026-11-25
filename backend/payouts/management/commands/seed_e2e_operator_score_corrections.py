"""운영자 앱 점수 정정 화면 e2e 전용(#1183) — 채점이 끝난 마감 공모전 둘: 배분 전 하나, 배분 끝남 하나.

둘 다 참가자 둘이 채점까지 끝난 상태다. 「배분 끝남」은 `Distribution` 행이 있는 것으로 만든다(판정은
`distributions.services.is_prize_settled` 하나다 — 화면은 API 의 `prize_settled` 만 읽는다). 호출마다 새 공모전이다.

배포 환경에서는 돌지 않는다(다른 seed_e2e_* 명령과 같은 이유).
"""

from __future__ import annotations

import json
import uuid

from django.core.management.base import BaseCommand
from django.test import Client
from django.utils import timezone

from contests.models import Contest
from core.e2e_guard import refuse_in_deployed_environment
from distributions.models import Distribution

from .seed_e2e_operator_queues import (
    DEADLINE_OFFSET,
    run_scoring_scan,
    _RUN_ID_OVERRIDE,
    _clear_stale_seed_contests,
    _close_contest,
    _publish_contest,
    _submit,
    _verified_user,
)


def _scored_contest(client: Client, label: str, uid: str) -> dict:
    deadline = timezone.now() + DEADLINE_OFFSET
    _sponsor, contest = _publish_contest(
        client,
        sponsor_uid=f"e2e-corr-{label}-sponsor-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    devs = [_verified_user(client, f"e2e-corr-{label}-dev-{uid}-{i}") for i in (1, 2)]
    submissions = [_submit(client, dev, contest["id"], requirement_id=requirement_id) for dev in devs]
    _close_contest(client, contest, deadline=deadline)
    run_scoring_scan(client)
    return {"contest_id": contest["id"], "submission_ids": [s["id"] for s in submissions]}


def seed_score_correction_contests() -> dict:
    client = Client()
    uid = uuid.uuid4().hex[:8]
    open_contest = _scored_contest(client, "open", uid)
    settled = _scored_contest(client, "settled", uid)
    Distribution.objects.create(
        contest=Contest.objects.get(pk=settled["contest_id"]),
        cutline_percentage="60.00",
        total_prize=1_000_000,
        qualifying_count=2,
        share_amount=500_000,
    )
    return {"open": open_contest, "settled": settled}


class Command(BaseCommand):
    help = "운영자 앱 점수 정정 e2e 에 필요한, 채점이 끝난 마감 공모전 둘(배분 전·배분 끝남)을 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--run-id", default=None, help="이번 실행을 가리키는 토큰(다른 큐 시드와 같다).")

    def handle(self, *args, **options) -> None:
        refuse_in_deployed_environment("seed_e2e_operator_score_corrections")
        run_id = options.get("run_id")
        token = _RUN_ID_OVERRIDE.set(run_id) if run_id else None
        try:
            _clear_stale_seed_contests()
            self.stdout.write(json.dumps(seed_score_correction_contests()))
        finally:
            if token is not None:
                _RUN_ID_OVERRIDE.reset(token)
