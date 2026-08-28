"""0002_contest_ledger_id 백필이 기존 행이 있는 DB에서도 안전한지 확인한다.

`AddField(default=uuid.uuid4, unique=True)` 하나로 처리하면 Django가
`effective_default()`를 딱 한 번만 평가해 이미 있는 모든 행에 같은 UUID를 써버려
unique 인덱스 생성이 중복 키 위반으로 실패한다(#8이 이미 돌아간 dev·staging
DB에서 실제로 재현됨). 이 테스트는 0001 상태에서 Contest 행을 두 개 이상 만든
뒤 마이그레이션을 최신까지 전진시켜, 백필이 행마다 서로 다른 UUID를 배정하는지
직접 확인한다.
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import SponsorProfile


class ContestLedgerIdBackfillTests(TransactionTestCase):
    def test_backfill_assigns_distinct_uuids_to_pre_existing_rows(self):
        executor = MigrationExecutor(connection)

        # contests를 0001로 되돌린다 — 그 시점 히스토리컬 모델로 행을 만들기
        # 위함이다. payments(0002에 의존)는 그래프상 자동으로 함께 되돌아간다.
        executor.migrate([("contests", "0001_initial")])
        executor.loader.build_graph()

        old_state = executor.loader.project_state(("contests", "0001_initial"))
        HistoricalCategory = old_state.apps.get_model("contests", "Category")
        HistoricalContest = old_state.apps.get_model("contests", "Contest")

        # accounts 앱은 되돌리지 않았으므로 현재(최신) 모델을 그대로 쓴다.
        User = get_user_model()
        user = User.objects.create_user(username="migrator", email="migrator@example.com")
        sponsor = SponsorProfile.objects.create(user=user)

        category = HistoricalCategory.objects.create(name="마이그레이션 테스트")

        contest_ids = []
        for title in ("A", "B", "C"):
            contest = HistoricalContest.objects.create(
                sponsor_id=sponsor.id,
                category_id=category.id,
                title=title,
                description="",
                prize=1_000_000,
                deadline_at=timezone.now(),
                status="draft",
                required_minimum_prize=0,
                is_underfunded=False,
            )
            contest_ids.append(contest.id)

        # 최신 상태로 다시 전진시킨다 — 0002의 세 단계(AddField null 허용 →
        # RunPython 백필 → AlterField unique・not null)를 실제로 통과해야 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from contests.models import Contest

        ledger_ids = list(
            Contest.objects.filter(id__in=contest_ids)
            .order_by("id")
            .values_list("ledger_id", flat=True)
        )

        assert len(ledger_ids) == 3
        assert all(ledger_id is not None for ledger_id in ledger_ids)
        assert len(set(ledger_ids)) == 3  # 세 행 모두 서로 다른 UUID를 받아야 한다.
