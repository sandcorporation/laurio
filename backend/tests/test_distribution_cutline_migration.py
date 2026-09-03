"""0003_distribution_cutline(policies)/0003_delete_distributioncutline(distributions)
백필이, 이미 운영 중이던 컷라인 값을 잃지 않고 옮기는지 확인한다 (#79,
tests/test_handover_backfill_migration.py와 같은 형식).

`DistributionCutline`은 이미 pk=1 단일 행 모델이었고, admin이 있던 시절
(ADR-0019 이전) 운영자가 직접 값을 조정했을 수 있다. 이 마이그레이션이 그 값을
옮기지 않고 `PlatformPolicy`의 AddField 기본값(60.00)으로 그냥 두면, 운영자가
조정해둔 컷라인이 조용히 원래대로 되돌아간다 — 아무도 즉시 눈치채지 못하고,
다음 배분에서 자격자 집합이 달라진다. 이 테스트는 두 앱을 컷라인 이관 이전
상태로 되돌린 뒤, 기본값이 아닌 값(77.50%)이 든 `DistributionCutline` 행을 직접
만들고, 최신까지 전진시켜 그 값이 `PlatformPolicy.distribution_cutline_percentage`
로 실제로 옮겨지는지 — 그리고 옛 테이블 자체가 지워지는지 — 직접 확인한다.
"""

from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class DistributionCutlineMigrationTests(TransactionTestCase):
    def test_non_default_cutline_survives_the_migration_into_platform_policy(self):
        executor = MigrationExecutor(connection)

        # 두 앱을 컷라인 이관(#79) 이전 상태로 되돌린다 — distributions는 아직
        # DistributionCutline 테이블을 갖고 있고, policies는 아직
        # distribution_cutline_percentage 필드가 없다.
        executor.migrate(
            [
                ("distributions", "0002_distributionshare_result_notice_sent_at"),
                ("policies", "0002_bounds_and_exempt_threshold_inputs"),
            ]
        )
        executor.loader.build_graph()

        old_distributions_state = executor.loader.project_state(
            ("distributions", "0002_distributionshare_result_notice_sent_at")
        )
        HistoricalDistributionCutline = old_distributions_state.apps.get_model(
            "distributions", "DistributionCutline"
        )

        # 운영자가 (지금은 사라진) admin 시절 60%에서 77.50%로 조정해둔 값이라고
        # 가정한다 — 기본값이 아닌 값이어야 "옮기지 않아도 우연히 통과"하지 않는다.
        HistoricalDistributionCutline.objects.create(
            pk=1, minimum_percentage=Decimal("77.50")
        )

        # 최신 상태로 다시 전진시킨다 — policies의 0003 RunPython 백필이 이
        # 값을 실제로 옮기는지, distributions의 0003이 옛 테이블을 지우는지
        # 둘 다 통과해야 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from policies.models import PlatformPolicy

        policy = PlatformPolicy.objects.get(pk=1)
        assert policy.distribution_cutline_percentage == Decimal("77.50")

        # 옛 테이블 자체가 지워졌다 — 컷라인이 두 곳에 동시에 살아 있으면 안
        # 된다(ADR-0023 "정책값은 DB의 단일 행 하나로 모은다").
        assert "distributions_distributioncutline" not in connection.introspection.table_names()

    def test_rolling_back_and_forward_again_preserves_a_non_default_cutline(self):
        """롤백해도 값을 잃지 않는다(코드리뷰 지적 #79 후속) — `policies`의
        0003을 되돌렸다가(그러면 `distributions`의 0003도 함께 되돌아가
        `DistributionCutline` 테이블이 다시 생긴다) 다시 최신까지 전진시켜도,
        운영자가 조정해둔 값이 살아 있어야 한다.

        옛 reverse(`noop_reverse`)는 아무 것도 쓰지 않았다 — 그래서 롤백 직후
        되살아난 `DistributionCutline` 테이블은 빈 채였고, 다시 전진시키면
        `policies.scope.current_policy`의 get_or_create가 필드 기본값
        (60.00)으로 조용히 되돌아갔다. 이 테스트가 바로 그 왕복을 재현한다 —
        reverse가 값을 되돌려 쓰지 않으면 이 테스트가 빨개진다.
        """

        executor = MigrationExecutor(connection)
        executor.migrate(
            [
                ("distributions", "0002_distributionshare_result_notice_sent_at"),
                ("policies", "0002_bounds_and_exempt_threshold_inputs"),
            ]
        )
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from policies.models import PlatformPolicy

        # 운영자가 마이그레이션이 끝난 뒤 컷라인을 33.25%로 조정했다고 가정한다
        # — 기본값(60.00)이 아니어야 "롤백해도 우연히 맞아떨어졌다"가 안 된다.
        PlatformPolicy.objects.update_or_create(
            pk=1, defaults={"distribution_cutline_percentage": Decimal("33.25")}
        )

        # 두 앱을 이관 이전 상태로 되돌린다 — distributions의 0003(DeleteModel)이
        # 먼저 되돌아가 DistributionCutline 테이블을 다시 만들고, 그 다음
        # policies의 0003 RunPython의 reverse가 실행된다.
        executor.loader.build_graph()
        executor.migrate(
            [
                ("distributions", "0002_distributionshare_result_notice_sent_at"),
                ("policies", "0002_bounds_and_exempt_threshold_inputs"),
            ]
        )

        # 다시 최신까지 전진시킨다 — policies의 0003 RunPython(정방향)이 방금
        # reverse가 되돌려 쓴 DistributionCutline 값을 다시 읽어야 한다.
        executor.loader.build_graph()
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        policy = PlatformPolicy.objects.get(pk=1)
        assert policy.distribution_cutline_percentage == Decimal("33.25")

    def test_boots_with_default_cutline_when_no_prior_row_existed(self):
        """신선한 DB(DistributionCutline 행이 한 번도 만들어진 적 없음)에서도
        마이그레이션이 그냥 통과하고, 이후 첫 조회가 기본값(60.00)으로 행을
        만든다 — #79 AC "행이 없으면 기본값으로 만든다".
        """

        executor = MigrationExecutor(connection)
        executor.migrate(
            [
                ("distributions", "0002_distributionshare_result_notice_sent_at"),
                ("policies", "0002_bounds_and_exempt_threshold_inputs"),
            ]
        )
        executor.loader.build_graph()

        # DistributionCutline 행을 만들지 않은 채로 곧장 최신까지 전진시킨다.
        targets = executor.loader.graph.leaf_nodes()
        executor.migrate(targets)

        from policies.scope import current_policy

        policy = current_policy()
        assert policy.distribution_cutline_percentage == Decimal("60.00")
