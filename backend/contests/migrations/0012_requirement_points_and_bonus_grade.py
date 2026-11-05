# ROLLING-DEPLOY-SAFE: grade 의 AlterField 는 choices(가산 값)만 넓힌다 — DB 칸·제약은 그대로다. points 는 DB 기본값(1)을 달고 더해 옛 코드의 INSERT 가 빼먹어도 된다(겹쳐 바꾸는 몇 초 동안 옛 코드가 만든 필수 항목은 배점 1로 들어간다, ADR-0073).

from django.db import migrations, models


def fill_points(apps, schema_editor):
    """기존 항목을 필수 2·선택 1 로 채운다 — 지금 가중치 그대로라 완성도 순위가 바뀌지 않는다(ADR-0073)."""

    requirement = apps.get_model("contests", "Requirement")
    requirement.objects.filter(grade="required").update(points=2)
    requirement.objects.exclude(grade="required").update(points=1)


class Migration(migrations.Migration):
    """공모전 Requirement 에 가산 등급 값과 배점 `points` 1~10(#904, ADR-0073)."""

    dependencies = [
        ("contests", "0011_contest_archived_at_and_connected_app_writes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="requirement",
            name="grade",
            field=models.CharField(
                choices=[("required", "필수"), ("optional", "선택"), ("bonus", "가산")], max_length=16
            ),
        ),
        migrations.AddField(
            model_name="requirement",
            name="points",
            field=models.PositiveSmallIntegerField(db_default=1),
        ),
        migrations.RunPython(fill_points, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="requirement",
            constraint=models.CheckConstraint(
                condition=models.Q(points__gte=1, points__lte=10), name="contests_requirement_points_range"
            ),
        ),
    ]
