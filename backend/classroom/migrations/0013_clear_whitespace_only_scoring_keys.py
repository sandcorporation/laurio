# 공백만 든 채점 키를 비우고, 그 클래스의 키 상태를 키가 없는 클래스와
# 같게 맞춘다 (#435, spec #432).
#
# `classroom.api.set_class_openai_key`는 저장 전에 앞뒤 공백을 지우고
# 빈 값이면 422로 거절하므로, 그 경로로는 공백만 남은 키가 애초에
# 생기지 않는다. 그래도 이 검증이 없던 시절의 데이터나 손으로(관리
# 명령·직접 조작) 만든 데이터가 남아 있을 수 있다 — 그 행이 남아 있으면
# `Class.has_scoring_key()`는 이미 "키 없음"으로 보지만(그 메서드가
# `.strip()`으로 판정한다), 채점 스캔의 후보 쿼리(`classroom.pending_scoring
# .pending_submissions`)는 `openai_api_key_encrypted=""`(정확히 빈 문자열)
# 만 걸러내 그 클래스의 시도가 tick마다 후보로 올라와 매번 "키 없음"으로
# 끝나며 헛돈다. 이 마이그레이션이 그 어긋남을 실제 데이터에서 없앤다.
#
# 되돌리기는 없다(`RunPython.noop`) — 지우는 값이 애초에 공백뿐이라
# 복원할 실제 키가 없다.
from __future__ import annotations

from django.db import migrations


def _clear_whitespace_only_keys(apps, schema_editor):
    Class = apps.get_model("classroom", "Class")
    for row in Class.objects.exclude(openai_api_key_encrypted="").iterator():
        if row.openai_api_key_encrypted.strip():
            continue
        row.openai_api_key_encrypted = ""
        row.openai_api_key_last4 = ""
        # "unverified"는 `Class.ScoringKeyStatus.UNVERIFIED`의 값이자 키가
        # 없는 새 클래스의 기본값이다 — 이 필드가 이력 모델에는 없어 문자열
        # 그대로 쓴다.
        row.openai_api_key_status = "unverified"
        row.save(
            update_fields=[
                "openai_api_key_encrypted",
                "openai_api_key_last4",
                "openai_api_key_status",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("classroom", "0012_syntax_check_toggle"),
    ]

    operations = [
        migrations.RunPython(_clear_whitespace_only_keys, migrations.RunPython.noop),
    ]
