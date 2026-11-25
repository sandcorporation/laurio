"""「채점 연결 없음」 알림 — 연결이 없어 참여자의 시도가 멈추면 소유자에게 한 번 (#1389).

준비는 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`). 확인은 알림 API(`/api/notifications/me`·`unread-count`)와
기록 표를 읽는다 — 기록은 「한 번」의 장치라 직접 본다. 경합은 `transaction=True` 와 스레드로 진짜 동시 호출을
만든다(`test_classroom_ownership_transfer.py` 의 선례). 판정 지점(`_has_participant_awaiting`)에 장벽을 꽂아 두 스레드가
둘 다 「알릴 조건이 참」을 본 뒤에 쓰게 만든다 — `Class` 잠금이 있으면 둘째는 잠금에서 기다리므로 장벽은 시간이 지나
깨지고 첫째가 먼저 끝낸다.
"""

from __future__ import annotations

import threading

import pytest
from django.db import IntegrityError, connections, transaction
from django.test import Client
from django.utils import timezone

from classroom import scoring_key_missing
from classroom.models import ClassScoringKeyMissingAlert
from notifications.models import CLASSROOM_NOTIFICATION_TYPES, Notification, NotificationDispatch, NotificationType
from tests.classroom_scenarios import (
    CLASSES_URL,
    FakeCompatibleServer,
    accept_ownership_transfer,
    add_co_instructor,
    archive_class,
    auth_header,
    co_instructor_id_of,
    create_class,
    create_open_problem,
    internal_headers,
    join_class,
    login,
    request_ownership_transfer,
    set_anthropic_key,
    set_compatible_server,
    set_key,
    submit_repository,
    switch_scoring_vendor,
    transfer_ownership,
    user_id,
)

MISSING = NotificationType.CLASSROOM_SCORING_KEY_MISSING
SCAN_URL = f"/api/internal/scans/{scoring_key_missing.SCAN_NAME}"
#: 경합 시험의 스레드 하나가 넘지 말아야 할 시간(초) — 넘으면 교착으로 본다.
THREAD_DEADLINE = 10.0


# --- 준비 ---------------------------------------------------------------------------------


def _keyless_class(client, *, participants: tuple[str, ...] = ("participant-1",)) -> dict:
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], with_key=False)
    problem = create_open_problem(client, owner["access"], class_id)
    accesses = {}
    for uid in participants:
        accesses[uid] = login(client, uid)["access"]
        join_class(client, accesses[uid], class_id, instructor_access=owner["access"], display_name=uid)
    return {"owner": owner, "class_id": class_id, "problem_id": problem.id, "participants": accesses}


def _submit(client, access: str, ctx: dict, capture=None) -> dict:
    """제출 — `capture` 가 있으면 커밋 콜백(즉시 채점·「연결 없음」 알림)을 실제로 돌린다."""

    if capture is None:
        return submit_repository(client, access, ctx["class_id"], ctx["problem_id"])
    with capture(execute=True):
        return submit_repository(client, access, ctx["class_id"], ctx["problem_id"])


def _scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _alerts(class_id: int):
    return Notification.objects.filter(notification_type=MISSING, context__class_id=class_id)


def _records(class_id: int):
    return ClassScoringKeyMissingAlert.objects.filter(classroom_id=class_id)


def _open_records(class_id: int):
    return _records(class_id).filter(closed_at__isnull=True)


def _my_missing_rows(client, access: str) -> list[dict]:
    response = client.get("/api/notifications/me?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return [row for row in response.json()["items"] if row["notification_type"] == MISSING]


def _unread(client, access: str, *, classroom_only: bool) -> int:
    flag = "true" if classroom_only else "false"
    response = client.get(f"/api/notifications/unread-count?classroom_only={flag}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["count"]


def _delete_key(client, access: str, class_id: int, vendor: str = "openai") -> None:
    response = client.delete(f"{CLASSES_URL}/{class_id}/{vendor}-key", **auth_header(access))
    assert response.status_code == 200, response.content


# --- 단위: 조건(D1~D3) -------------------------------------------------------------------


def test_participant_attempt_in_a_keyless_class_alerts_the_owner_once(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _keyless_class(client)

    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)
    _scan(client)

    rows = _my_missing_rows(client, ctx["owner"]["access"])
    assert len(rows) == 1
    assert rows[0]["context"] == {"class_id": ctx["class_id"], "class_name": "웹 스터디"}
    record = _open_records(ctx["class_id"]).get()
    assert record.recipient_id == user_id("owner")
    assert record.notification_id == _alerts(ctx["class_id"]).get().id


def test_alert_carries_only_the_class_id_and_name(client, db, django_capture_on_commit_callbacks):
    """학생 이름·소스·요구사항 원문을 싣지 않는다."""

    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)

    assert set(_alerts(ctx["class_id"]).get().context) == {"class_id", "class_name"}


def test_class_with_a_key_gets_no_missing_alert(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_class(client)
    set_key(client, ctx["owner"]["access"], ctx["class_id"])

    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)
    _scan(client)

    assert not _alerts(ctx["class_id"]).exists()
    assert not _records(ctx["class_id"]).exists()


def test_keyless_class_without_awaiting_participant_attempts_gets_no_alert(client, db):
    ctx = _keyless_class(client)

    _scan(client)

    assert scoring_key_missing.alert_missing_key(ctx["class_id"]) is False
    assert not _alerts(ctx["class_id"]).exists()


def test_owner_and_co_instructor_own_attempts_do_not_alert(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_class(client, participants=())
    owner = ctx["owner"]
    co = login(client, "co")
    add_co_instructor(client, owner["access"], ctx["class_id"], co["access"])
    # 강사도 자기 클래스에 들어와 낼 수 있다 — 문제 점검용이다.
    join_class(client, owner["access"], ctx["class_id"], instructor_access=owner["access"], display_name="강사")
    join_class(client, co["access"], ctx["class_id"], instructor_access=owner["access"], display_name="공동")

    _submit(client, owner["access"], ctx, django_capture_on_commit_callbacks)
    _submit(client, co["access"], ctx, django_capture_on_commit_callbacks)
    _scan(client)

    assert not _alerts(ctx["class_id"]).exists()


def test_co_instructor_never_receives_the_alert(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_class(client)
    co = login(client, "co")
    add_co_instructor(client, ctx["owner"]["access"], ctx["class_id"], co["access"])

    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)

    assert len(_my_missing_rows(client, ctx["owner"]["access"])) == 1
    assert _my_missing_rows(client, co["access"]) == []


def test_archived_class_is_not_alerted(client, db):
    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx)  # 콜백 없이 — 대기 시도만 남긴다
    archive_class(client, ctx["owner"]["access"], ctx["class_id"])

    _scan(client)

    assert scoring_key_missing.alert_missing_key(ctx["class_id"]) is False
    assert not _records(ctx["class_id"]).exists()


def test_rejected_attempts_do_not_count_as_awaiting(client, db):
    from classroom.models import ClassroomScoringAttempt
    from classroom.pending_scoring import rejection_error

    ctx = _keyless_class(client)
    submitted = _submit(client, ctx["participants"]["participant-1"], ctx)
    # 반려는 채점 경로만 남긴다 — 연결 없는 클래스에서 그 기록을 만드는 HTTP 길이 없어 기록 한 줄로 그 상태를 만든다.
    ClassroomScoringAttempt.objects.create(
        submission_id=submitted["id"], error=rejection_error(source_chars=10, limit_chars=1)
    )

    _scan(client)

    assert not _alerts(ctx["class_id"]).exists()


# --- 단위: 유형 플래그 -------------------------------------------------------------------


def test_type_is_internal_only_and_counted_by_the_classroom_bell(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)

    notification = _alerts(ctx["class_id"]).get()
    assert notification.status == Notification.Status.NOT_DISPATCHED
    assert not NotificationDispatch.objects.filter(notification=notification).exists()
    assert MISSING in CLASSROOM_NOTIFICATION_TYPES
    assert _unread(client, ctx["owner"]["access"], classroom_only=True) == 1
    assert _unread(client, ctx["owner"]["access"], classroom_only=False) == 0


# --- 단위: 리셋(D10) — `_save_scoring_connection` 다섯 호출부 -----------------------------


def _alerted(client, capture) -> dict:
    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx, capture)
    assert _open_records(ctx["class_id"]).count() == 1
    return ctx


def _closed_by_owner(class_id: int) -> bool:
    return (
        not _open_records(class_id).exists()
        and _records(class_id).filter(closed_reason=ClassScoringKeyMissingAlert.ClosedReason.OWNER).count() == 1
    )


def test_saving_an_openai_key_closes_the_record_and_a_later_stop_alerts_again(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _alerted(client, django_capture_on_commit_callbacks)

    set_key(client, ctx["owner"]["access"], ctx["class_id"])
    assert _closed_by_owner(ctx["class_id"])

    # 지금 쓰는 키를 지우면(이것도 연결이 바뀐 것) 다시 「연결 없음」 — 다음 참여자 제출이 새로 알린다.
    _delete_key(client, ctx["owner"]["access"], ctx["class_id"])
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)

    assert _alerts(ctx["class_id"]).count() == 2
    assert _open_records(ctx["class_id"]).count() == 1
    assert len(_my_missing_rows(client, ctx["owner"]["access"])) == 2


def test_saving_a_claude_key_closes_the_record(client, db, django_capture_on_commit_callbacks):
    ctx = _alerted(client, django_capture_on_commit_callbacks)

    response = set_anthropic_key(client, ctx["owner"]["access"], ctx["class_id"])
    assert response.status_code == 200, response.content

    assert _closed_by_owner(ctx["class_id"])


def test_saving_a_compatible_server_closes_the_record(client, db, monkeypatch, django_capture_on_commit_callbacks):
    ctx = _alerted(client, django_capture_on_commit_callbacks)
    FakeCompatibleServer().install(monkeypatch)

    set_compatible_server(client, ctx["owner"]["access"], ctx["class_id"], "https://llm.example.com/v1")

    assert _closed_by_owner(ctx["class_id"])


def _keyless_with_resting_claude_key(client, capture) -> dict:
    """OpenAI 키로 채점하다 Claude 키를 쉬는 쪽에 넣어 두고, 지금 쓰는 OpenAI 키를 지운 뒤 알림이 열린 클래스."""

    ctx = _keyless_class(client)
    set_key(client, ctx["owner"]["access"], ctx["class_id"])
    assert set_anthropic_key(client, ctx["owner"]["access"], ctx["class_id"]).status_code == 200
    _delete_key(client, ctx["owner"]["access"], ctx["class_id"], "openai")
    _submit(client, ctx["participants"]["participant-1"], ctx, capture)
    assert _open_records(ctx["class_id"]).count() == 1
    return ctx


def test_switching_the_vendor_closes_the_record(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_with_resting_claude_key(client, django_capture_on_commit_callbacks)

    switch_scoring_vendor(client, ctx["owner"]["access"], ctx["class_id"], "anthropic_key")

    assert _closed_by_owner(ctx["class_id"])


def test_changing_only_the_resting_key_keeps_the_record_open(client, db, django_capture_on_commit_callbacks):
    ctx = _keyless_with_resting_claude_key(client, django_capture_on_commit_callbacks)

    _delete_key(client, ctx["owner"]["access"], ctx["class_id"], "anthropic")
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)

    assert _open_records(ctx["class_id"]).count() == 1
    assert _alerts(ctx["class_id"]).count() == 1


def test_deleting_the_active_key_closes_an_open_record(client, db, django_capture_on_commit_callbacks):
    """지금 쓰는 키 삭제도 리셋이다. 키가 있는 동안에는 열린 기록이 생기지 않으므로(연결이 생기면 닫힌다) 경합으로만
    남는 그 모양을 기록 한 줄로 만들어 이 호출부가 닫는지 본다."""

    ctx = _keyless_class(client)
    set_key(client, ctx["owner"]["access"], ctx["class_id"])
    ClassScoringKeyMissingAlert.objects.create(
        classroom_id=ctx["class_id"], recipient_id=user_id("owner"), opened_at=timezone.now()
    )

    _delete_key(client, ctx["owner"]["access"], ctx["class_id"], "openai")

    assert _closed_by_owner(ctx["class_id"])


# --- 단위: 소유권 이전(D11) --------------------------------------------------------------


def test_transfer_closes_the_record_and_the_new_owner_is_alerted_once(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _alerted(client, django_capture_on_commit_callbacks)
    co = login(client, "co")
    add_co_instructor(client, ctx["owner"]["access"], ctx["class_id"], co["access"])

    transfer_ownership(client, ctx["owner"]["access"], ctx["class_id"], co["access"])
    assert (
        _records(ctx["class_id"]).get(closed_at__isnull=False).closed_reason
        == ClassScoringKeyMissingAlert.ClosedReason.TRANSFER
    )

    _scan(client)
    _scan(client)

    assert len(_my_missing_rows(client, co["access"])) == 1
    # 옛 소유자(이제 공동 강사)의 지난 줄은 그대로 남고 더 생기지 않는다.
    assert len(_my_missing_rows(client, ctx["owner"]["access"])) == 1
    assert _open_records(ctx["class_id"]).get().recipient_id == user_id("co")


# --- 제약 --------------------------------------------------------------------------------


def test_a_second_open_record_for_the_same_class_is_refused_by_the_database(
    client, db, django_capture_on_commit_callbacks
):
    ctx = _alerted(client, django_capture_on_commit_callbacks)
    first = _open_records(ctx["class_id"]).get()

    with pytest.raises(IntegrityError), transaction.atomic():
        ClassScoringKeyMissingAlert.objects.create(
            classroom_id=ctx["class_id"], recipient_id=first.recipient_id, opened_at=first.opened_at
        )


# --- 실패 주입(D5·D6) ---------------------------------------------------------------------


def test_notification_failure_leaves_neither_and_the_next_scan_alerts_once(
    client, db, monkeypatch, django_capture_on_commit_callbacks
):
    ctx = _keyless_class(client)
    real = scoring_key_missing.create_notification
    calls = {"n": 0}

    def fail_once(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Notification INSERT 실패 흉내")
        return real(**kwargs)

    monkeypatch.setattr(scoring_key_missing, "create_notification", fail_once)

    # 제출 응답은 실패하지 않는다(콜백이 예외를 삼킨다).
    _submit(client, ctx["participants"]["participant-1"], ctx, django_capture_on_commit_callbacks)
    assert not _records(ctx["class_id"]).exists()
    assert not _alerts(ctx["class_id"]).exists()

    first = _scan(client)
    assert first["failed"] == []
    assert _records(ctx["class_id"]).count() == 1
    assert _alerts(ctx["class_id"]).count() == 1

    for _ in range(3):
        _scan(client)
    assert _alerts(ctx["class_id"]).count() == 1


def test_scan_row_does_not_fail_when_the_notification_insert_fails(client, db, monkeypatch):
    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx)

    def boom(**kwargs):
        raise RuntimeError("Notification INSERT 실패 흉내")

    monkeypatch.setattr(scoring_key_missing, "create_notification", boom)
    result = _scan(client)

    assert result["failed"] == []
    assert not _records(ctx["class_id"]).exists()


def test_failure_after_the_record_insert_rolls_both_back(client, db, monkeypatch):
    ctx = _keyless_class(client)
    _submit(client, ctx["participants"]["participant-1"], ctx)
    real_save = ClassScoringKeyMissingAlert.save

    def save_then_fail(self, *args, **kwargs):
        if kwargs.get("update_fields") == ["notification"]:
            raise RuntimeError("커밋 전 실패 흉내")
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(ClassScoringKeyMissingAlert, "save", save_then_fail)

    with pytest.raises(RuntimeError):
        scoring_key_missing.alert_missing_key(ctx["class_id"])

    assert not _records(ctx["class_id"]).exists()
    assert not _alerts(ctx["class_id"]).exists()


# --- 경합 ---------------------------------------------------------------------------------


def _race(django_db_blocker, *calls) -> list:
    """`calls` 를 스레드마다 하나씩 동시에 돌린다 — 각 스레드에 시간 상한이 있다(넘으면 교착)."""

    results: list = [None] * len(calls)
    errors: list = []
    start = threading.Barrier(len(calls))

    def worker(i, call):
        try:
            with django_db_blocker.unblock():
                local = Client()
                start.wait()
                results[i] = call(local)
        except Exception as exc:  # noqa: BLE001 — 주 스레드에서 다시 던진다
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, c), daemon=True) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(THREAD_DEADLINE)
        assert not thread.is_alive(), "교착 — 스레드가 시간 상한 안에 끝나지 않았다"
    if errors:
        raise errors[0]
    return results


@pytest.fixture
def judged_together(monkeypatch):
    """부르면 두 경로가 「알릴 조건이 참」을 본 뒤에 만나게 한다 — 잠금이 없으면 둘 다 쓰고, 있으면 둘째가 잠금에서
    기다리는 동안 장벽이 시간 초과로 깨져 첫째가 먼저 끝낸다. 준비(제출 콜백)가 장벽을 미리 깨지 않게 경합 직전에
    부른다."""

    def arm() -> None:
        barrier = threading.Barrier(2)
        real = scoring_key_missing._has_participant_awaiting

        def meet(class_id):
            answer = real(class_id)
            try:
                barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            return answer

        monkeypatch.setattr(scoring_key_missing, "_has_participant_awaiting", meet)

    return arm


@pytest.mark.django_db(transaction=True)
def test_two_participants_submitting_at_once_make_one_record_and_one_alert(django_db_blocker, judged_together):
    with django_db_blocker.unblock():
        client = Client()
        ctx = _keyless_class(client, participants=("participant-1", "participant-2"))
        judged_together()

        _race(
            django_db_blocker,
            lambda c: _submit(c, ctx["participants"]["participant-1"], ctx),
            lambda c: _submit(c, ctx["participants"]["participant-2"], ctx),
        )

        assert _open_records(ctx["class_id"]).count() == 1
        assert _alerts(ctx["class_id"]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_callback_and_scan_at_once_finish_without_deadlock_and_alert_once(django_db_blocker, judged_together):
    with django_db_blocker.unblock():
        client = Client()
        ctx = _keyless_class(client)
        _submit(client, ctx["participants"]["participant-1"], ctx)
        # 위 제출의 콜백이 이미 알렸으면 경합이 아니다 — 지우고 둘이 동시에 다시 하게 한다.
        _records(ctx["class_id"]).delete()
        _alerts(ctx["class_id"]).delete()
        judged_together()

        _race(
            django_db_blocker,
            lambda c: scoring_key_missing.alert_missing_key_safely(ctx["class_id"]),
            lambda c: _scan(c),
        )

        assert _open_records(ctx["class_id"]).count() == 1
        assert _alerts(ctx["class_id"]).count() == 1


@pytest.mark.django_db(transaction=True)
def test_callback_and_connection_save_at_once_end_in_one_of_two_states(django_db_blocker):
    with django_db_blocker.unblock():
        client = Client()
        ctx = _keyless_class(client)
        _submit(client, ctx["participants"]["participant-1"], ctx)
        _records(ctx["class_id"]).delete()
        _alerts(ctx["class_id"]).delete()

        _race(
            django_db_blocker,
            lambda c: scoring_key_missing.alert_missing_key(ctx["class_id"]),
            lambda c: set_key(c, ctx["owner"]["access"], ctx["class_id"]),
        )

        state = (_records(ctx["class_id"]).count(), _alerts(ctx["class_id"]).count())
        assert state in {(0, 0), (1, 1)}
        assert not _open_records(ctx["class_id"]).exists()
        if state == (1, 1):
            assert _records(ctx["class_id"]).get().closed_reason == ClassScoringKeyMissingAlert.ClosedReason.OWNER


@pytest.mark.django_db(transaction=True)
def test_callback_and_transfer_accept_at_once_alert_the_owner_of_that_moment(django_db_blocker):
    with django_db_blocker.unblock():
        client = Client()
        ctx = _keyless_class(client)
        owner = ctx["owner"]
        co = login(client, "co")
        add_co_instructor(client, owner["access"], ctx["class_id"], co["access"])
        _submit(client, ctx["participants"]["participant-1"], ctx)
        _records(ctx["class_id"]).delete()
        _alerts(ctx["class_id"]).delete()
        transfer = request_ownership_transfer(
            client, owner["access"], ctx["class_id"], co_instructor_id_of(client, owner["access"], ctx["class_id"], "공동 강사")
        ).json()

        _race(
            django_db_blocker,
            lambda c: scoring_key_missing.alert_missing_key(ctx["class_id"]),
            lambda c: accept_ownership_transfer(c, co["access"], ctx["class_id"], transfer["id"]).status_code,
        )

        records = list(_records(ctx["class_id"]))
        alerts = list(_alerts(ctx["class_id"]))
        owner_id, co_id = user_id("owner"), user_id("co")
        assert len(alerts) == len(records) <= 1
        if alerts:
            # 알림은 그 트랜잭션 시점의 소유자에게 갔고, 기록의 받은 사람과 같다.
            assert alerts[0].recipient_id == records[0].recipient_id
            if records[0].recipient_id == owner_id:
                # 알림이 먼저 — 수락이 그 기록을 `transfer` 로 닫았다.
                assert records[0].closed_reason == ClassScoringKeyMissingAlert.ClosedReason.TRANSFER
            else:
                # 수락이 먼저 — 옛 소유자에게는 0, 새 소유자에게 열린 기록이 하나.
                assert records[0].recipient_id == co_id and records[0].closed_at is None

        # 어느 쪽이든 스캔 한 번이면 새 소유자에게 하나, 옛 소유자에게는 더 가지 않는다.
        before_owner = _alerts(ctx["class_id"]).filter(recipient_id=owner_id).count()
        _scan(client)
        assert _alerts(ctx["class_id"]).filter(recipient_id=co_id).count() == 1
        assert _alerts(ctx["class_id"]).filter(recipient_id=owner_id).count() == before_owner
