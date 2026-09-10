"""0002_backfill_handover_for_existing_awards 백필이 이미 Award된 행이 있는
DB에서도 안전한지 확인한다(tests/test_judging_ends_at_backfill_migration.py와
같은 형식, #15 리뷰 지적 2).

Handover는 지금까지 awards.api.award_submission이 Award 생성과 같은 트랜잭션
에서만 만들었다 — 이 기능이 배포되기 전에 이미 Award된 Contest는 Handover가
아예 없는 채로 남는다. 이 테스트는 handovers를 0001(백필 이전)로 되돌린 뒤 —
awards.contests.submissions 앱 스키마 자체는 이 롤백의 영향을 받지 않으므로
— 현재 모델로 Handover 없는 Award를 직접 만들고, handovers를 최신까지
전진시켜 0002의 RunPython이 그 Award에 Handover를 채우는지 직접 확인한다.
채워지지 않으면 그 Award는 모든 Handover 엔드포인트에서 404이고, release-due
스캔은 Handover 테이블만 스캔하므로 이 행을 볼 방법이 없으며, Payout 요청도
404다 — Escrow 해제도 지급도 영구히 막힌다.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from awards.models import Award
from contests.models import Category, Contest
from contests.models import ContestSubmission
from submissions.models import Submission


class HandoverBackfillMigrationTests(TransactionTestCase):
    def test_backfill_creates_handover_for_pre_existing_awards(self):
        executor = MigrationExecutor(connection)

        # handovers를 0001(백필 이전)로 되돌린다. awards·contests·submissions는
        # 이 마이그레이션의 영향을 받지 않으므로(핸드오버 백필은 이 앱들의
        # 스키마를 건드리지 않는다) 현재(최신) 모델을 그대로 써서 행을 만들 수
        # 있다.
        executor.migrate([("handovers", "0001_initial")])
        executor.loader.build_graph()

        User = get_user_model()
        sponsor_user = User.objects.create_user(
            username="handover-migrator-sponsor", email="handover-migrator-sponsor@example.com"
        )
        developer_user = User.objects.create_user(
            username="handover-migrator-dev", email="handover-migrator-dev@example.com"
        )
        sponsor = SponsorProfile.objects.create(user=sponsor_user)
        developer = DeveloperProfile.objects.create(user=developer_user)
        category = Category.objects.create(name="Handover 마이그레이션 테스트")

        contest = Contest.objects.create(
            sponsor=sponsor,
            title="이미 Award된 Contest",
            category=category,
            description="",
            prize=1_000_000,
            deadline_at=timezone.now() - timedelta(days=30),
            status=Contest.Status.AWARDED,
            required_minimum_prize=0,
            is_underfunded=False,
        )
        submission = ContestSubmission.objects.create(
            user=developer_user,
            product=Submission.Product.CONTEST,
            contest=contest,
            developer=developer,
        )
        awarded_at = timezone.now() - timedelta(days=20)
        award = Award.objects.create(contest=contest, submission=submission, awarded_at=awarded_at)

        # 이 시점에 Handover는 없다 — 마이그레이션이 아니라 (지금은 되돌려 놓은)
        # 앱 코드가 Award와 같은 트랜잭션에서 만드는 것이었기 때문이다.
        old_state = executor.loader.project_state(("handovers", "0001_initial"))
        HistoricalHandover = old_state.apps.get_model("handovers", "Handover")
        assert not HistoricalHandover.objects.filter(award_id=award.id).exists()

        # 최신 상태로 다시 전진시킨다 — 0002의 RunPython 백필을 실제로 통과해야
        # 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from handovers.models import Handover

        handover = Handover.objects.get(award_id=award.id)
        assert handover.status == Handover.Status.PENDING_ACCEPTANCE
        assert handover.release_deadline_at == awarded_at + timedelta(days=14)
        assert handover.released_at is None
