"""개최자가 무료 공모전에 「클래스에서 들여오기」를 허용한다 — 공유층 원본 읽기 자리
(#547, 부모 #546, ADR-0054).

허용 설정은 HTTP(개최·공개 중 편집)로 본다. 공유층 카탈로그(`core.contest_catalog`)는
HTTP 표면이 없는 앱 사이의 계약이라 그 함수로 직접 읽는다 — 그것을 쓰는 강의실 쪽 HTTP
시험은 #548 이 맡는다(`tests/test_github_api_adapter.py` 와 같은 종류의 예외).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Contest, ContestChange
from core.contest_catalog import contest_catalog, contest_source_changed
from tests.test_free_contest_hosting import (  # noqa: F401 — 픽스처 재사용
    CONTESTS_URL,
    _auth_header,
    _free_brief,
    _grant,
    _hosted_user,
    _operator_client,
    category,
    landing_type,
)

pytestmark = pytest.mark.django_db


def _host(client, uid="cls-host-1"):
    user = _hosted_user(client, uid)
    _grant(_operator_client(f"root-{uid}"), user["user_id"])
    return user


def _free_contest(client, user, category, landing_type, *, allow=True, publish=True, **brief):
    payload = _free_brief(category, landing_type, **brief)
    payload["requirements"] = [
        {"text": "할 일을 추가할 수 있다", "grade": "required"},
        {"text": "할 일을 완료로 표시할 수 있다", "grade": "optional"},
    ]
    payload["allows_classroom_import"] = allow
    created = client.post(
        f"{CONTESTS_URL}/free", data=payload, content_type="application/json", **_auth_header(user["access"])
    )
    assert created.status_code == 200, created.content
    contest = created.json()
    if publish:
        published = client.post(
            f"{CONTESTS_URL}/{contest['id']}/publish",
            content_type="application/json",
            **_auth_header(user["access"]),
        )
        assert published.status_code == 200, published.content
        contest = published.json()
    return contest


def _patch(client, user, contest_id, **fields):
    return client.patch(
        f"{CONTESTS_URL}/{contest_id}",
        data=fields,
        content_type="application/json",
        **_auth_header(user["access"]),
    )


@pytest.fixture
def source_changes():
    received: list[int] = []

    def receiver(sender, contest_id, **kwargs):
        received.append(contest_id)

    contest_source_changed.connect(receiver, weak=False, dispatch_uid="test-source-changes")
    yield received
    contest_source_changed.disconnect(dispatch_uid="test-source-changes")


# --- 허용 설정 ------------------------------------------------------------------


def test_host_allows_classroom_import_when_opening_a_free_contest(client, category, landing_type):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type, allow=True)

    assert contest["allows_classroom_import"] is True
    assert client.get(f"{CONTESTS_URL}/{contest['id']}").json()["allows_classroom_import"] is True


def test_allowance_defaults_to_off(client, category, landing_type):
    user = _host(client)
    payload = _free_brief(category, landing_type)
    created = client.post(
        f"{CONTESTS_URL}/free", data=payload, content_type="application/json", **_auth_header(user["access"])
    )

    assert created.json()["allows_classroom_import"] is False


def test_host_toggles_the_allowance_while_published_without_telling_participants(
    client, category, landing_type, source_changes, django_capture_on_commit_callbacks
):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type, allow=False)

    with django_capture_on_commit_callbacks(execute=True):
        response = _patch(client, user, contest["id"], allows_classroom_import=True)

    assert response.status_code == 200, response.content
    assert response.json()["allows_classroom_import"] is True
    # 강사에게 여는 문이지 참가 조건이 아니다 — 변경 이력·참가자 알림이 없다.
    assert not ContestChange.objects.filter(contest_id=contest["id"]).exists()
    # 이미 들여온 공모전 문제는 알아야 한다.
    assert source_changes == [contest["id"]]


def test_a_paid_contest_cannot_allow_classroom_import(client, category, landing_type):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type, publish=False)
    Contest.objects.filter(pk=contest["id"]).update(is_free=False)

    response = _patch(client, user, contest["id"], allows_classroom_import=True)

    assert response.status_code == 422


# --- 바뀌었다 신호 ----------------------------------------------------------------


def test_editing_a_published_free_contest_announces_the_change(
    client, category, landing_type, source_changes, django_capture_on_commit_callbacks
):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type)

    with django_capture_on_commit_callbacks(execute=True):
        _patch(client, user, contest["id"], title="고친 제목")
    with django_capture_on_commit_callbacks(execute=True):
        added = client.post(
            f"{CONTESTS_URL}/{contest['id']}/requirements",
            data={"text": "할 일을 지울 수 있다", "grade": "required"},
            content_type="application/json",
            **_auth_header(user["access"]),
        )
    assert added.status_code == 200, added.content

    assert source_changes == [contest["id"], contest["id"]]


def test_editing_a_draft_announces_nothing(
    client, category, landing_type, source_changes, django_capture_on_commit_callbacks
):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type, publish=False)

    with django_capture_on_commit_callbacks(execute=True):
        _patch(client, user, contest["id"], title="초안 제목", allows_classroom_import=False)

    assert source_changes == []


# --- 공유층 카탈로그 ---------------------------------------------------------------


def test_catalog_lists_only_open_allowed_free_contests(client, category, landing_type):
    user = _host(client)
    allowed = _free_contest(client, user, category, landing_type, title="허용")
    _free_contest(client, user, category, landing_type, title="허용 안 함", allow=False)
    _free_contest(client, user, category, landing_type, title="초안", publish=False)
    closed = _free_contest(client, user, category, landing_type, title="마감")
    Contest.objects.filter(pk=closed["id"]).update(deadline_at=timezone.now() - timedelta(minutes=1))

    listed = contest_catalog().list_importable()

    assert [c.contest_id for c in listed] == [allowed["id"]]
    assert listed[0].title == "허용"
    assert listed[0].requirement_count == 2


def test_catalog_reads_the_source_with_requirements_in_order(client, category, landing_type):
    user = _host(client)
    contest = _free_contest(client, user, category, landing_type)

    source = contest_catalog().get_source(contest["id"])

    assert source is not None
    assert source.title == contest["title"]
    assert source.accepts_classroom_entries is True
    assert [(r.text, r.grade) for r in source.requirements] == [
        ("할 일을 추가할 수 있다", "required"),
        ("할 일을 완료로 표시할 수 있다", "optional"),
    ]


def test_source_stays_readable_after_close_but_stops_accepting_entries(client, category, landing_type):
    """마감되거나 허용을 거두면 공모전 문제는 평범한 문제로 남는다 — 원본은 계속 읽히고
    「공모전에도 내기」만 닫힌다."""

    user = _host(client)
    contest = _free_contest(client, user, category, landing_type)
    Contest.objects.filter(pk=contest["id"]).update(deadline_at=timezone.now() - timedelta(minutes=1))

    source = contest_catalog().get_source(contest["id"])

    assert source is not None
    assert source.accepts_classroom_entries is False


def test_catalog_does_not_expose_drafts_or_paid_contests(client, category, landing_type):
    user = _host(client)
    draft = _free_contest(client, user, category, landing_type, publish=False)
    paid = _free_contest(client, user, category, landing_type)
    Contest.objects.filter(pk=paid["id"]).update(is_free=False)

    assert contest_catalog().get_source(draft["id"]) is None
    assert contest_catalog().get_source(paid["id"]) is None
    assert contest_catalog().get_source(999_999) is None
