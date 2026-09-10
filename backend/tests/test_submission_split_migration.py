"""`submissions.Submission`을 부모·자식으로 쪼개는 마이그레이션이 기존 행을
잃지 않는지 확인한다 (#270, ADR-0039, `tests/test_contest_ledger_id_migration.py`
·`tests/test_handover_backfill_migration.py`와 같은 형식).

`submissions`를 0011(이 티켓 이전)로 되돌린 뒤 — `contests`도 그래프상
0018(`ContestSubmission`)이 함께 되돌아간다 — 그 시점 히스토리컬 모델로
`contest`·`developer`를 직접 가진 `Submission`을 만들고, 그 위에 자료
(`SubmissionAsset`, 부모 FK)까지 매단다. 최신까지 전진시킨 뒤 다음을 본다:

- 부모 pk가 그대로 보존된다(`Submission.id == ContestSubmission.id`).
- `contests.ContestSubmission`이 옛 `contest`·`developer` 값을 그대로 물려받았다.
- `Submission.user`가 `developer.user`와 같다(#270이 지키는 두 불변식 중 하나).
- `Submission.product`가 `contest`로 채워졌다.
- 자료(`SubmissionAsset`)의 FK가 여전히 그 부모를 가리킨다 — pk가 안 바뀌었으므로
  손대지 않아도 유효해야 한다.
- 유니크 제약(이제 `ContestSubmission`에 있다)이 여전히 같은 (contest, developer)
  의 두 번째 제출을 막는다.

그리고 되돌리기가 값을 복구하는지도 같은 실행 안에서 확인한다 — 0011까지
되돌린 뒤 부모의 `contest_id`·`developer_id`가 원래 값 그대로 복원됐는지 본다.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from contests.models import Category, Contest


class SubmissionSplitMigrationTests(TransactionTestCase):
    def _make_contest_and_developer(self):
        User = get_user_model()
        sponsor_user = User.objects.create_user(
            username="submission-split-sponsor", email="submission-split-sponsor@example.com"
        )
        developer_user = User.objects.create_user(
            username="submission-split-dev", email="submission-split-dev@example.com"
        )
        sponsor = SponsorProfile.objects.create(user=sponsor_user)
        developer = DeveloperProfile.objects.create(user=developer_user)
        category = Category.objects.create(name="제출물 분할 마이그레이션 테스트")
        contest = Contest.objects.create(
            sponsor=sponsor,
            title="분할 전 제출물이 있는 공모전",
            category=category,
            description="",
            prize=1_000_000,
            deadline_at=timezone.now(),
            status=Contest.Status.DRAFT,
            required_minimum_prize=0,
            is_underfunded=False,
        )
        return contest, developer

    def test_split_preserves_parent_pk_and_moves_contest_developer_to_child(self):
        executor = MigrationExecutor(connection)

        # submissions를 0011(이 티켓 이전)로 되돌린다 — contests의 0018
        # (ContestSubmission)도 그래프상 자동으로 함께 되돌아간다.
        executor.migrate([("submissions", "0011_merge_screenshot_kind_and_destroyed_at")])
        executor.loader.build_graph()

        contest, developer = self._make_contest_and_developer()

        old_state = executor.loader.project_state(
            ("submissions", "0011_merge_screenshot_kind_and_destroyed_at")
        )
        HistoricalSubmission = old_state.apps.get_model("submissions", "Submission")
        HistoricalSubmissionAsset = old_state.apps.get_model("submissions", "SubmissionAsset")

        submission = HistoricalSubmission.objects.create(
            contest_id=contest.id, developer_id=developer.id
        )
        asset = HistoricalSubmissionAsset.objects.create(
            submission_id=submission.id, kind="source", value="old-object-key"
        )

        # 최신 상태로 전진시킨다 — #270의 세 마이그레이션(0012 user/product 백필,
        # contests/0018 ContestSubmission 생성+복제, 0013/0014 부모 컬럼 제거)을
        # 실제로 통과해야 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from contests.models import ContestSubmission
        from submissions.models import Submission, SubmissionAsset

        migrated = Submission.objects.get(pk=submission.id)
        assert migrated.pk == submission.id  # 부모 pk가 그대로다.
        assert migrated.product == Submission.Product.CONTEST
        assert migrated.user_id == developer.user_id  # 두 불변식 중 하나.

        child = ContestSubmission.objects.get(pk=submission.id)
        assert child.contest_id == contest.id
        assert child.developer_id == developer.id

        # 자료의 FK는 손대지 않았다 — pk가 그대로라 여전히 유효해야 한다.
        migrated_asset = SubmissionAsset.objects.get(pk=asset.id)
        assert migrated_asset.submission_id == submission.id
        assert migrated_asset.value == "old-object-key"

        # 유니크 제약이 여전히 같은 (contest, developer)의 두 번째 제출을 막는다
        # — 이제는 자식(ContestSubmission)에서 걸린다.
        with self.assertRaises(IntegrityError):
            ContestSubmission.objects.create(
                user_id=developer.user_id,
                product=Submission.Product.CONTEST,
                contest_id=contest.id,
                developer_id=developer.id,
            )

    def test_split_migration_is_reversible(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("submissions", "0011_merge_screenshot_kind_and_destroyed_at")])
        executor.loader.build_graph()

        contest, developer = self._make_contest_and_developer()

        old_state = executor.loader.project_state(
            ("submissions", "0011_merge_screenshot_kind_and_destroyed_at")
        )
        HistoricalSubmission = old_state.apps.get_model("submissions", "Submission")
        submission = HistoricalSubmission.objects.create(
            contest_id=contest.id, developer_id=developer.id
        )

        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        # 되돌린다 — #270 이전으로.
        executor.loader.build_graph()
        executor.migrate([("submissions", "0011_merge_screenshot_kind_and_destroyed_at")])
        executor.loader.build_graph()

        restored_state = executor.loader.project_state(
            ("submissions", "0011_merge_screenshot_kind_and_destroyed_at")
        )
        RestoredSubmission = restored_state.apps.get_model("submissions", "Submission")
        restored = RestoredSubmission.objects.get(pk=submission.id)
        assert restored.contest_id == contest.id
        assert restored.developer_id == developer.id

        # 다시 전진시켜 스위트의 나머지가 최신 스키마를 기대한 상태로 끝나게
        # 한다 — django_test_case가 트랜잭션을 롤백해 데이터는 정리하지만
        # 스키마(마이그레이션 상태)는 프로세스 전역이다.
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
