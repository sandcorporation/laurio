"""배포 뒤 확인·자동 되돌리기(#1092) — 스위치 `CODEMIT_POSTDEPLOY`(off|check|rollback, 기본 off).

`scripts/ci/deploy-prod.sh` 를 임시 git 저장소(직전 배포 A → 이번 배포 B)에서 돌린다. `deploy.sh` 는 받은 명령과
그때의 커밋을 적는 가짜이고, 확인 스크립트는 진짜를 가짜 `docker`·`curl` 위에서 돌린다. 가짜는 `FAKE_BAD` 커밋이
체크아웃돼 있을 때만 `FAKE_FAIL` 단계(deploy.sh 명령 또는 `docker`·`curl`)에서 실패한다 — 되돌린 뒤에는 통과한다.

**off 의 기대 순서는 스위치를 넣기 전 deploy-prod.sh 의 것이다** — 이 파일의 off 시험은 그 판에서도 통과했다.
`deploy.sh rollback-plan` 은 진짜 deploy.sh 로 따로 본다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent

FAKE_DEPLOY = r"""#!/bin/sh
cmd="$2"; arg="${3:-}"
head=$(git rev-parse HEAD)
echo "${cmd}${arg:+ $arg}@$(echo "$head" | cut -c1-4)" >> "$FAKE_CALLS"
if [ "$head" = "${FAKE_BAD:-}" ] && [ "${FAKE_FAIL:-}" = "${cmd}${arg:+ $arg}" ]; then exit 1; fi
case "$cmd" in
  plan)
    printf 'DEPLOY_ANY=%s\nBUILD_BACKEND=%s\nBUILD_FRONTEND=false\nBUILD_OPERATOR=false\nBUILD_CLASSROOM=false\nBUILD_SEARCH=false\nBUILD_PGBOUNCER=false\nBUILD_AGENT_GRADER=false\nPLANNED_COMMIT=%s\n' \
      "${FAKE_ANY:-true}" "${FAKE_ANY:-true}" "$head" > .jenkins-prod-plan ;;
  rollback-plan)
    target=$(cat .jenkins-prod-deployed)
    sed "s/^PLANNED_COMMIT=.*/PLANNED_COMMIT=$target/" .jenkins-prod-plan > .p && mv .p .jenkins-prod-plan
    echo "$target" ;;
  mark) git rev-parse HEAD > .jenkins-prod-deployed; rm -f .jenkins-prod-plan ;;
esac
exit 0
"""

# 실패 판정은 `docker`·`curl` 하위 명령의 이름으로 — ready / health / ping / curl
FAKE_TOOL = r"""#!/bin/sh
case "$*" in
  *scope=ready*) step=ready ;;
  *api/health*) step=health ;;
  *"inspect ping"*) step=ping ;;
  *) step="$TOOL" ;;
esac
echo "$TOOL $step@$(git rev-parse HEAD | cut -c1-4)" >> "$FAKE_CALLS"
if [ "$(git rev-parse HEAD)" = "${FAKE_BAD:-}" ] && [ "${FAKE_FAIL:-}" = "$step" ]; then exit 1; fi
exit 0
"""

OFF_SUCCESS = [
    "preflight", "plan", "image backend", "up", "verify",
    "health backend", "health events", "health search", "reindex", "mark", "glitchtip", "prune",
]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def prod(tmp_path):
    """A(직전 배포, 표식) → B(이번 배포) 두 커밋의 저장소 — 준비는 픽스처라 시험 본문의 CPU 한도 밖이다(#701)."""

    repo = tmp_path / "repo"
    (repo / "scripts" / "ci").mkdir(parents=True)
    (repo / "docker").mkdir()
    for name in ("deploy-prod.sh", "post-deploy-check.sh", "post-deploy-rollback.sh"):
        shutil.copy(REPO_ROOT / "scripts" / "ci" / name, repo / "scripts" / "ci" / name)
    (repo / "scripts" / "ci" / "glitchtip-resolve.sh").write_text(
        '#!/bin/sh\necho "glitchtip@$(git rev-parse HEAD | cut -c1-4)" >> "$FAKE_CALLS"\n', encoding="utf-8",
    )
    (repo / "deploy.sh").write_text(FAKE_DEPLOY, encoding="utf-8")
    (repo / ".gitignore").write_text(".jenkins-prod-*\ndocker/.env.prod\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "A")
    a = _git(repo, "rev-parse", "HEAD")
    (repo / "change.txt").write_text("B\n", encoding="utf-8")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "B")
    b = _git(repo, "rev-parse", "HEAD")
    (repo / ".jenkins-prod-deployed").write_text(a + "\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("docker", "curl"):
        (bin_dir / tool).write_text(FAKE_TOOL.replace("$TOOL", tool), encoding="utf-8")
        (bin_dir / tool).chmod(0o755)
    calls = tmp_path / "calls"
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("CODEMIT_POSTDEPLOY")
    } | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CALLS": str(calls),
        "CODEMIT_POSTDEPLOY_INTERVAL": "0",
        "CODEMIT_POSTDEPLOY_SECONDS": "0",
    }

    def run(*, deploy: str = b, env_file: str | None = None, **fake: str):
        calls.write_text("")
        if env_file is not None:
            (repo / "docker" / ".env.prod").write_text(env_file, encoding="utf-8")
        result = subprocess.run(
            ["bash", "scripts/ci/deploy-prod.sh"], cwd=repo,
            env={**env, "SANDCORP_IMAGE_SHA": deploy, **fake}, capture_output=True, text=True,
        )
        lines = calls.read_text(encoding="utf-8").splitlines()
        return result, lines

    return repo, a, b, run


def _steps(lines: list[str]) -> list[str]:
    return [line.rsplit("@", 1)[0] for line in lines]


def _marker(repo: Path) -> str:
    return (repo / ".jenkins-prod-deployed").read_text(encoding="utf-8").strip()


# ------------------------------------------------------------ off = 지금 그대로


@pytest.mark.parametrize("env_file", [None, "CODEMIT_POSTDEPLOY=off\n"])
def test_off_runs_the_same_steps_and_never_checks(prod, env_file):
    repo, _, b, run = prod
    result, lines = run(env_file=env_file)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _steps(lines) == OFF_SUCCESS
    assert _marker(repo) == b


def test_off_failure_after_replace_ends_2_without_rollback(prod):
    repo, a, b, run = prod
    result, lines = run(FAKE_BAD=b, FAKE_FAIL="health backend")
    assert result.returncode == 2
    assert _steps(lines) == ["preflight", "plan", "image backend", "up", "verify", "health backend"]
    assert _marker(repo) == a


def test_off_image_failure_ends_1(prod):
    _, _, b, run = prod
    result, lines = run(FAKE_BAD=b, FAKE_FAIL="image backend")
    assert result.returncode == 1
    assert _steps(lines) == ["preflight", "plan", "image backend"]


def test_off_docs_only_moves_marker(prod):
    repo, _, b, run = prod
    result, lines = run(FAKE_ANY="false")
    assert result.returncode == 0
    assert _steps(lines) == ["preflight", "plan", "mark", "glitchtip", "prune"]
    assert _marker(repo) == b


# ------------------------------------------------------------ check


def test_check_passes_then_marks(prod):
    repo, _, b, run = prod
    result, lines = run(
        env_file="CODEMIT_POSTDEPLOY=check\nCODEMIT_POSTDEPLOY_URLS=https://web.example/,https://api.example/x\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    steps = _steps(lines)
    assert steps[steps.index("reindex") + 1:] == [
        "docker ready", "docker health", "docker ping", "curl curl", "curl curl", "mark", "glitchtip", "prune",
    ]
    assert "배포 뒤 확인 통과" in result.stdout
    assert _marker(repo) == b


def test_check_failure_ends_2_and_does_not_roll_back(prod):
    repo, a, b, run = prod
    result, lines = run(
        env_file="CODEMIT_POSTDEPLOY=check\nCODEMIT_POSTDEPLOY_URLS=https://web.example/\n",
        FAKE_BAD=b, FAKE_FAIL="ping",
    )
    assert result.returncode == 2
    assert "rollback-plan" not in _steps(lines)
    assert "확인 작업자: 실패" in result.stdout
    assert _marker(repo) == a


def test_check_without_urls_fails_instead_of_passing(prod):
    _, _, _, run = prod
    result, _ = run(CODEMIT_POSTDEPLOY="check")
    assert result.returncode == 2
    assert "CODEMIT_POSTDEPLOY_URLS 가 비었다" in result.stdout


def test_unknown_switch_value_stops_before_replacing(prod):
    _, _, _, run = prod
    result, lines = run(CODEMIT_POSTDEPLOY="on")
    assert result.returncode == 1
    assert lines == []


# ------------------------------------------------------------ rollback


ROLLBACK_ENV = "CODEMIT_POSTDEPLOY=rollback\nCODEMIT_POSTDEPLOY_URLS=https://web.example/\n"


def test_failed_check_rolls_back_to_marker_image(prod):
    repo, a, b, run = prod
    result, lines = run(env_file=ROLLBACK_ENV, FAKE_BAD=b, FAKE_FAIL="curl")
    assert result.returncode == 2, result.stdout + result.stderr
    after = lines[lines.index(f"rollback-plan@{b[:4]}") + 1:]
    assert after == [
        f"{step}@{a[:4]}" for step in (
            "image backend", "up", "verify", "health backend", "health events", "health search", "reindex",
            "docker ready", "docker health", "docker ping", "curl curl",
        )
    ]
    assert "자동 되돌리기 끝" in result.stdout
    assert _git(repo, "rev-parse", "HEAD") == a
    assert _marker(repo) == a
    assert not (repo / ".jenkins-prod-plan").exists()


def test_failed_health_rolls_back_before_the_check(prod):
    _, a, b, run = prod
    result, lines = run(env_file=ROLLBACK_ENV, FAKE_BAD=b, FAKE_FAIL="health backend")
    assert result.returncode == 2
    steps = _steps(lines)
    assert steps[steps.index("health backend") + 1] == "rollback-plan"
    assert f"up@{a[:4]}" in lines


def test_rollback_failure_is_reported(prod):
    repo, a, b, run = prod
    (repo / "docker" / ".env.prod").write_text("CODEMIT_POSTDEPLOY=rollback\n", encoding="utf-8")
    # 주소가 비어 B 의 확인이 실패하고, 되돌린 A 에서는 verify 가 실패한다
    result, lines = run(FAKE_BAD=a, FAKE_FAIL="verify")
    assert result.returncode == 2
    assert lines[-1] == f"verify@{a[:4]}"
    assert "자동 되돌리기 실패(verify)" in result.stdout


def test_manual_rollback_sha_is_not_rolled_back_again(prod):
    repo, a, b, run = prod
    (repo / ".jenkins-prod-deployed").write_text(b + "\n", encoding="utf-8")
    result, lines = run(deploy=a, env_file=ROLLBACK_ENV, FAKE_BAD=a, FAKE_FAIL="health backend")
    assert result.returncode == 2
    assert "rollback-plan" not in _steps(lines)
    assert "되돌리지 않는다" in result.stdout


# ------------------------------------------------------------ 확인 한도


def test_check_gives_up_at_the_time_limit(prod):
    repo, _, b, _ = prod
    bin_dir = repo.parent / "bin"
    result = subprocess.run(
        ["bash", "scripts/ci/post-deploy-check.sh"], cwd=repo, capture_output=True, text=True, timeout=30,
        env={
            **os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_CALLS": str(repo.parent / "calls"), "FAKE_BAD": b, "FAKE_FAIL": "ready",
            "CODEMIT_POSTDEPLOY_SECONDS": "2", "CODEMIT_POSTDEPLOY_INTERVAL": "1",
            "CODEMIT_POSTDEPLOY_URLS": "https://web.example/",
        },
    )
    assert result.returncode == 1
    assert "확인 준비: 실패 — 2초 안에" in result.stdout
    ready_tries = (repo.parent / "calls").read_text(encoding="utf-8").count("docker ready")
    assert 2 <= ready_tries <= 4


# ------------------------------------------------------------ deploy.sh rollback-plan


@pytest.fixture
def real_deploy(tmp_path):
    repo = tmp_path / "real"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "A")
    a = _git(repo, "rev-parse", "HEAD")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "B")
    b = _git(repo, "rev-parse", "HEAD")

    def run(*, marker: str | None, any_: str = "true"):
        if marker is not None:
            (repo / ".jenkins-prod-deployed").write_text(marker + "\n", encoding="utf-8")
        (repo / ".jenkins-prod-plan").write_text(
            f"DEPLOY_ANY={any_}\nBUILD_BACKEND=true\nBUILD_FRONTEND=false\nBUILD_OPERATOR=false\n"
            "BUILD_CLASSROOM=false\nBUILD_SEARCH=true\nBUILD_PGBOUNCER=false\nBUILD_AGENT_GRADER=false\n"
            f"AGENT_GRADER_RECREATE=false\nROLLING_BACKEND=false\nPLANNED_COMMIT={b}\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            ["sh", "deploy.sh", "prod", "rollback-plan"], cwd=repo, capture_output=True, text=True,
        )
        return result, (repo / ".jenkins-prod-plan").read_text(encoding="utf-8")

    return a, b, run


def test_rollback_plan_points_the_failed_plan_at_the_marker(real_deploy):
    a, b, run = real_deploy
    result, plan = run(marker=a)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == a
    assert f"PLANNED_COMMIT={a}" in plan
    assert "BUILD_BACKEND=true" in plan and "BUILD_SEARCH=true" in plan and "BUILD_FRONTEND=false" in plan
    assert "ROLLING_BACKEND=true" in plan


@pytest.mark.parametrize(
    ("marker", "any_", "message"),
    [
        (None, "true", "되돌릴 곳을 모른다"),
        ("B", "true", "되돌릴 곳이 없다"),
        ("A", "false", "되돌릴 것이 없다"),
    ],
)
def test_rollback_plan_refuses_without_a_place_to_go(real_deploy, marker, any_, message):
    a, b, run = real_deploy
    result, plan = run(marker={"A": a, "B": b, None: None}[marker], any_=any_)
    assert result.returncode == 1
    assert message in result.stdout
    assert f"PLANNED_COMMIT={b}" in plan
