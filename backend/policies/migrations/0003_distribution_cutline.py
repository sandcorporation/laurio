"""배분 컷라인을 PlatformPolicy로 흡수한다 (#79, ADR-0023).

`distributions.DistributionCutline`은 이미 pk=1 단일 행 모델이었다 — 정책이
여러 테이블로 흩어지지 않도록 이 모델이 흡수한다. 스키마(필드 추가 + 상한
CheckConstraint)만이 아니라 **기존 행의 값을 옮기는 것**이 이 마이그레이션의
핵심이다: `DistributionCutline`은 admin이 있던 시절(ADR-0019 이전) 운영자가
직접 조정했을 수 있는 행이다. AddField의 기본값(60.00)만 믿고 그 값을 옮기지
않으면, 운영자가 조정해둔 컷라인이 조용히 원래대로 되돌아가 — 아무도 즉시
눈치채지 못한 채 다음 배분의 자격자 집합이 달라진다.

`copy_cutline_into_policy`가 `DistributionCutline(pk=1)`이 있으면 그 값으로
`PlatformPolicy(pk=1)`을 만들거나(없으면) 그 필드만 갱신한다(있으면) — 이미
존재하는 PlatformPolicy 행의 다른 필드(#75가 옮긴 수수료율·원천징수율)는
건드리지 않는다. `distributions`의 0003(DistributionCutline 삭제)이 이 뒤에
와야 하므로, 그쪽 마이그레이션이 이 마이그레이션에 의존한다 — 데이터를 옮기기
전에 원본 테이블이 지워지는 순서는 없다.
"""

from decimal import Decimal

from django.db import migrations, models


def copy_cutline_into_policy(apps, schema_editor):
    PlatformPolicy = apps.get_model("policies", "PlatformPolicy")
    DistributionCutline = apps.get_model("distributions", "DistributionCutline")

    try:
        cutline = DistributionCutline.objects.get(pk=1)
    except DistributionCutline.DoesNotExist:
        # 신선한 DB거나 배분이 한 번도 돌지 않아 컷라인 행이 아직 없다 — 옮길
        # 값이 없으므로 새 필드는 그냥 기본값(60.00)으로 둔다.
        return

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": cutline.minimum_percentage}
    )


def noop_reverse(apps, schema_editor):
    # 값을 되돌려 DistributionCutline에 쓰는 것은 이 마이그레이션의 책임이 아니다
    # (distributions 쪽 마이그레이션이 되돌아갈 때 테이블 자체가 다시 생긴다) —
    # 그래도 reverse가 정의돼 있어야 `migrate policies 0002`가 여기서 막히지
    # 않는다.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("policies", "0002_bounds_and_exempt_threshold_inputs"),
        ("distributions", "0002_distributionshare_result_notice_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformpolicy",
            name="distribution_cutline_percentage",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("60.00"), max_digits=5
            ),
        ),
        migrations.AddConstraint(
            model_name="platformpolicy",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    distribution_cutline_percentage__gte=Decimal("0.00")
                )
                & models.Q(distribution_cutline_percentage__lte=Decimal("100.00")),
                name="distribution_cutline_percentage_within_0_100",
            ),
        ),
        migrations.RunPython(copy_cutline_into_policy, noop_reverse),
    ]
