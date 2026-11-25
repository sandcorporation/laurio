"""e2e 시드의 채점 스캔 호출 — 앞 실행이 돌아 건너뛰어진 응답을 성공으로 읽지 않는다."""

import pytest

from payouts.management.commands import seed_e2e_operator_queues as queues


class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.content = b""

    def json(self):
        return self._body


class _Client:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def post(self, url, **headers):
        self.calls += 1
        return _Response(self.bodies.pop(0))


def test_skipped_running_is_retried_until_the_scan_really_ran():
    client = _Client([{"skipped": "running"}, {"skipped": "running"}, {"scan": "submission-scoring", "count": 1}])
    body = queues.run_scoring_scan(client, wait_seconds=0)
    assert client.calls == 3
    assert body["count"] == 1


def test_never_finishing_scan_fails_loudly_instead_of_seeding_unscored_data():
    client = _Client([{"skipped": "running"}] * 3)
    with pytest.raises(AssertionError):
        queues.run_scoring_scan(client, attempts=3, wait_seconds=0)
