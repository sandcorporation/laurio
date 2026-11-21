"""채점 완료 알림 문구 — 무료 공모전은 이의 기간을 말하지 않고 유료는 말한다(#1182)."""

from notifications.models import Notification, NotificationType
from notifications.rendering import render_message


def _scoring_complete(**context) -> str:
    return render_message(
        Notification(notification_type=NotificationType.SCORING_COMPLETE, context={"contest_title": "공모", **context})
    )


def test_a_paid_contest_says_the_appeal_window_opens():
    assert "이의제기 기간이 시작됩니다" in _scoring_complete(is_free=False)


def test_a_free_contest_never_mentions_an_appeal_period():
    text = _scoring_complete(is_free=True)
    assert "채점이 완료됐습니다" in text
    assert "이의" not in text
