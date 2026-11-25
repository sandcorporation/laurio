"""채점 연결이 바뀌면 열어 둔 클래스 상세가 다시 읽는다 — `instructors-changed` 신호 (#1532 ②).

키 넣기·지우기·벤더 바꾸기·호환 서버 저장은 모두 그 클래스 강사(소유자·공동 강사)에게 같은 신호를 올린다. 본문은
`class_id` 와 변경 번호 `rev` 뿐이다 — 키 값·마스킹도 싣지 않는다. 준비는 마운트된 HTTP API, 신호는 fake 이벤트 버스로 본다.
"""

from __future__ import annotations

import json

import pytest

from core.events import FakeEventBus
from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    auth_header,
    create_class,
    login,
    put_compatible_server,
    set_anthropic_key,
    set_key,
    switch_scoring_vendor,
    user_id,
)

INSTRUCTORS_CHANGED = "instructors-changed"
SECRET = "sk-secret-signal-7f2a"


def _signals(uid: str) -> list:
    return [e for e in FakeEventBus._queues.get(user_id(uid), []) if e.kind == INSTRUCTORS_CHANGED]


def _scene(client):
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    class_id = create_class(client, owner["access"], with_key=False)
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    FakeEventBus._queues.clear()
    return owner, co, class_id


def _delete(client, access, class_id, path):
    response = client.delete(f"{CLASSES_URL}/{class_id}/{path}", **auth_header(access))
    assert response.status_code == 200, response.content


def _assert_signalled(owner, co, class_id, action):
    for uid in ("owner", "co"):
        events = _signals(uid)
        assert len(events) == 1, f"{action}: {uid} 에게 신호가 {len(events)}개"
        assert set(events[0].payload) == {"class_id", "rev"}
        assert events[0].payload["class_id"] == class_id
        assert SECRET not in json.dumps(events[0].payload)


@pytest.mark.django_db
def test_openai_key_save_signals(client, django_capture_on_commit_callbacks):
    owner, co, class_id = _scene(client)
    with django_capture_on_commit_callbacks(execute=True):
        set_key(client, owner["access"], class_id, SECRET)
    _assert_signalled(owner, co, class_id, "키 넣기")


@pytest.mark.django_db
def test_openai_key_delete_signals(client, django_capture_on_commit_callbacks):
    owner, co, class_id = _scene(client)
    set_key(client, owner["access"], class_id, SECRET)
    FakeEventBus._queues.clear()
    with django_capture_on_commit_callbacks(execute=True):
        _delete(client, owner["access"], class_id, "openai-key")
    _assert_signalled(owner, co, class_id, "키 지우기")


@pytest.mark.django_db
def test_anthropic_key_save_and_delete_signal(client, django_capture_on_commit_callbacks):
    owner, co, class_id = _scene(client)
    with django_capture_on_commit_callbacks(execute=True):
        assert set_anthropic_key(client, owner["access"], class_id, SECRET).status_code == 200
    _assert_signalled(owner, co, class_id, "Claude 키 넣기")
    FakeEventBus._queues.clear()
    with django_capture_on_commit_callbacks(execute=True):
        _delete(client, owner["access"], class_id, "anthropic-key")
    _assert_signalled(owner, co, class_id, "Claude 키 지우기")


@pytest.mark.django_db
def test_vendor_switch_signals(client, django_capture_on_commit_callbacks):
    owner, co, class_id = _scene(client)
    set_key(client, owner["access"], class_id, SECRET)
    assert set_anthropic_key(client, owner["access"], class_id, SECRET + "-a").status_code == 200
    FakeEventBus._queues.clear()
    with django_capture_on_commit_callbacks(execute=True):
        switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")
    _assert_signalled(owner, co, class_id, "연결 종류 바꾸기")


@pytest.mark.django_db
def test_compatible_server_save_signals(client, django_capture_on_commit_callbacks):
    owner, co, class_id = _scene(client)
    with django_capture_on_commit_callbacks(execute=True):
        response = put_compatible_server(client, owner["access"], class_id, "https://llm.example.com/v1", SECRET)
    assert response.status_code == 200, response.content
    _assert_signalled(owner, co, class_id, "호환 서버")
