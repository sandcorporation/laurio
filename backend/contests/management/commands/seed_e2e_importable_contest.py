"""강의실 「문제 가져오기」 시트의 공모전 탭 e2e(#876)용 — 클래스에서 들여오기를 허용한 공개 중
무료 공모전 하나를 심고 `{contest_id, title}` JSON 을 마지막 줄에 찍는다.

개최 흐름(운영자 권한 부여 → 무료 공모전 개최 → 공개)을 화면 없이 걷는 대신 ORM 으로 상태를 직접
만든다 — 그 흐름은 backend 시험이 지킨다. 호출마다 새 행만 만들고 이름이 `run_id` 로 갈려
서로 부딪히지 않는다. 제목 접두어는 일부러 `[E2E]` 가 아니다 — `seed_e2e_contests` 가 그 접두어를
통째로 걷어, 도는 중인 다른 스펙의 행을 지울 수 있다.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import SponsorProfile
from contests.models import Category, Contest, DeliverableType, Requirement
from core.management.stdout_utf8 import write_stdout_utf8


class Command(BaseCommand):
    help = "클래스에서 들여오기를 허용한 공개 중 무료 공모전 하나를 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--run-id", default="", help="이름을 가르는 실행 표식")

    def handle(self, *args, **options) -> None:
        run_id = options["run_id"] or uuid.uuid4().hex[:8]
        username = f"e2e-import-host-{run_id}-{uuid.uuid4().hex[:6]}"
        user = get_user_model().objects.create_user(username=username, email=f"{username}@example.invalid")
        user.set_unusable_password()
        user.save(update_fields=["password"])
        sponsor = SponsorProfile.objects.create(user=user, display_name="E2E 가져오기 개최자")
        # 이름이 호출마다 달라야 병렬 호출이 유일 제약에 걸리지 않는다. `[E2E]` 접두어라 `prune_e2e_junk` 가 걷는다.
        tag = uuid.uuid4().hex[:8]
        category = Category.objects.create(name=f"[E2E] 가져오기 {tag}")
        deliverable_type = DeliverableType.objects.create(name=f"[E2E] 가져오기 {tag}", minimum_prize=0)
        title = f"[E2E-IMPORT] 가져올 공모전 {run_id}-{uuid.uuid4().hex[:6]}"
        # 시드는 변수로 넘긴다 — 개최 흐름을 걷지 않고 공개 상태로 바로 만드는 자리라 `CREATION_STATES` 에 싣지 않는다.
        status = Contest.Status.PUBLISHED
        contest = Contest.objects.create(
            sponsor=sponsor,
            title=title,
            category=category,
            description="강의실 가져오기 e2e 용 무료 공모전입니다.",
            prize=0,
            deadline_at=timezone.now() + timedelta(days=7),
            status=status,
            is_free=True,
            allows_classroom_import=True,
        )
        contest.deliverable_types.set([deliverable_type])
        Requirement.objects.create(contest=contest, text="할 일을 추가할 수 있다", grade="required", order=0)
        write_stdout_utf8(self.stdout, json.dumps({"contest_id": contest.pk, "title": title}, ensure_ascii=False) + "\n")
