"""0005_backfill_judging_ends_at 백필이 기존 CLOSED 행이 있는 DB에서도 안전한지
확인한다 (#13 리뷰 지적 5, tests/test_contest_ledger_id_migration.py와 같은 형식).

0004는 judging_ends_at을 null 허용 컬럼으로만 추가했다 — 그 값을 실제로 채우는
조건부 UPDATE는 core.transitions 레지스트리에 등록된 PUBLISHED -> CLOSED 전이
규칙뿐이라, 이 기능이 배포되기 전에 이미 CLOSED로 넘어가 있던 행은 손대지 않는다.
이 테스트는 0004 상태에서 status="closed"인 Contest 행을 직접 만든 뒤 마이그레이션을
최신까지 전진시켜, 0005의 RunPython이 deadline_at + 7일로 judging_ends_at을
채우는지 직접 확인한다. 채워지지 않으면 Award는 403, 연장은 409, 스케줄러의
`__lte` 비교는 NULL과 매치하지 않아 그 Contest가 영영 갇힌다.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import SponsorProfile


class JudgingEndsAtBackfillTests(TransactionTestCase):
    def test_backfill_derives_judging_ends_at_from_deadline_for_pre_existing_closed_rows(self):
        executor = MigrationExecutor(connection)

        # contests를 0004로 되돌린다 — judging_ends_at 컬럼은 이미 있지만 아직
        # 아무 것도 백필되지 않은 시점의 히스토리컬 모델로 행을 만들기 위함이다.
        executor.migrate([("contests", "0004_contest_judging_ends_at_and_more")])
        executor.loader.build_graph()

        old_state = executor.loader.project_state(
            ("contests", "0004_contest_judging_ends_at_and_more")
        )
        HistoricalCategory = old_state.apps.get_model("contests", "Category")
        HistoricalContest = old_state.apps.get_model("contests", "Contest")

        User = get_user_model()
        user = User.objects.create_user(username="migrator-13", email="migrator-13@example.com")
        sponsor = SponsorProfile.objects.create(user=user)
        category = HistoricalCategory.objects.create(name="마이그레이션 테스트(#13)")

        deadline = timezone.now() - timedelta(days=10)
        closed_contest = HistoricalContest.objects.create(
            sponsor_id=sponsor.id,
            category_id=category.id,
            title="이미 마감된 Contest",
            description="",
            prize=1_000_000,
            deadline_at=deadline,
            status="closed",
            required_minimum_prize=0,
            is_underfunded=False,
            judging_extension_count=0,
            refund_disabled=False,
            # judging_ends_at은 명시하지 않는다 — 필드 기본값(null)이 이 백필이
            # 고쳐야 하는 "이미 CLOSED인데 judging_ends_at이 비어 있는" 상황을
            # 그대로 재현한다.
        )

        # 대조군: 아직 DRAFT인 행은 judging_ends_at이 계속 null이어야 한다 —
        # 백필이 CLOSED 여부를 가리지 않고 전부 채워버리면 안 된다.
        draft_contest = HistoricalContest.objects.create(
            sponsor_id=sponsor.id,
            category_id=category.id,
            title="아직 초안인 Contest",
            description="",
            prize=1_000_000,
            deadline_at=timezone.now() + timedelta(days=10),
            status="draft",
            required_minimum_prize=0,
            is_underfunded=False,
            judging_extension_count=0,
            refund_disabled=False,
        )

        # 최신 상태로 다시 전진시킨다 — 0005의 RunPython 백필을 실제로 통과해야
        # 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from contests.models import Contest

        migrated_closed = Contest.objects.get(id=closed_contest.id)
        migrated_draft = Contest.objects.get(id=draft_contest.id)

        assert migrated_closed.judging_ends_at == deadline + timedelta(days=7)
        assert migrated_draft.judging_ends_at is None
