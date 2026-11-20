"""제출 때의 「채점 크기」 참고 알림(#989 B) — 저장을 막지 않고, 채점 시점의 「크기 초과」 보류와 같은 판정을 낸다.
시임은 마운트된 제출 HTTP API 와 채점 스캔 엔드포인트다."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from scoring import services
from storage.adapters.fake import FakeStorageAdapter
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    CONTESTS_URL,
    _auth_header,
    _close_contest,
    _publish_contest,
    _run_pending,
    _source_object_key,
    _verified_user,
    _zip_bytes,
    category,
    landing_type,
)
from tests.integration.test_scoring_source_hold import _MustNotBeCalled, _tiny_budget


def _open_contest(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    return contest, deadline


def _upload(contest, dev, files: dict[str, str]) -> str:
    key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(key, _zip_bytes(files))
    return key


def _submit(client, contest, dev, assets: list[dict]):
    return client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={"assets": assets, "requirement_responses": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


@pytest.mark.django_db
def test_upload_over_the_scoring_budget_is_flagged_and_scoring_later_holds_it(
    client, category, landing_type, monkeypatch
):
    contest, deadline = _open_contest(client, category, landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _tiny_budget(monkeypatch)
    key = _upload(contest, dev, {"app.py": "print('로그인 기능')\n"})

    created = _submit(client, contest, dev, [{"kind": "source", "value": key}])

    assert created.status_code == 201, created.content
    assert created.json()["scoring_size_warning"] is True
    # 참고 알림은 저장 응답에만 — 다시 열었을 때는 싣지 않는다.
    mine = client.get(f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"]))
    assert mine.json()["scoring_size_warning"] is False

    # 같은 판정 — 채점 시점에도 이 제출은 「크기 초과」 보류다.
    _close_contest(client, contest, deadline=deadline)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())
    assert _run_pending(client)["rows"][0]["status"] == "held"


@pytest.mark.django_db
def test_upload_within_the_budget_is_not_flagged_and_scoring_does_not_hold_it(
    client, category, landing_type
):
    contest, deadline = _open_contest(client, category, landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    key = _upload(contest, dev, {"app.py": "print('로그인 기능')\n"})

    created = _submit(client, contest, dev, [{"kind": "source", "value": key}])
    assert created.json()["scoring_size_warning"] is False

    updated = client.put(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me",
        data={"assets": [{"id": created.json()["assets"][0]["id"], "kind": "source", "value": key}],
              "requirement_responses": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert updated.status_code == 200, updated.content
    assert updated.json()["scoring_size_warning"] is False

    _close_contest(client, contest, deadline=deadline)
    assert _run_pending(client)["rows"][0]["status"] != "held"


@pytest.mark.django_db
def test_update_that_makes_the_upload_too_large_is_flagged(client, category, landing_type, monkeypatch):
    contest, _deadline = _open_contest(client, category, landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    small = _upload(contest, dev, {"app.py": "x\n"})
    assert _submit(client, contest, dev, [{"kind": "source", "value": small}]).json()["scoring_size_warning"] is False

    _tiny_budget(monkeypatch)
    big = _upload(contest, dev, {"app.py": "print('로그인 기능이 있는 큰 앱')\n" * 20})
    updated = client.put(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me",
        data={"assets": [{"kind": "source", "value": big}], "requirement_responses": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert updated.status_code == 200, updated.content
    assert updated.json()["scoring_size_warning"] is True


@pytest.mark.django_db
def test_agent_scoring_reads_a_single_zip_whole_so_it_is_not_flagged(
    client, category, landing_type, monkeypatch
):
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    contest, _deadline = _open_contest(client, category, landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _tiny_budget(monkeypatch)
    key = _upload(contest, dev, {"app.py": "print('로그인 기능')\n"})

    created = _submit(client, contest, dev, [{"kind": "source", "value": key}])

    assert created.status_code == 201, created.content
    assert created.json()["scoring_size_warning"] is False


@pytest.mark.django_db
def test_measuring_failure_does_not_block_the_save(client, category, landing_type, monkeypatch):
    contest, _deadline = _open_contest(client, category, landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    def broken(*, timeout=None):
        raise RuntimeError("어댑터를 만들 수 없다")

    monkeypatch.setattr(services, "get_adapter", broken)
    key = _upload(contest, dev, {"app.py": "print('로그인 기능')\n"})

    created = _submit(client, contest, dev, [{"kind": "source", "value": key}])

    assert created.status_code == 201, created.content
    assert created.json()["scoring_size_warning"] is False
