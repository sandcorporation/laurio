"""운영 env 만 바뀐 배포도 앱 컨테이너를 다시 올린다(#1372) — 진짜 `deploy.sh` 를 돌린다.

`plan` 은 「직전 배포 표식 → 이 커밋」의 경로 차이로 교체를 정한다. 운영 env 파일(`docker/.env.<target>`)은
저장소 밖이라 그 비교에 들지 않아, env 를 고친 뒤 같은 커밋을 다시 배포(ROLLBACK_SHA)해도 「배포할 것이 없다」로
끝나 컨테이너가 옛 env 를 들고 있었다(배포 잡 #801).

지금은 `mark` 가 env 파일의 sha256 을 표식 옆(`.jenkins-<target>-env-sha256`, 600)에 남기고, `plan` 이 지금 지문과
견준다 — 다르거나 남긴 것이 없으면 교체 길(`ENV_CHANGED`)을 타고, `up` 이 backend·celery-worker·events·grader·
llm-proxy 를 이미지는 그대로 둔 채 다시 만든다. 로그에는 지문도 값도 찍지 않는다.
"""

from __future__ import annotations

import hashlib
import stat
import subprocess

import pytest

from tests.test_deploy_plan_rolling import _git, _prepare

ENV_TEXT = "SECRET_KEY=fake-only-for-test\n"
FINGERPRINT = hashlib.sha256(ENV_TEXT.encode()).hexdigest()

# `up` 이 부른 docker 명령을 한 줄씩 남기는 가짜 — 컨테이너는 늘 하나(`cid-<서비스>`) 떠 있다.
FAKE_DOCKER_LOG = """#!/bin/sh
echo "$*" >> "$FAKE_DOCKER_LOG"
if [ "$1" = compose ]; then
  for a in "$@"; do last=$a; done
  case " $* " in *" ps -q "*) echo "cid-$last" ;; esac
fi
exit 0
"""


def _docs_only(tmp_path, fingerprint: str | None):
    """코드는 안 바뀐 커밋(이미지 문맥 밖 파일만), env 는 `ENV_TEXT`, 남긴 지문은 `fingerprint`."""
    repo, env = _prepare(tmp_path, lambda compose: compose, touch=("frontend/playwright.config.ts",))
    (repo / "docker/.env.prod").write_text(ENV_TEXT, encoding="utf-8")
    if fingerprint is not None:
        (repo / ".jenkins-prod-env-sha256").write_text(fingerprint + "\n", encoding="utf-8")
    return repo, env


def _run(prepared, *args: str) -> subprocess.CompletedProcess[str]:
    repo, env = prepared
    result = subprocess.run(["sh", "deploy.sh", "prod", *args], cwd=repo, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _plan(prepared) -> tuple[dict[str, str], str]:
    out = _run(prepared, "plan").stdout
    text = (prepared[0] / ".jenkins-prod-plan").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line), out


@pytest.fixture
def env_changed(tmp_path):
    return _docs_only(tmp_path, "0" * 64)


@pytest.fixture
def env_same(tmp_path):
    return _docs_only(tmp_path, FINGERPRINT)


@pytest.fixture
def no_fingerprint(tmp_path):
    return _docs_only(tmp_path, None)


def test_no_code_change_but_env_fingerprint_differs_replaces(env_changed):
    plan, out = _plan(env_changed)

    assert plan["DEPLOY_ANY"] == "true"
    assert plan["ENV_CHANGED"] == "true"
    # 이미지 받기는 그대로 plan 을 따른다 — 바뀐 서비스가 없으니 받지 않는다
    assert [v for k, v in plan.items() if k.startswith("BUILD_")] == ["false"] * 7
    assert "env 가 바뀌어 다시 올린다" in out
    assert "배포할 것이 없다" not in out
    assert FINGERPRINT not in out and "fake-only-for-test" not in out


def test_no_code_change_and_same_fingerprint_does_not_replace(env_same):
    plan, out = _plan(env_same)

    assert plan["DEPLOY_ANY"] == "false"
    assert plan["ENV_CHANGED"] == "false"
    assert "env 가 바뀌어" not in out


def test_missing_fingerprint_file_replaces(no_fingerprint):
    plan, _ = _plan(no_fingerprint)

    assert plan["DEPLOY_ANY"] == "true"
    assert plan["ENV_CHANGED"] == "true"


@pytest.fixture
def marked(no_fingerprint):
    result = _run(no_fingerprint, "mark")
    return no_fingerprint[0], result.stdout


def test_mark_leaves_only_the_fingerprint_owner_readable(marked):
    repo, out = marked
    kept = repo / ".jenkins-prod-env-sha256"

    assert kept.read_text(encoding="utf-8").strip() == FINGERPRINT
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert FINGERPRINT not in out


@pytest.fixture
def env_only_up(tmp_path):
    repo, env = _docs_only(tmp_path, None)
    (tmp_path / "bin" / "docker").write_text(FAKE_DOCKER_LOG, encoding="utf-8")
    log = tmp_path / "docker.log"
    head = _git(repo, "rev-parse", "HEAD")
    flags = {f"BUILD_{s}": "false" for s in
             ("BACKEND", "FRONTEND", "OPERATOR", "CLASSROOM", "SEARCH", "PGBOUNCER", "AGENT_GRADER")}
    plan = {"DEPLOY_ANY": "true", **flags, "AGENT_GRADER_RECREATE": "false", "ENV_CHANGED": "true",
            "ROLLING_BACKEND": "false", "PLANNED_COMMIT": head}
    (repo / ".jenkins-prod-plan").write_text("".join(f"{k}={v}\n" for k, v in plan.items()), encoding="utf-8")
    result = _run((repo, {**env, "FAKE_DOCKER_LOG": str(log)}), "up")
    return log.read_text(encoding="utf-8").splitlines(), result.stdout


def test_env_only_up_recreates_every_backend_env_service(env_only_up):
    calls, out = env_only_up
    ups = [c for c in calls if " up -d --no-deps " in f" {c} "]

    recreated = {w for c in ups if "--force-recreate" in c for w in c.split()}
    assert {"backend", "celery-worker", "events", "grader", "llm-proxy"} <= recreated
    # 이미지 받기·마이그레이션 길은 타지 않는다
    assert not [c for c in calls if " pull " in f" {c} " or "migrate" in c]
    assert "env 가 바뀌어" in out
