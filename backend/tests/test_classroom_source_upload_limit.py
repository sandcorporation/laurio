"""참여자 문제 화면이 받는 소스 업로드 상한(#671) — 운영자 정책 `max_source_asset_bytes` 그대로.

정책 API 는 운영자 라우터라 강의실이 읽지 못한다 — 참여자 화면이 이미 읽는 응답
(`GET .../problems/{id}/mine`)이 그 값을 싣는다. 업로드를 실제로 막는 상한(`submissions.resolvers`)과
같은 칸이다.
"""

from __future__ import annotations

from tests.classroom_scenarios import create_class, create_open_problem, join_class, login, mine
from tests.test_operator_policy import _change_policy, _client_for


def _participant_problem(client):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"])
    return owner, learner, class_id, problem


def test_the_participant_sees_the_policy_source_limit(client, db):
    owner, learner, class_id, problem = _participant_problem(client)
    root = _client_for("root-source-limit", superuser=True)
    changed = _change_policy(root, max_source_asset_bytes=30 * 1024 * 1024, reason="소스 상한 조정")
    assert changed.status_code == 200, changed.content

    assert mine(client, learner["access"], class_id, problem.id)["max_source_asset_bytes"] == 30 * 1024 * 1024
    assert mine(client, owner["access"], class_id, problem.id)["max_source_asset_bytes"] == 30 * 1024 * 1024
