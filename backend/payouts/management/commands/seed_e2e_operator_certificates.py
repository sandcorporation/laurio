"""운영자 앱 상장 목록·취소 e2e 전용(#1131) — 마감된 공모전 하나에 상장 둘이 발급된 상태.

발급은 개최자 표면(`/api/contests/{id}/certificates`)을 그대로 태운다 — 번호·확인 주소·PDF 가
실제 발급 규칙대로 만들어진다. 마감은 `seed_e2e_operator_queues._close_contest` 로 상태만
옮기고 마감 시각을 과거로 당긴다(발급은 마감 뒤에만 된다). 호출마다 새 공모전이다.

배포 환경에서는 돌지 않는다(다른 seed_e2e_* 명령과 같은 이유).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.test import Client
from django.utils import timezone

from contests.models import Contest
from core.e2e_guard import refuse_in_deployed_environment

from .seed_e2e_operator_queues import (
    DEADLINE_OFFSET,
    _RUN_ID_OVERRIDE,
    _auth_header,
    _clear_stale_seed_contests,
    _close_contest,
    _publish_contest,
    _submit,
    _verified_user,
)


def seed_issued_certificates() -> dict:
    client = Client()
    uid = uuid.uuid4().hex[:8]
    deadline = timezone.now() + DEADLINE_OFFSET
    sponsor, contest = _publish_contest(
        client,
        sponsor_uid=f"e2e-cert-sponsor-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    devs = [_verified_user(client, f"e2e-cert-dev-{uid}-{i}") for i in (1, 2)]
    submissions = [_submit(client, dev, contest["id"], requirement_id=requirement_id) for dev in devs]
    _close_contest(client, contest, deadline=deadline)
    Contest.objects.filter(id=contest["id"]).update(deadline_at=timezone.now() - timedelta(minutes=1))

    award_date = timezone.localtime(timezone.now()).date().isoformat()
    names = [f"이상장{uid[:4]}", f"박상장{uid[:4]}"]
    items = [
        {
            "submission_id": submission["id"],
            "text": {
                "award_name": "최우수상",
                "recipient_name": name,
                "body": "",
                "giver_name": "홍길동",
                "giver_title": "심사위원장",
                "award_date": award_date,
            },
        }
        for submission, name in zip(submissions, names)
    ]
    response = client.post(
        f"/api/contests/{contest['id']}/certificates",
        data={"items": items},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 201, response.content
    return {
        "contest_id": contest["id"],
        "sponsor_access": sponsor["access"],
        "certificates": [
            {"id": c["id"], "number": c["number"], "recipient_name": c["recipient_name"]}
            for c in response.json()
        ],
    }


class Command(BaseCommand):
    help = "운영자 앱 상장 목록·취소 e2e 에 필요한, 상장 둘이 발급된 마감 공모전 하나를 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--run-id", default=None, help="이번 실행을 가리키는 토큰(다른 큐 시드와 같다).")

    def handle(self, *args, **options) -> None:
        refuse_in_deployed_environment("seed_e2e_operator_certificates")
        run_id = options.get("run_id")
        token = _RUN_ID_OVERRIDE.set(run_id) if run_id else None
        try:
            _clear_stale_seed_contests()
            self.stdout.write(json.dumps(seed_issued_certificates()))
        finally:
            if token is not None:
                _RUN_ID_OVERRIDE.reset(token)
