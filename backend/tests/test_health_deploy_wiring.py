"""`/api/health` 의 워커 점검과 배포 배선(#949).

운영 backend 만 워커 신호를 요구하고(`HEALTH_REQUIRED_WORKERS`), 배포 롤링·`deploy.sh health` 는
`?scope=ready` 라 워커 교체 중에도 막히지 않는다. 워커 컨테이너는 신호 파일 healthcheck 를 단다.
"""

from __future__ import annotations

import pytest

from tests.test_deploy_celery_beat_in_worker import DEPLOY, _compose


def test_prod_backend_requires_both_worker_signals():
    env = _compose("compose.prod.yaml")["services"]["backend"]["environment"]

    assert env["HEALTH_REQUIRED_WORKERS"] == "celery,grader"


@pytest.mark.parametrize("name", ["celery-worker", "grader"])
def test_prod_workers_have_signal_file_healthcheck(name):
    test = _compose("compose.prod.yaml")["services"][name]["healthcheck"]["test"][-1]

    assert "/tmp/codemit-heartbeat" in test
    assert "-90 seconds" in test


def test_only_backend_requires_signals():
    services = _compose("compose.prod.yaml")["services"]

    for name in ("celery-worker", "grader", "events"):
        assert "HEALTH_REQUIRED_WORKERS" not in services[name].get("environment", {})


def test_deploy_health_probe_uses_ready_scope():
    assert "/api/health?scope=ready" in DEPLOY
    assert "/api/health'" not in DEPLOY
