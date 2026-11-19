"""#986 보탬 5: 무료 공모전의 「채점 완료」 알림은 이의 기간을 말하지 않는다 — 무료에는 이의 신청이 없다.

공모전 3(is_free) 알림 866~872 가 「이의제기 기간이 시작됩니다」라고 보냈다(대장 #1447).
"""

from __future__ import annotations

from notifications.models import Notification, NotificationType
from notifications.rendering import render_message


def _render(context: dict) -> str:
    return render_message(
        Notification(notification_type=NotificationType.SCORING_COMPLETE, context=context)
    )


def test_free_contest_scoring_complete_does_not_mention_appeals():
    assert _render({"contest_title": "무료 대회", "is_free": True}) == (
        "[Codemit] 제출하신 '무료 대회' Contest 채점이 완료됐습니다. codemit에서 확인하세요."
    )


def test_paid_contest_scoring_complete_keeps_the_appeal_window():
    assert _render({"contest_title": "유료 대회", "is_free": False}) == (
        "[Codemit] 제출하신 '유료 대회' Contest 채점이 완료됐습니다. "
        "이의제기 기간이 시작됩니다 — codemit에서 확인하세요."
    )


def test_notifications_made_before_the_flag_keep_the_old_wording():
    assert "이의제기 기간" in _render({"contest_title": "옛 알림"})
