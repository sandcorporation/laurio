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

**코드리뷰 지적 반영(#79 후속)**:

1. **롤백 시 값 유실**. 옛 `restore_cutline_into_distribution_cutline`(당시
   `noop_reverse`)가 값을 되돌려 쓰지 않아, `migrate policies 0002`로
   되돌렸다가 다시 전진시키면 이미 옮겨둔 값이 사라지고
   `distribution_cutline_percentage`가 다시 기본값(60.00)이 됐다 — 이
   마이그레이션이 막으려던 바로 그 사고가 롤백 경로에 그대로 남아 있었다.
   지금은 reverse가 `PlatformPolicy(pk=1)`의 현재 값을 읽어
   `DistributionCutline(pk=1)`에 다시 써준다 — distributions 쪽 0003이 이
   RunPython보다 먼저 되돌아가(테이블이 이미 복구된 뒤이므로) 이 시점에 그
   테이블이 이미 존재한다.
2. **범위 밖 옛 값이 배포 전체를 막는다**. `DistributionCutline.minimum_percentage`
   에는 상한이 없어(`max_digits=5`라 최대 999.99까지 저장 가능) 0~100 밖의
   값이 들어 있을 수 있었다. `AddConstraint`가 `RunPython`보다 먼저 실행되므로,
   그런 값을 그대로 옮기려 하면 `PlatformPolicy`의 CheckConstraint를 어겨
   `IntegrityError`로 죽고, 그 배포의 `migrate` 전체가 원인을 알 수 없는 채로
   멈춘다. 연산 순서를 바꿔도(RunPython을 먼저 두면) 이번엔 그 값을 담은 채로
   `AddConstraint` 자체가 죽으므로 해결되지 않는다 — `copy_cutline_into_policy`가
   DB에 쓰기 전에 범위를 먼저 검증해, 막히더라도 무엇이·왜 막혔는지 말하는
   명시적인 예외로 실패하게 한다(값을 조용히 clamp하지 않는다 — 운영자가 실제로
   둔 값이 무엇이었는지 지워지는 것도 같은 성질의 사고이기 때문이다).
"""

from decimal import Decimal

from django.db import migrations, models

_MIN_CUTLINE = Decimal("0.00")
_MAX_CUTLINE = Decimal("100.00")


def copy_cutline_into_policy(apps, schema_editor):
    PlatformPolicy = apps.get_model("policies", "PlatformPolicy")
    DistributionCutline = apps.get_model("distributions", "DistributionCutline")

    try:
        cutline = DistributionCutline.objects.get(pk=1)
    except DistributionCutline.DoesNotExist:
        # 신선한 DB거나 배분이 한 번도 돌지 않아 컷라인 행이 아직 없다 — 옮길
        # 값이 없으므로 새 필드는 그냥 기본값(60.00)으로 둔다.
        return

    value = cutline.minimum_percentage
    if value < _MIN_CUTLINE or value > _MAX_CUTLINE:
        # 이 위의 AddConstraint가 이미 DB에 걸려 있으므로, 검증 없이 그대로
        # update_or_create를 시도하면 IntegrityError로 죽어 원인이 스택
        # trace 뒤에 묻힌다 — 그 전에 이 마이그레이션 자신이 무엇이 왜
        # 막혔는지 말한다.
        raise RuntimeError(
            "distributions_distributioncutline(pk=1).minimum_percentage="
            f"{value}가 0~100(%) 범위 밖이다. 옛 DistributionCutline 필드에는 "
            "이 상한이 없어 저장될 수 있었지만, PlatformPolicy."
            "distribution_cutline_percentage는 CheckConstraint로 0~100을 "
            "강제한다. 이 값을 자동으로 잘라내면(clamp) 운영자가 실제로 둔 "
            "값이 무엇이었는지 조용히 지워지므로, 배포 전에 psql이나 "
            "`manage.py shell`로 이 행의 값을 0~100 사이로 직접 고친 뒤 "
            "마이그레이션을 다시 시도하라."
        )

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": value}
    )


def restore_cutline_into_distribution_cutline(apps, schema_editor):
    """`copy_cutline_into_policy`의 반대 방향 — 롤백 시에도 값을 잃지 않는다.

    이 마이그레이션을 되돌리는 순서에서(distributions의 0003이 먼저 되돌아가
    `DistributionCutline` 테이블을 다시 만든 뒤, 이 RunPython의 reverse가
    실행된다) `PlatformPolicy(pk=1).distribution_cutline_percentage`가 이 시점
    에는 아직 존재한다 — 이 마이그레이션 안의 RemoveField/RemoveConstraint는
    연산 목록에서 이 RunPython보다 뒤에 있으므로, 되돌릴 때는 그보다 먼저
    (이 함수보다 나중에) 실행된다. 그 값을 옛 테이블에 다시 써서 "롤백하면
    운영자가 조정해둔 컷라인이 사라진다"는 사고를 반대 방향에서도 막는다.
    """

    PlatformPolicy = apps.get_model("policies", "PlatformPolicy")
    DistributionCutline = apps.get_model("distributions", "DistributionCutline")

    try:
        policy = PlatformPolicy.objects.get(pk=1)
    except PlatformPolicy.DoesNotExist:
        return

    DistributionCutline.objects.update_or_create(
        pk=1, defaults={"minimum_percentage": policy.distribution_cutline_percentage}
    )


class Migration(migrations.Migration):

    dependencies = [
        ("policies", "0004_sane_upper_bounds_for_remaining_values"),
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
        migrations.RunPython(
            copy_cutline_into_policy, restore_cutline_into_distribution_cutline
        ),
    ]
