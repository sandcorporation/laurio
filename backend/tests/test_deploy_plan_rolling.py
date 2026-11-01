"""`deploy.sh plan` 이 compose 파일만 바뀐 배포를 겹쳐 바꾸는지 — 진짜 스크립트를 돌린다.

2026-10-06 prod(GlitchTip 64 재발, 강의실 알림 수 `TypeError: fetch failed`): #582 가
`docker/compose.prod.yaml` 에 채점 워커 `celery-scoring` 을 더했다. `plan` 은 compose 파일이
바뀌면 「어느 서비스의 환경이 바뀌었는지 모른다」며 **풀러까지** 바꿀 것으로 표시했고, 풀러를
바꾸는 배포는 겹쳐 바꾸지 않는다 — backend·events 를 내리고 올렸다. 그 창(이벤트 서비스 이름이
16초 넘게 안 풀렸다)이 BFF 재시도 예산(약 15.8초)보다 길어 강의실 BFF 가 500 을 냈다.

풀러의 정의가 그대로면 풀러를 바꿀 까닭이 없다. 이 시험은 임시 git 저장소에 직전 배포와
지금 커밋을 만들고 진짜 `deploy.sh prod plan` 을 돌린다. `docker` 는 PATH 의 가짜다 — 컨테이너는
다 떠 있다고 답하고, `compose -f <파일> config <서비스>` 에는 진짜 compose 처럼 그 서비스와
그것이 `depends_on` 으로 기대는 서비스의 정의를 함께 내놓는다. `config --hash pgbouncer` 에는
풀러 자신의 정의만으로 낸 해시를 낸다(진짜 compose 도 그 서비스만 해시한다).

2026-10-26 prod(GlitchTip 75 재발): #790 이 `db`·`redis` 이미지를 digest 로 고정했다. `db` 는
배포가 다시 만들지 않는데(`up --no-recreate`), 풀러 비교가 `config pgbouncer` 의 렌더 —
`depends_on` 의 `db` 까지 든 — 를 견줘 「풀러가 바뀌었다」가 됐고, backend 넷이 31초 내려가
공개 앱 `/contests` 가 `fetch failed`(ENOTFOUND backend)로 500 을 냈다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
COMPOSE = "docker/compose.prod.yaml"

# 가짜 `docker` 는 `sh` 다 — `plan` 은 서비스마다 `compose ps -q` 를 부르는데(열두 번 남짓),
# 그때마다 파이썬을 띄우면 그것만으로 CPU 0.4초가 든다(#701). 정의를 렌더해야 하는
# `config` 만 파이썬(`docker-config`)에 넘긴다.
# 세 앱의 실행 env 어긋남(#711·#727)은 이 파일의 관심이 아니다 — 떠 있는 컨테이너의 설정 해시와
# 지금 해시를 같은 값(`same`)으로 답해 「어긋나지 않음」으로 둔다(`test_deploy_plan_app_env.py` 가 본다).
FAKE_DOCKER = """#!/bin/sh
if [ "$1" = inspect ]; then
  case "$3" in *config-hash*) echo same ;; esac
  exit 0
fi
[ "$1" = compose ] || exit 0
shift
compose_file=
while [ $# -gt 0 ]; do
  case "$1" in
    -f) compose_file=$2; shift 2 ;;
    --env-file) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
case "$1" in
  ps) [ "$2" = -q ] && echo "cid-$3" ;;
  config) shift; exec "$(dirname "$0")/docker-config" "$compose_file" "$@" ;;
esac
exit 0
"""

# `--hash` 는 풀러만 진짜로 낸다 — 세 앱의 해시는 위 `inspect` 와 같은 `same` 이다.
FAKE_DOCKER_CONFIG = f"""#!{sys.executable}
import hashlib, json, sys
import yaml

compose_file, *names = sys.argv[1:]
with open(compose_file, encoding="utf-8") as f:
    services = yaml.safe_load(f)["services"]
if names[0] == "--hash":
    for s in names[1:]:
        digest = hashlib.sha256(json.dumps(services[s], sort_keys=True).encode()).hexdigest()
        print(s, digest if s == "pgbouncer" else "same")
    sys.exit(0)
rendered, todo = {{}}, list(names)
while todo:
    s = todo.pop()
    if s not in rendered:
        rendered[s] = services[s]
        todo.extend(services[s].get("depends_on") or ())
print(json.dumps(rendered, sort_keys=True))
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


# 문맥 해시(#712)가 도는 저장소 — `image_context.py` 의 표가 요구하는 경로를 다 둔다.
CONTEXT_FILES = (
    "backend/app.py", "frontend/app/page.tsx", "frontend/playwright.config.ts", "operator/page.tsx",
    "classroom/page.tsx", "packages/shared/index.ts", "package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml",
    "docker/pgbouncer/entry.sh",
    *(f"docker/{n}.Dockerfile" for n in ("backend", "frontend", "operator", "classroom", "search", "pgbouncer")),
)


def _prepare(tmp_path: Path, change, *, touch: tuple[str, ...] = ()) -> tuple[Path, dict[str, str]]:
    """직전 배포·이번 배포 커밋이 든 임시 저장소와 가짜 `docker` 를 PATH 에 둔 환경.

    준비(git 서브프로세스 여럿)라 픽스처에서 부른다 — 시험 본문의 CPU 한도 밖이다(#701).
    본문에는 `plan` 호출과 단언만 남는다."""

    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    compose = (REPO_ROOT / COMPOSE).read_text(encoding="utf-8")
    (repo / COMPOSE).write_text(compose, encoding="utf-8")
    (repo / ".gitignore").write_text(".jenkins-*\ndocker/.env.prod\n", encoding="utf-8")
    (repo / "docker/.env.prod").write_text("", encoding="utf-8")
    if touch:
        (repo / "scripts/ci").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "scripts/ci/image_context.py", repo / "scripts/ci/image_context.py")
        for rel in CONTEXT_FILES:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(rel, encoding="utf-8")
        (repo / ".dockerignore").write_text("**/playwright.config.ts\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "직전 배포")
    (repo / ".jenkins-prod-deployed").write_text(_git(repo, "rev-parse", "HEAD") + "\n")

    (repo / COMPOSE).write_text(change(compose), encoding="utf-8")
    for rel in touch:
        (repo / rel).write_text("바뀜", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "이번 배포")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", FAKE_DOCKER), ("docker-config", FAKE_DOCKER_CONFIG)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return repo, env


def _plan(prepared: tuple[Path, dict[str, str]]) -> dict[str, str]:
    repo, env = prepared
    result = subprocess.run(
        ["sh", "deploy.sh", "prod", "plan"], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = (repo / ".jenkins-prod-plan").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in plan.splitlines() if "=" in line)


@pytest.fixture
def other_service_changed(tmp_path):
    # #582 의 모양 — 다른 서비스의 command 만 바꾼다.
    def change(compose: str) -> str:
        changed = compose.replace(
            "command: celery -A config worker -Q celery -B --schedule /tmp/celerybeat-schedule --concurrency 2 --loglevel info",
            "command: celery -A config worker -Q celery -B --schedule /tmp/celerybeat-schedule --concurrency 2 --loglevel debug",
        )
        assert changed != compose
        return changed

    return _prepare(tmp_path, change)


def test_compose_change_that_leaves_the_pooler_alone_still_rolls_the_backend(other_service_changed):
    plan = _plan(other_service_changed)

    assert plan["BUILD_BACKEND"] == "true"
    assert plan["BUILD_PGBOUNCER"] == "false"
    assert plan["ROLLING_BACKEND"] == "true"


@pytest.fixture
def pooler_changed(tmp_path):
    def change(compose: str) -> str:
        changed = compose.replace(
            "      PGBOUNCER_POOL_MODE: transaction\n",
            "      PGBOUNCER_POOL_MODE: transaction\n      PGBOUNCER_DEFAULT_POOL_SIZE: 30\n",
        )
        assert changed != compose
        return changed

    return _prepare(tmp_path, change)


def test_compose_change_to_the_pooler_itself_still_replaces_the_pooler(pooler_changed):
    plan = _plan(pooler_changed)

    assert plan["BUILD_PGBOUNCER"] == "true"
    assert plan["ROLLING_BACKEND"] == "false"


@pytest.fixture
def db_image_pinned(tmp_path):
    # #790 의 모양 — 풀러가 기대는 db 의 이미지만 digest 로 고정한다.
    def change(compose: str) -> str:
        changed = compose.replace("image: postgres:17-alpine@sha256:", "image: postgres:17-alpine@sha256:0", 1)
        assert changed != compose
        return changed

    return _prepare(tmp_path, change)


def test_compose_change_to_the_db_the_pooler_relies_on_leaves_the_pooler_alone(db_image_pinned):
    plan = _plan(db_image_pinned)

    assert plan["BUILD_PGBOUNCER"] == "false"
    assert plan["ROLLING_BACKEND"] == "true"


# 이미지 문맥 해시로 고른다(#712, codemit-deploy-staging #474) — 문맥 밖 파일만 바뀐 커밋은 그 앱을 다시 띄우지 않는다.
@pytest.fixture
def playwright_config_only(tmp_path):
    return _prepare(tmp_path, lambda compose: compose, touch=("frontend/playwright.config.ts",))


def test_a_file_outside_the_image_context_replaces_nothing(playwright_config_only):
    plan = _plan(playwright_config_only)

    assert plan["BUILD_FRONTEND"] == "false"
    assert plan["BUILD_BACKEND"] == "false"


@pytest.fixture
def frontend_page_changed(tmp_path):
    return _prepare(tmp_path, lambda compose: compose, touch=("frontend/app/page.tsx",))


def test_a_file_in_the_image_context_replaces_only_that_app(frontend_page_changed):
    plan = _plan(frontend_page_changed)

    assert plan["BUILD_FRONTEND"] == "true"
    assert plan["BUILD_OPERATOR"] == "false"
    assert plan["BUILD_BACKEND"] == "false"


# prod 에이전트에는 python3 가 없다(#849) — 그 자리에서는 컨트롤러가 「대상 확인」 단계에서 낸 문맥 해시의 답을
# env 로 받아 쓴다. 기준(배포 표식)과 대상(HEAD)이 둘 다 맞을 때만이고, 못 쓰면 이유 한 줄을 찍고 경로로 떨어진다.
NO_PYTHON = {"CODEMIT_DEPLOY_PYTHON": "python3-없는-에이전트"}


def _controller(prepared: tuple[Path, dict[str, str]], changed: str, **override: str) -> tuple[Path, dict[str, str]]:
    repo, env = prepared
    answer = {
        "CODEMIT_CTX_BASE": (repo / ".jenkins-prod-deployed").read_text(encoding="utf-8").strip(),
        "CODEMIT_CTX_HEAD": _git(repo, "rev-parse", "HEAD"),
        "CODEMIT_CTX_CHANGED": changed,
    }
    return repo, {**env, **NO_PYTHON, **answer, **override}


def _plan_logged(prepared: tuple[Path, dict[str, str]]) -> tuple[dict[str, str], str]:
    repo, env = prepared
    result = subprocess.run(
        ["sh", "deploy.sh", "prod", "plan"], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = (repo / ".jenkins-prod-plan").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in plan.splitlines() if "=" in line), result.stdout


@pytest.fixture
def no_python_controller_says_nothing_changed(tmp_path):
    return _controller(_prepare(tmp_path, lambda c: c, touch=("frontend/playwright.config.ts",)), "")


def test_without_python_the_controllers_answer_skips_every_unchanged_image(no_python_controller_says_nothing_changed):
    plan, out = _plan_logged(no_python_controller_says_nothing_changed)

    assert "문맥 해시로 고른다(컨트롤러가 낸 값) — 바뀐 서비스: 없음" in out
    assert [k for k, v in plan.items() if k.startswith("BUILD_") and v == "true"] == []


@pytest.fixture
def no_python_controller_says_frontend(tmp_path):
    return _controller(_prepare(tmp_path, lambda c: c, touch=("frontend/app/page.tsx",)), "frontend")


def test_without_python_the_controllers_answer_replaces_only_the_changed_image(no_python_controller_says_frontend):
    plan, out = _plan_logged(no_python_controller_says_frontend)

    assert "바뀐 서비스: frontend" in out
    assert plan["BUILD_FRONTEND"] == "true"
    assert plan["BUILD_BACKEND"] == plan["BUILD_OPERATOR"] == plan["BUILD_CLASSROOM"] == "false"


@pytest.fixture
def controller_answer_from_another_base(tmp_path):
    return _controller(
        _prepare(tmp_path, lambda c: c, touch=("frontend/playwright.config.ts",)), "", CODEMIT_CTX_BASE="0" * 40
    )


def test_a_controller_answer_for_another_base_is_not_used_and_says_why(controller_answer_from_another_base):
    plan, out = _plan_logged(controller_answer_from_another_base)

    assert "문맥 해시를 내지 못했다 — 경로로 고른다." in out
    assert "이유: python3-없는-에이전트 가 없고 컨트롤러가 낸 값의 기준(000000000000)이" in out
    assert plan["BUILD_FRONTEND"] == "true"


@pytest.fixture
def no_python_no_answer(tmp_path):
    repo, env = _prepare(tmp_path, lambda c: c, touch=("frontend/playwright.config.ts",))
    return repo, {**env, **NO_PYTHON}


def test_without_python_or_an_answer_the_reason_is_printed(no_python_no_answer):
    _, out = _plan_logged(no_python_no_answer)

    assert "이유: python3-없는-에이전트 가 없고 컨트롤러가 넘긴 값(CODEMIT_CTX_BASE)도 없다" in out
