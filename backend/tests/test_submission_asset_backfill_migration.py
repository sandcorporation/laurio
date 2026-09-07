"""`0003_backfill_submission_assets`가 기존 Submission의 네 컬럼을 자료로 옮기는지
확인한다 (#190, tests/test_handover_backfill_migration.py와 같은 형식).

**이 백필은 되돌릴 수 없다.** 바로 다음 마이그레이션(`0004`)이 원본 컬럼 넷을
영구히 지우므로, 백필이 한 행이라도 놓치면 그 제출작의 소스·데모·영상이 어디에도
남지 않는다. 소스가 사라진 Submission은 채점되지 않고 배분 컷라인에서 조용히
빠지며, 그 사실을 알아챌 방법이 그 시점엔 없다.

`submissions`를 `0001_initial`(백필 이전)로 되돌린 뒤 **그 시점의 과거 모델**로
행을 심고 — 지금 모델에는 그 컬럼이 없다 — 최신까지 전진시켜 `0003`의 RunPython을
실제로 통과시킨다.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from contests.models import Category, Contest


class SubmissionAssetBackfillMigrationTests(TransactionTestCase):
    def test_backfill_moves_every_legacy_column_onto_assets(self):
        executor = MigrationExecutor(connection)

        User = get_user_model()
        sponsor = SponsorProfile.objects.create(
            user=User.objects.create_user(
                username="asset-migrator-sponsor", email="asset-migrator-sponsor@example.com"
            )
        )
        category = Category.objects.create(name="자료 마이그레이션 테스트")
        contest = Contest.objects.create(
            sponsor=sponsor,
            title="다중화 이전에 제출이 있던 Contest",
            category=category,
            description="",
            prize=1_000_000,
            deadline_at=timezone.now() - timedelta(days=30),
            status=Contest.Status.CLOSED,
            required_minimum_prize=0,
            is_underfunded=False,
        )
        developers = [
            DeveloperProfile.objects.create(
                user=User.objects.create_user(
                    username=f"asset-migrator-dev-{i}", email=f"asset-migrator-dev-{i}@example.com"
                )
            )
            for i in range(3)
        ]

        # `submissions`를 백필 이전으로 되돌린다 — 그래야 네 컬럼이 다시 존재한다.
        executor.migrate([("submissions", "0001_initial")])
        executor.loader.build_graph()
        old_state = executor.loader.project_state(("submissions", "0001_initial"))
        LegacySubmission = old_state.apps.get_model("submissions", "Submission")

        # 세 갈래를 심는다: 전부 채운 제출 · 소스만 낸 제출 · 데모 없이 계정만
        # 남은 제출(옮길 곳이 없는 경우).
        full = LegacySubmission.objects.create(
            contest_id=contest.id,
            developer_id=developers[0].id,
            source_object_key="submission:1:1:source/aaa",
            demo_video_object_key="submission:1:1:demo-video/bbb",
            demo_url="https://example.invalid/full",
            test_account="full-id / full-pw",
        )
        source_only = LegacySubmission.objects.create(
            contest_id=contest.id,
            developer_id=developers[1].id,
            source_object_key="submission:1:2:source/ccc",
        )
        orphan_account = LegacySubmission.objects.create(
            contest_id=contest.id,
            developer_id=developers[2].id,
            source_object_key="submission:1:3:source/ddd",
            test_account="갈 곳 없는 계정",
        )

        # 최신까지 전진시킨다 — 0003의 RunPython과 0004의 컬럼 드롭을 실제로 통과한다.
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        from submissions.models import SubmissionAsset

        def assets_of(submission_id: int) -> dict[str, list]:
            grouped: dict[str, list] = {}
            for asset in SubmissionAsset.objects.filter(submission_id=submission_id):
                grouped.setdefault(asset.kind, []).append(asset)
            return grouped

        full_assets = assets_of(full.id)
        assert [a.value for a in full_assets["source"]] == ["submission:1:1:source/aaa"]
        assert [a.value for a in full_assets["demo_video"]] == ["submission:1:1:demo-video/bbb"]
        assert [a.value for a in full_assets["demo_url"]] == ["https://example.invalid/full"]
        # 테스트 계정은 데모 URL 자료에 붙는다 — 제출작이 아니라 그 데모의 것이다.
        assert full_assets["demo_url"][0].test_account == "full-id / full-pw"
        assert "repository" not in full_assets

        assert list(assets_of(source_only.id)) == ["source"]

        # 데모가 없으면 계정을 붙일 자료가 없다. 빈 값을 담은 데모 자료를 만들지
        # 않는다 — 그러면 공개 프로필에 열리지 않는 「데모 보기」가 뜬다. 값은
        # 버려지고 소스만 남는다.
        orphan_assets = assets_of(orphan_account.id)
        assert list(orphan_assets) == ["source"]
        assert SubmissionAsset.objects.filter(
            submission_id=orphan_account.id, test_account="갈 곳 없는 계정"
        ).count() == 0
