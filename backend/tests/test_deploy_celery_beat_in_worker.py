"""beat 는 worker 안에서 돈다(#859) — 별도 `celery-beat` 컨테이너가 없다.

oracle 메모리를 줄이려고 worker 를 `-B` 로 띄우고 prefork 자식 수를 고정했다(전: 코어 수 4 + beat
컨테이너 153MiB). beat 가 둘이면 같은 주기 작업이 두 번 쏘이므로, compose 에서 사라진 옛
`celery-beat` 컨테이너는 배포가 걷는다 — 걷는 자리는 채점 고아를 걷는 함수(#584)와 같다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
DEPLOY = (REPO_ROOT / "deploy.sh").read_text(encoding="utf-8")


class _ComposeLoader(yaml.SafeLoader):
    """compose 의 `!reset`(덮어쓰기 표식)을 그 값 그대로 읽는다."""


_ComposeLoader.add_constructor(
    "!reset",
    lambda loader, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else loader.construct_mapping(node)
    if isinstance(node, yaml.MappingNode)
    else loader.construct_scalar(node),
)


def _compose(name: str) -> dict:
    return yaml.load((REPO_ROOT / "docker" / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


@pytest.mark.parametrize("name", ["compose.prod.yaml", "compose.dev.yaml", "compose.ci-images.yaml"])
def test_no_compose_file_defines_a_separate_beat(name):
    assert "celery-beat" not in _compose(name)["services"]


@pytest.mark.parametrize("name", ["compose.prod.yaml", "compose.dev.yaml"])
def test_the_worker_runs_beat_with_a_writable_schedule_and_a_fixed_pool(name):
    command = _compose(name)["services"]["celery-worker"]["command"]
    args = command.split()
    assert "-B" in args
    # 작업 디렉터리(/app)가 아니라 /tmp — 앱 사용자가 바뀌어도 쓸 수 있는 자리다.
    assert args[args.index("--schedule") + 1].startswith("/tmp/")
    # 없으면 prefork 자식이 코어 수만큼 생긴다(oracle 4개, 자식 하나 약 160MiB).
    assert args[args.index("--concurrency") + 1] == "2"


def test_deploy_no_longer_names_the_beat_service_anywhere_but_the_orphan_sweep():
    assert 'backend) echo "backend celery-worker events grader" ;;' in DEPLOY
    rest = DEPLOY.replace(_retire_function(), "")
    code = [line for line in rest.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "celery-beat" in line]
    assert "for svc in celery-scoring grader celery-beat; do" in _retire_function()


def _retire_function() -> str:
    match = re.search(r"^retire_orphan_services\(\) \{\n.*?^\}\n", DEPLOY, re.S | re.M)
    assert match, "deploy.sh 에 retire_orphan_services 가 없다"
    return match.group(0)


FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$CALLS"
case "$*" in
  "ps -aq --filter label=com.docker.compose.service=celery-beat"*) echo old-beat ;;
esac
exit 0
"""


def test_the_sweep_stops_and_removes_an_old_beat_container(tmp_path: Path):
    """첫 배포: compose 에는 beat 가 없고 옛 `celery-beat` 컨테이너가 남아 있다 → 멈추고 지운다."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    calls = tmp_path / "calls"
    script = (
        "log() { echo \"$*\"; }\n"
        "COMPOSE=fake_compose\n"
        "fake_compose() { [ \"$1\" = config ] && printf 'backend\\ncelery-worker\\ngrader\\n'; return 0; }\n"
        "TARGET=prod\n" + _retire_function() + "retire_orphan_services\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls)}
    out = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True, check=True)
    recorded = calls.read_text().splitlines()
    assert any(c.startswith("stop") and "old-beat" in c for c in recorded), recorded
    assert "rm old-beat" in recorded
    # grader 는 compose 에 있으니 건드리지 않는다.
    assert not any("service=grader" in c for c in recorded)
    assert "celery-beat" in out.stdout
