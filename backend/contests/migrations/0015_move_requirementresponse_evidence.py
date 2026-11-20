"""자가 응답(`RequirementResponse`)·근거(`Evidence`)의 소속을 submissions 에서 contests 로 (#1086).

**상태만 옮긴다.** 표(`submissions_requirementresponse`·`submissions_evidence`)·제약·FK 는 그대로 두고
`db_table` 로 옛 이름을 고정한다 — `sqlmigrate` 가 SQL 0줄이다. 짝은 `submissions/0006`(옛 상태 지움).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contests", "0014_contest_require_demo_video_and_more"),
        ("submissions", "0005_submissionasset_video_link_kind"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="RequirementResponse",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("is_met", models.BooleanField(default=False)),
                        ("note", models.CharField(blank=True, max_length=1000)),
                        ("requirement", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="responses", to="contests.requirement")),
                        ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="requirement_responses", to="submissions.submission")),
                    ],
                    options={
                        "db_table": "submissions_requirementresponse",
                        "ordering": ["requirement__order", "requirement_id"],
                        "constraints": [
                            models.UniqueConstraint(fields=("submission", "requirement"), name="unique_response_per_requirement"),
                        ],
                    },
                ),
                migrations.CreateModel(
                    name="Evidence",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("kind", models.CharField(choices=[("video_timestamp", "영상 타임스탬프"), ("screenshot", "스크린샷"), ("demo_path", "데모 내 경로"), ("source_location", "소스 위치")], max_length=20)),
                        ("value", models.CharField(max_length=500)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="evidence_items", to="submissions.submissionasset")),
                        ("response", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence_items", to="contests.requirementresponse")),
                    ],
                    options={
                        "db_table": "submissions_evidence",
                        "ordering": ["id"],
                    },
                ),
            ],
        ),
    ]
