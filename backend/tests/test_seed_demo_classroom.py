"""`seed_demo_classroom` 이 알림도 심는다 (#341).

채점을 실제로 돌리지 않는 시드라 스캔(`classroom.scoring`)이 알림을 만들
기회가 없었다 — 그래서 데모 강사·참여자로 알림 화면(#304)을 열어도 늘
비어 있었다. 이 파일은 시드가 스캔과 같은 함수를 불러 같은 모양의 알림을
남기는지, 그리고 재시드·걷기가 다른 강사의 알림을 건드리지 않는지를 본다.

**이 파일은 HTTP 를 거치지 않는다.** 검증 대상이 관리 명령 자신의 행동이다 —
`tests/test_prune_e2e_junk.py`·`tests/test_seed_e2e_contests_namespace.py` 와
같은 이유로 `call_command` 를 직접 부른다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command

from classroom.models import Class
from notifications.models import Notification, NotificationType


def _instructor(email: str):
    User = get_user_model()
    return User.objects.create(email=email, username=email, is_active=True)


def _web_class(instructor) -> Class:
    return Class.objects.get(instructor=instructor, name__contains="웹 프론트엔드 스터디")


def test_seed_leaves_usage_on_the_class_for_the_settings_screen(db):
    instructor = _instructor("chain-g-usage-inst@example.test")

    call_command("seed_demo_classroom", email=instructor.email)

    assert _web_class(instructor).token_usage_total > 0


def test_seed_notifies_participant_of_each_scored_attempt(db):
    instructor = _instructor("chain-g-scored-inst@example.test")

    call_command("seed_demo_classroom", email=instructor.email)

    # 이수민(demo-classroom-1) — 1주차 두 번(미통과, 통과) + 2주차 한 번(미통과).
    participant = get_user_model().objects.get(email="demo-classroom-1@example.com")
    notifications = list(
        Notification.objects.filter(
            recipient=participant,
            notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        )
    )
    assert len(notifications) == 3

    web_class = _web_class(instructor)
    for notification in notifications:
        assert notification.context["class_id"] == web_class.id
        assert isinstance(notification.context["problem_id"], int)
        assert isinstance(notification.context["submission_id"], int)
        assert isinstance(notification.context["attempt_number"], int)
        assert notification.status == Notification.Status.NOT_DISPATCHED
        assert not notification.dispatches.exists()

    passed_flags = sorted(n.context["passed"] for n in notifications)
    assert passed_flags == [False, False, True]


def test_reseed_does_not_duplicate_notifications(db):
    instructor = _instructor("chain-g-reseed-inst@example.test")

    call_command("seed_demo_classroom", email=instructor.email)
    first_total = Notification.objects.count()
    first_scored = Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        context__class_id=_web_class(instructor).id,
    ).count()

    call_command("seed_demo_classroom", email=instructor.email)

    assert Notification.objects.count() == first_total
    assert first_scored > 0
    assert (
        Notification.objects.filter(
            notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
            context__class_id=_web_class(instructor).id,
        ).count()
        == first_scored
    )


def test_purge_only_removes_this_instructors_notifications(db):
    """걷어내는 범위는 시드 자신이 심은 것에 닫혀 있다 — 다른 강사의 알림에는
    닿지 않는다(참여자 계정은 이메일 접두어로 재사용되므로, class_id 로
    좁혀야만 이 경계가 성립한다)."""

    instructor_a = _instructor("chain-g-purge-a@example.test")
    instructor_b = _instructor("chain-g-purge-b@example.test")
    call_command("seed_demo_classroom", email=instructor_a.email)
    call_command("seed_demo_classroom", email=instructor_b.email)

    class_a = _web_class(instructor_a)
    class_b = _web_class(instructor_b)

    call_command("seed_demo_classroom", email=instructor_a.email, purge_only=True)

    assert not Notification.objects.filter(context__class_id=class_a.id).exists()
    assert Notification.objects.filter(context__class_id=class_b.id).exists()
