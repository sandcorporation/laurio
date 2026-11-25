# 옛 「넘기려 합니다」 알림을 그 알림을 낳은 요청에 잇는다(#1448 일부-6·②) — 데이터만 바꾼다.
# 규칙은 `classroom.transfer_notification_backfill` 머리말: 받는 사람·클래스·알림 생성 시각과 요청 생성 시각으로
# 요청 하나가 정해질 때만 잇고, 못 정하면 그대로 둔다(목록이 끝난 요청 `gone` 으로 보인다).
#
# `notifications` 쪽 마이그레이션이 아니라 여기 두는 까닭: `notifications` 는 공유층이라 `classroom` 을 읽지 못한다
# (`backend/app_deps.toml`). 칸은 그대로라 옛 코드도 이은 `context` 를 그대로 읽는다. 되돌리기는 하지 않는다 —
# 더한 `transfer_id` 는 지금 코드가 새 알림에 싣는 것과 같은 값이다.
from __future__ import annotations

from django.db import migrations


def _link(apps, schema_editor):
    from classroom.transfer_notification_backfill import link_legacy_request_notifications

    link_legacy_request_notifications(
        apps.get_model("notifications", "Notification"),
        apps.get_model("classroom", "OwnershipTransfer"),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("classroom", "0051_classroom_scoring_key_missing_alert"),
        ("notifications", "0017_classroom_member_expelled"),
    ]

    operations = [
        migrations.RunPython(_link, migrations.RunPython.noop),
    ]
