"""「채점 연결 없음」 알림 — 연결이 없어 참여자의 시도가 멈추면 소유자에게 한 번 알린다 (#1389).

지금 있는 채점 멈춤 알림(키 거부·크레딧 소진·서버 연결 불가·플랫폼 장애, `classroom.scoring`)은 grader 가 벤더를
부른 뒤에만 생긴다. 연결이 없는 클래스는 grader 가 후보로 잡지 않으므로(`pending_scoring.pending_submissions`)
그 길로는 알릴 수 없다 — 그래서 이 모듈이 따로 본다.

**알릴 조건**(모두 참): 클래스가 보관되지 않았고, 지금 연결이 없고(`Class.has_scoring_key()` 거짓), 참여자 시도 —
낸 사람이 지금 소유자도 공동 강사도 아닌 시도 — 가운데 채점을 기다리는 것(`pending_scoring.awaiting_score`)이
하나 이상 있다. 강사 본인 시도만 기다리면 알리지 않는다.

**「한 번」은 DB 가 지킨다.** `ClassScoringKeyMissingAlert` 는 클래스마다 열린 기록이 하나뿐이다(부분 유일 제약).
`alert_missing_key` 는 `Class` 행을 잠근 뒤 조건을 다시 보고, 열린 기록을 `get_or_create` 해 **새로 만들었을 때만**
알림 행을 만들어 잇는다 — 둘은 같은 트랜잭션이라 실패하면 둘 다 없고, 다음 계기(참여자 제출·60초 스캔)가 다시 한다.

**잠금 규칙.** 이 표를 건드리는 모든 경로는 먼저 `Class` 행을 잠그고, 알림 경로는 `Class` 말고 다른 행을 잠그지
않는다: ① `alert_missing_key`(`select_for_update`), ② 연결 저장(`classroom.api._save_scoring_connection`, `Class`
조건부 UPDATE 뒤 `close_open_alert`), ③ 소유권 이전 수락(`classroom.ownership_transfers.accept`, 공동 강사 줄 →
요청 → `Class` 뒤 `close_open_alert`), ④ 스캔 후보 조회는 잠금 없는 SELECT 이고 행마다 ①을 부른다.

판정 기준 시점은 ①이 `Class` 를 잠근 순간이다 — 받는 사람도 그 순간의 소유자(`Class.instructor`)이고 기록에 박는다.
"""

from __future__ import annotations

import logging

from django.db import models, transaction
from django.db.models import QuerySet

from core.clock import Clock
from core.scans import ScanSpec
from notifications.models import NotificationType
from notifications.services import create_notification

from .instructors import is_instructor_q
from .models import Class, ClassroomSubmission, ClassScoringKeyMissingAlert
from .pending_scoring import awaiting_score, no_scoring_key_q

logger = logging.getLogger(__name__)

SCAN_NAME = "classroom-scoring-key-missing-alerts"


def _participant_awaiting() -> QuerySet[ClassroomSubmission]:
    """참여자(지금 소유자도 공동 강사도 아닌 사람)가 낸, 채점을 기다리는 시도."""

    return awaiting_score(ClassroomSubmission.objects.all()).exclude(
        is_instructor_q(user="member__user_id", classroom="problem__classroom")
    )


def _has_participant_awaiting(class_id: int) -> bool:
    return _participant_awaiting().filter(problem__classroom_id=class_id).exists()


def alert_missing_key(class_id: int) -> bool:
    """조건이 참이고 열린 기록이 없으면 기록과 알림을 한 트랜잭션에서 만든다 — 새로 알렸으면 참.

    예외는 호출자에게 그대로 간다(트랜잭션은 롤백돼 기록도 알림도 남지 않는다). 계기 쪽은
    `alert_missing_key_safely` 를 부른다."""

    # 잠그기 전에 한 번 거른다 — 연결이 있는 클래스(대다수)의 제출마다 `Class` 를 잠그지 않게. 판정은 잠근 뒤 다시 한다.
    unlocked = Class.objects.filter(pk=class_id).first()
    if unlocked is None or unlocked.archived_at is not None or unlocked.has_scoring_key():
        return False

    with transaction.atomic():
        locked = Class.objects.select_for_update().filter(pk=class_id).first()
        if locked is None or locked.archived_at is not None or locked.has_scoring_key():
            return False
        if not _has_participant_awaiting(locked.id):
            return False
        alert, created = ClassScoringKeyMissingAlert.objects.get_or_create(
            classroom=locked,
            closed_at=None,
            defaults={"recipient_id": locked.instructor_id, "opened_at": Clock.now()},
        )
        if not created:
            return False
        # 앱 안 전용 유형이라 `Notification` INSERT 한 번이고 밖으로 나가지 않는다. 벨 신호는 커밋 뒤에 나간다.
        notification = create_notification(
            recipient=locked.instructor,
            notification_type=NotificationType.CLASSROOM_SCORING_KEY_MISSING,
            context={"class_id": locked.id, "class_name": locked.name},
        )
        alert.notification = notification
        alert.save(update_fields=["notification"])
    return True


def alert_missing_key_safely(class_id: int) -> bool:
    """`alert_missing_key` 를 부르되 예외를 호출자에게 넘기지 않는다 — 제출 응답·스캔 행이 알림 실패로 실패하지
    않게. 예외는 트랜잭션 **밖**에서 잡으므로 기록·알림은 이미 함께 롤백됐다(다음 계기가 다시 한다)."""

    try:
        return alert_missing_key(class_id)
    except Exception:  # noqa: BLE001 — 다음 참여자 제출이나 60초 스캔이 다시 한다.
        logger.exception("「채점 연결 없음」 알림을 만들지 못했다 — 다음 계기가 다시 한다 (class_id=%s)", class_id)
        return False


def close_open_alert(class_id: int, reason: str) -> None:
    """열린 기록을 닫는다 — 다시 멈추면 새 기록·새 알림이 생긴다. **부르는 쪽이 이미 `Class` 행을 잠근
    트랜잭션 안에서** 부른다(잠금 규칙 ②·③)."""

    ClassScoringKeyMissingAlert.objects.filter(classroom_id=class_id, closed_at__isnull=True).update(
        closed_at=Clock.now(), closed_reason=reason
    )


def _candidates(as_of, ctx) -> QuerySet[Class]:
    """보관되지 않았고, 연결이 없어 보이고, 열린 기록이 없고, 참여자 대기 시도가 있는 클래스 — 잠금 없이 고른다.
    연결 유무는 ①이 잠근 뒤 다시 본다."""

    return (
        Class.objects.filter(archived_at__isnull=True)
        .filter(no_scoring_key_q())
        .exclude(models.Exists(ClassScoringKeyMissingAlert.objects.filter(classroom=models.OuterRef("pk"), closed_at__isnull=True)))
        .filter(models.Exists(_participant_awaiting().filter(problem__classroom=models.OuterRef("pk"))))
    )


def _alert_one(class_obj: Class, as_of, ctx) -> dict | None:
    if not alert_missing_key_safely(class_obj.pk):
        return None
    return {"class_id": class_obj.pk, "status": "alerted"}


#: 실패한 알림의 재시도, 배포 시점에 이미 멈춰 있던 클래스, 소유권 이전 뒤 남은 대기 시도를 맡는다.
CLASSROOM_SCORING_KEY_MISSING_SCAN = ScanSpec(
    name=SCAN_NAME,
    candidates=_candidates,
    handle_row=_alert_one,
)
