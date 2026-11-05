# ROLLING-DEPLOY-SAFE: `required` 는 상태(state)에서만 지운다 — DB 칸은 그대로 두고 DB 기본값(true)만 달아 새 코드의 INSERT 가 그 칸을 빼먹어도 되게 한다. 옛 코드는 칸이 남아 있어 그대로 읽고 쓴다. 겹쳐 바꾸는 몇 초 동안 새 코드가 만든 선택 항목은 옛 코드에게 필수로 보이고, 옛 코드가 만든 항목은 grade 의 DB 기본값(필수)·points 의 DB 기본값(1)으로 들어간다(ADR-0073). 실제 DROP 은 다음 배포의 contract 마이그레이션 몫이다.

from django.db import migrations, models

from core.quality_review import fingerprint_of_pairs

_MODELS = ("checklistitem", "problemtemplatechecklistitem", "classtemplateproblemchecklistitem")
_MODEL_NAMES = ("ChecklistItem", "ProblemTemplateChecklistItem", "ClassTemplateProblemChecklistItem")


def fill_grade_and_points(apps, schema_editor):
    """required=True → 필수·배점 2, False → 선택·배점 1(기존 가중치 그대로 — 순위가 바뀌지 않는다)."""

    for name in _MODEL_NAMES:
        model = apps.get_model("classroom", name)
        model.objects.filter(required=True).update(grade="required", points=2)
        model.objects.filter(required=False).update(grade="optional", points=1)


def refingerprint_quality_reviews(apps, schema_editor):
    """완성도 기록의 지문을 새 정의(AI 대상 항목의 id·라벨, ADR-0073)로 다시 센다 — 그대로 두면 지금의 기록을
    찾지 못해 강사가 다시 돈을 내고 채점해야 한다. 기록의 항목 스냅샷(id·라벨)에서 세므로 지금 체크리스트와
    같았던 기록만 다시 「지금의 기록」이 된다. append-only 행이라 `save()` 를 거치지 않고 update 로 쓴다."""

    review = apps.get_model("classroom", "ClassroomQualityReview")
    for row in review.objects.only("id", "items").iterator():
        fingerprint = fingerprint_of_pairs([(item["item_id"], item["label"]) for item in row.items])
        review.objects.filter(id=row.id).update(checklist_fingerprint=fingerprint)


class Migration(migrations.Migration):
    """체크리스트 `required` bool → `grade`(필수·선택·가산) 하나, 배점 `points` 1~10(#904, ADR-0073)."""

    dependencies = [
        ("classroom", "0036_quality_review"),
    ]

    operations = [
        *[
            migrations.AddField(
                model_name=model_name,
                name="grade",
                field=models.CharField(
                    choices=[("required", "필수"), ("optional", "선택"), ("bonus", "가산")],
                    db_default="required",
                    default="required",
                    max_length=16,
                ),
            )
            for model_name in _MODELS
        ],
        *[
            migrations.AddField(
                model_name=model_name,
                name="points",
                field=models.PositiveSmallIntegerField(db_default=1),
            )
            for model_name in _MODELS
        ],
        migrations.RunPython(fill_grade_and_points, migrations.RunPython.noop),
        migrations.RunPython(refingerprint_quality_reviews, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.AlterField(
                    model_name=model_name,
                    name="required",
                    field=models.BooleanField(db_default=True, default=True),
                )
                for model_name in _MODELS
            ],
            state_operations=[migrations.RemoveField(model_name=model_name, name="required") for model_name in _MODELS],
        ),
        *[
            migrations.AddConstraint(
                model_name=model_name,
                constraint=models.CheckConstraint(
                    condition=models.Q(points__gte=1, points__lte=10), name=f"classroom_{model_name}_points_range"
                ),
            )
            for model_name in _MODELS
        ],
    ]
