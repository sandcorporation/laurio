"""내부 인증 스케줄러 틱 엔드포인트 (티켓 02, ADR-0003).

이 프로젝트의 유일한 테스트 시임은 HTTP다. `ScheduledStateDemo` 를 ORM으로 직접
만드는 것은 "미리 그런 상태였다"는 픽스처 준비일 뿐이고(test_admin.py가 유저를
create_superuser 로 만드는 것과 같은 성격), 실제로 검증하는 동작 — 전이가 일어나는지,
두 번 쏴도 한 번만 통과하는지 — 은 전부 `POST /api/internal/tick` 을 통해서만 확인한다.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from core.models import ClockOverride, ScheduledStateDemo

TICK_URL = "/api/internal/tick"


def _auth_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


@pytest.mark.django_db
def test_tick_rejects_request_without_internal_auth(client):
    response = client.post(TICK_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_tick_rejects_wrong_token(client):
    response = client.post(TICK_URL, **{"HTTP_X_INTERNAL_TOKEN": "wrong-token"})

    assert response.status_code == 401


@pytest.mark.django_db
def test_tick_transitions_due_row_and_leaves_future_row_alone(client):
    now = timezone.now()
    _freeze(now)

    due = ScheduledStateDemo.objects.create(due_at=now - timedelta(minutes=1))
    not_due = ScheduledStateDemo.objects.create(due_at=now + timedelta(hours=1))

    response = client.post(TICK_URL, **_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["transitioned"] == [
        {
            "model": "ScheduledStateDemo",
            "pk": due.pk,
            "from_state": "pending",
            "to_state": "done",
        }
    ]

    due.refresh_from_db()
    not_due.refresh_from_db()
    assert due.state == ScheduledStateDemo.State.DONE
    assert not_due.state == ScheduledStateDemo.State.PENDING


@pytest.mark.django_db
def test_firing_tick_twice_runs_the_same_transition_only_once(client):
    now = timezone.now()
    _freeze(now)
    due = ScheduledStateDemo.objects.create(due_at=now - timedelta(minutes=1))

    first = client.post(TICK_URL, **_auth_headers())
    second = client.post(TICK_URL, **_auth_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["count"] == 1
    assert second.json()["count"] == 0
    assert second.json()["transitioned"] == []

    due.refresh_from_db()
    assert due.state == ScheduledStateDemo.State.DONE


@pytest.mark.django_db
def test_clock_can_be_fixed_and_advanced_by_tests(client):
    """테스트가 시각을 고정하고 임의로 전진시킬 수 있어야 한다는 AC를 직접 증명한다."""

    base = timezone.now().replace(microsecond=0)
    _freeze(base)
    due_soon = ScheduledStateDemo.objects.create(due_at=base + timedelta(minutes=30))

    # 아직 전이 시각 전이므로 틱을 쏴도 아무 일도 없다.
    response = client.post(TICK_URL, **_auth_headers())
    assert response.json()["count"] == 0
    due_soon.refresh_from_db()
    assert due_soon.state == ScheduledStateDemo.State.PENDING

    # 시각을 임의로 전진시킨다.
    _freeze(base + timedelta(hours=1))

    response = client.post(TICK_URL, **_auth_headers())
    assert response.json()["count"] == 1
    due_soon.refresh_from_db()
    assert due_soon.state == ScheduledStateDemo.State.DONE


@pytest.mark.django_db
def test_tick_transition_refreshes_auto_now_field_using_injected_clock(client):
    """claim_transition 은 QuerySet.update() 라서 auto_now 필드를 자동으로 못 채운다.

    이 메커니즘을 재사용하는 모든 실제 모델(#11/#13/#16)이 같은 문제를 겪지
    않으려면 claim_transition 자체가 auto_now 필드를 주입된 시각으로 채워야 한다.
    """

    base = timezone.now().replace(microsecond=0)
    _freeze(base)
    due = ScheduledStateDemo.objects.create(due_at=base - timedelta(minutes=1))
    original_updated_at = due.updated_at

    frozen_tick_time = base + timedelta(seconds=5)
    _freeze(frozen_tick_time)

    response = client.post(TICK_URL, **_auth_headers())
    assert response.json()["count"] == 1

    due.refresh_from_db()
    assert due.updated_at != original_updated_at
    assert due.updated_at == frozen_tick_time
