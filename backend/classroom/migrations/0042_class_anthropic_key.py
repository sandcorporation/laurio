"""Claude(Anthropic) 키를 OpenAI 키 칸에서 따로 떼어 낸다(#1269).

예전(#795, ADR-0066)에는 「Claude(Anthropic) 키」 연결이 OpenAI 키 칸(`openai_api_key_*`)을 같이 썼다.
이 마이그레이션은 Claude 칸 셋을 더하고, 지금 `anthropic_key` 연결인 클래스의 키를 그 칸으로 옮긴다 —
배포 직후에도 같은 키·같은 벤더로 채점된다. `openai_key`·`compatible_server` 연결은 그대로다.

되돌리면 `anthropic_key` 연결인 클래스의 Claude 키를 OpenAI 칸으로 돌려놓는다. 그때 쉬고 있던 Claude 키
(OpenAI 로 채점하던 클래스의 것)는 옛 모양에 둘 자리가 없어 사라진다.
"""

from django.db import migrations, models

ANTHROPIC_KEY = "anthropic_key"
UNVERIFIED = "unverified"


def _move_claude_keys(apps, schema_editor):
    Class = apps.get_model("classroom", "Class")
    for class_obj in Class.objects.filter(scoring_connection_kind=ANTHROPIC_KEY):
        class_obj.anthropic_api_key_encrypted = class_obj.openai_api_key_encrypted
        class_obj.anthropic_api_key_last4 = class_obj.openai_api_key_last4
        class_obj.anthropic_api_key_status = class_obj.openai_api_key_status
        class_obj.openai_api_key_encrypted = ""
        class_obj.openai_api_key_last4 = ""
        class_obj.openai_api_key_status = UNVERIFIED
        class_obj.save(
            update_fields=[
                "anthropic_api_key_encrypted",
                "anthropic_api_key_last4",
                "anthropic_api_key_status",
                "openai_api_key_encrypted",
                "openai_api_key_last4",
                "openai_api_key_status",
            ]
        )


def _move_claude_keys_back(apps, schema_editor):
    Class = apps.get_model("classroom", "Class")
    for class_obj in Class.objects.filter(scoring_connection_kind=ANTHROPIC_KEY):
        class_obj.openai_api_key_encrypted = class_obj.anthropic_api_key_encrypted
        class_obj.openai_api_key_last4 = class_obj.anthropic_api_key_last4
        class_obj.openai_api_key_status = class_obj.anthropic_api_key_status
        class_obj.save(update_fields=["openai_api_key_encrypted", "openai_api_key_last4", "openai_api_key_status"])


class Migration(migrations.Migration):
    dependencies = [
        ("classroom", "0041_classroom_agent_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="class",
            name="anthropic_api_key_encrypted",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="class",
            name="anthropic_api_key_last4",
            field=models.CharField(blank=True, db_default="", default="", max_length=4),
        ),
        migrations.AddField(
            model_name="class",
            name="anthropic_api_key_status",
            field=models.CharField(
                choices=[("verified", "확인함"), ("unverified", "미검증"), ("rejected", "거부됨")],
                db_default="unverified",
                default="unverified",
                max_length=10,
            ),
        ),
        migrations.RunPython(_move_claude_keys, _move_claude_keys_back),
    ]
