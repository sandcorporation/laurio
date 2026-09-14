# 제출 형식을 단일값에서 허용 목록으로 바꾼다 (#373, 부모 #371).
#
# squash(#364) 이후 처음으로 staging에 실데이터가 있는 상태에서 도는 데이터
# 마이그레이션이라 되돌리기(reverse)도 함께 적는다 — 목록의 첫 원소를 옛
# 단일 값으로 되돌린다("단일 값 → 원소 하나짜리 목록"의 역방향).
from __future__ import annotations

from django.db import migrations, models

_MODELS = ("problem", "problemtemplate", "classtemplateproblem")


def _populate_formats_list(apps, schema_editor):
    for model_name in _MODELS:
        Model = apps.get_model("classroom", model_name)
        for row in Model.objects.all().only("id", "submission_format"):
            row.submission_formats = [row.submission_format]
            row.save(update_fields=["submission_formats"])


def _populate_single_format(apps, schema_editor):
    """되돌리기 — 목록의 첫 원소를 옛 단일 값으로 되돌린다. 이 마이그레이션이
    만든 행은 언제나 원소 하나짜리 목록이지만, 그 사이 API로 여러 형식을
    고른 문제가 있었다면 첫 원소만 살아남는다(체인 노트가 정한 그대로의
    손실 있는 되돌리기 — 일상적으로 쓰는 경로가 아니라 비상용 탈출구다)."""

    for model_name in _MODELS:
        Model = apps.get_model("classroom", model_name)
        for row in Model.objects.all().only("id", "submission_formats"):
            formats = row.submission_formats or ["source"]
            row.submission_format = formats[0]
            row.save(update_fields=["submission_format"])


class Migration(migrations.Migration):

    dependencies = [
        ("classroom", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="problem",
            name="submission_formats",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="problemtemplate",
            name="submission_formats",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="classtemplateproblem",
            name="submission_formats",
            field=models.JSONField(default=list),
        ),
        migrations.RunPython(_populate_formats_list, _populate_single_format),
        # `RemoveField`의 되돌리기는 이 자리의 프로젝트 상태(`blank=True,
        # default=""`)로 옛 컬럼을 다시 만든다 — 원래 필드 정의(`blank`
        # 없음, default 없음)를 그대로 되살리면 Django가 NOT NULL 컬럼에 채울
        # 기본값을 찾지 못해(`effective_default`가 `None`을 고른다) 되돌리기가
        # `NOT NULL` 위반으로 죽는다(직접 겪음). 이 `AlterField`는 SQL을 내지
        # 않는 상태 전용 변경이다 — `blank`는 DB 제약이 아니라 폼 검증
        # 힌트라, 여기 값을 바꿔도 컬럼 자체는 그대로다. 되돌린 값(빈 문자열)은
        # 바로 다음에 도는 `_populate_single_format`이 실제 값으로 덮어쓴다.
        migrations.AlterField(
            model_name="problem",
            name="submission_format",
            field=models.CharField(
                max_length=20,
                choices=[("source", "소스"), ("repository", "저장소")],
                blank=True,
                default="",
            ),
        ),
        migrations.AlterField(
            model_name="problemtemplate",
            name="submission_format",
            field=models.CharField(
                max_length=20,
                choices=[("source", "소스"), ("repository", "저장소")],
                blank=True,
                default="",
            ),
        ),
        migrations.AlterField(
            model_name="classtemplateproblem",
            name="submission_format",
            field=models.CharField(
                max_length=20,
                choices=[("source", "소스"), ("repository", "저장소")],
                blank=True,
                default="",
            ),
        ),
        migrations.RemoveField(model_name="problem", name="submission_format"),
        migrations.RemoveField(model_name="problemtemplate", name="submission_format"),
        migrations.RemoveField(model_name="classtemplateproblem", name="submission_format"),
    ]
