"""`deploy.sh prod e2e-digest` — 떠 있는 앱·backend 가 열차의 e2e 가 본 이미지인지 견준다(#729). 진짜 스크립트를 돌린다.

열차는 e2e 가 받은 arm64 이미지에 `e2e-<묶음 트리>-arm64` 태그를 붙이고(`scripts/ci/images-e2e.sh`), prod 는
이 커밋의 트리로 그 태그를 받아 컨테이너의 이미지 ID 와 견준다. 여기서 고정하는 셋:
- 같으면 「같다」, 다르면 「다르다」, 태그가 없거나 컨테이너가 없으면 「대조 못 함」으로 적는다.
- 「다르다」는 떠 있는 이미지를 띄운 커밋(컨테이너의 `<sha>-arm64` 태그)과 이 커밋의 **문맥**을 견줘 가른다(#738):
  문맥이 같으면 같은 코드를 다시 구운 것(「다르다(문맥 같음 — 다시 구운 것)」), 다르면 「다르다!(문맥 다름)」,
  견주지 못하면 「다르다!(문맥 모름)」. 두 이미지 ID 와 떠 있는 커밋을 줄에 함께 싣는다.
- **관측만 한다** — 무엇이 나와도 0 으로 끝난다(배포를 붉히지 않는다).
- 태그는 이 커밋의 **트리**로 찾는다(쌓은 sha 와 main 의 sha 는 다르고, 같은 것은 트리다).

가짜 `docker` 의 상태: `running-<서비스>` 는 떠 있는 컨테이너의 이미지 ID, `ref-<서비스>` 는 그 컨테이너를
만든 이미지 이름(없으면 이 커밋의 태그), `e2e-<서비스>` 는 그 서비스의 e2e 태그가 가리키는 이미지 ID(없으면
태그가 없다). 받은 ref 는 `pulled` 에 적는다. 문맥 비교(`scripts/ci/image_context.py changed`)는 가짜 스크립트가
`changed` 의 내용을 내고 받은 인자를 `changed-args` 에 적는다 — 해시 자체는 `scripts/test_image_context.py` 의 몫이다.
저장소에는 커밋이 둘 있다 — 옛 커밋(`env["FAKE_OLD"]`, 떠 있는 컨테이너를 만든 커밋 역)과 지금 커밋. 이 체크아웃에
없는 커밋은 `UNKNOWN` 이다(#741 — 진짜 `changed` 는 모르는 커밋에도 0 으로 끝나니 호출 쪽이 `cat-file -e` 로 가른다).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_deploy_plan_rolling import COMPOSE, REPO_ROOT, _git

FAKE_DOCKER = """#!/bin/sh
state="$FAKE_DOCKER_STATE"
case "$1" in
  inspect)
    svc=${4#cid-}
    if [ "$3" = '{{.Config.Image}}' ]; then
      cat "$state/ref-$svc" 2>/dev/null || echo "ghcr.io/sandcorporation/codemit-$svc:$FAKE_HEAD-arm64"
    else
      cat "$state/running-$svc" 2>/dev/null
    fi
    exit 0 ;;
  pull)
    echo "$3" >> "$state/pulled"
    svc=${3##*/codemit-}; svc=${svc%%:*}
    [ -e "$state/e2e-$svc" ]; exit $? ;;
  image)
    if [ "$2" = inspect ]; then svc=${5##*/codemit-}; svc=${svc%%:*}; cat "$state/e2e-$svc"; fi
    exit 0 ;;
  compose)
    shift
    while [ $# -gt 0 ]; do case "$1" in -f|--env-file) shift 2 ;; -*) shift ;; *) break ;; esac; done
    if [ "$1" = ps ] && [ -e "$state/running-$3" ]; then echo "cid-$3"; fi
    exit 0 ;;
esac
exit 0
"""

UNKNOWN = "1" * 40

FAKE_IMAGE_CONTEXT = """import os, sys
state = os.environ["FAKE_DOCKER_STATE"]
with open(os.path.join(state, "changed-args"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
path = os.path.join(state, "changed")
if not os.path.exists(path):
    sys.exit(1)
print(open(path).read().strip())
"""


@pytest.fixture
def prod(tmp_path):
    """옛 커밋·지금 커밋 둘짜리 저장소 + 가짜 docker. 준비는 픽스처에서 — 시험 본문의 CPU 한도 밖이다(#701)."""
    repo = tmp_path / "repo"
    (repo / "docker").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "deploy.sh", repo / "deploy.sh")
    shutil.copy(REPO_ROOT / COMPOSE, repo / COMPOSE)
    (repo / "docker/.env.prod").write_text("", encoding="utf-8")
    (repo / "scripts/ci").mkdir(parents=True)
    (repo / "scripts/ci/image_context.py").write_text(FAKE_IMAGE_CONTEXT, encoding="utf-8")
    _git(repo, "init", "-q")
    (repo / "old").write_text("", encoding="utf-8")
    _git(repo, "add", "old")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "옛 배포")
    old = _git(repo, "rev-parse", "HEAD")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "배포")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    head = _git(repo, "rev-parse", "HEAD")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_DOCKER_STATE": str(state), "FAKE_HEAD": head, "FAKE_OLD": old}
    return repo, env, state, tree


def _run(repo: Path, env: dict[str, str], target: str = "prod") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["sh", "deploy.sh", target, "e2e-digest"], cwd=repo, env=env, capture_output=True, text=True)


def test_each_service_is_reported_and_the_run_stays_green(prod) -> None:
    repo, env, state, tree = prod
    (state / "running-backend").write_text("sha256:aaa\n")
    (state / "e2e-backend").write_text("sha256:aaa\n")
    (state / "running-frontend").write_text("sha256:bbb\n")
    (state / "e2e-frontend").write_text("sha256:ccc\n")
    (state / "ref-frontend").write_text(f"ghcr.io/sandcorporation/codemit-frontend:{env['FAKE_OLD']}-arm64\n")
    (state / "changed").write_text("frontend\n")
    (state / "running-operator").write_text("sha256:ddd\n")  # e2e 태그가 없다
    # classroom 은 떠 있지 않다

    done = _run(repo, env)

    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "e2e 대조: backend — 같다" in out
    assert "e2e 대조: frontend — 다르다!(문맥 다름)" in out  # 옛 커밋에서 떠 있고 문맥이 다르다
    assert "e2e 대조: operator — " in out and "열차가 이 트리를 e2e 로 보지 않았다" in out
    assert "e2e 대조: classroom — 떠 있는 컨테이너가 없다" in out
    assert "같다 1 · 다시 구움 0 · 다르다 1 · 대조 못 함 2" in out
    assert f"ghcr.io/sandcorporation/codemit-backend:e2e-{tree}-arm64" in (state / "pulled").read_text()


def test_staging_is_not_compared(prod) -> None:
    repo, env, state, _ = prod
    (repo / "docker/compose.staging.yaml").write_text("services: {}\n")
    (repo / "docker/.env.staging").write_text("")

    done = _run(repo, env, "staging")

    assert done.returncode == 0, done.stdout + done.stderr
    assert "대조하지 않는다" in done.stdout
    assert not (state / "pulled").exists()


def test_a_rebuilt_image_of_the_same_context_is_told_apart(prod) -> None:
    # #738 — ctx 가 prune 된 서비스는 열차가 같은 문맥을 다시 굽고 digest 가 바뀐다. plan 은 문맥이 같아
    # 바꿔 끼우지 않으니 떠 있는 것(옛 커밋의 이미지)과 e2e 가 본 것이 다르지만 같은 코드다.
    repo, env, state, _ = prod
    for svc in ("backend", "frontend", "operator", "classroom"):
        (state / f"running-{svc}").write_text("sha256:old000000000000000000\n")
        (state / f"ref-{svc}").write_text(f"ghcr.io/sandcorporation/codemit-{svc}:{env['FAKE_OLD']}-arm64\n")
        (state / f"e2e-{svc}").write_text("sha256:new000000000000000000\n")
    (state / "changed").write_text("frontend\n")
    (state / "ref-classroom").write_text("codemit-classroom:local\n")  # 커밋 태그가 아니다

    done = _run(repo, env)

    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "e2e 대조: backend — 다르다(문맥 같음 — 다시 구운 것)" in out
    assert "e2e 대조: frontend — 다르다!(문맥 다름)" in out
    assert "e2e 대조: classroom — 다르다!(문맥 모름)" in out
    assert "떠 있는 것 sha256:old000000000 (" + env["FAKE_OLD"][:12] + ")" in out
    assert "e2e 가 본 것 sha256:new000000000" in out
    assert "같다 0 · 다시 구움 2 · 다르다 2 · 대조 못 함 0" in out
    # 같은 커밋은 한 번만 견준다.
    assert (state / "changed-args").read_text().splitlines() == [f"changed {env['FAKE_OLD']} HEAD"]


def test_an_unknown_context_comparison_says_so(prod) -> None:
    # 떠 있는 컨테이너를 만든 커밋이 이 체크아웃에 없거나(force-push·얕은 체크아웃) 이미지 이름이 커밋 태그가
    # 아니면 문맥을 견주지 못한다 — 「문맥 다름」이 아니라 「문맥 모름」이다(#741).
    # C 로캘로 돈다(PR CI 와 같다) — 「커밋 모름」을 `cut -c` 로 자르면 바이트로 잘려 UTF-8 이 깨진다(32708a5).
    repo, env, state, _ = prod
    for svc in ("backend", "frontend"):
        (state / f"running-{svc}").write_text("sha256:old\n")
        (state / f"e2e-{svc}").write_text("sha256:new\n")
    (state / "ref-backend").write_text(f"ghcr.io/sandcorporation/codemit-backend:{UNKNOWN}-arm64\n")
    (state / "ref-frontend").write_text("codemit-frontend:local\n")
    (state / "changed").write_text("\n")  # 진짜 `changed` 처럼 모르는 커밋에도 0 으로 끝난다

    done = _run(repo, {**env, "LC_ALL": "C", "LANG": "C"})

    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert f"e2e 대조: backend — 다르다!(문맥 모름) 떠 있는 것 sha256:old ({UNKNOWN[:12]})" in out
    assert "e2e 대조: frontend — 다르다!(문맥 모름) 떠 있는 것 sha256:old (커밋 모름)" in out
    assert "같다 0 · 다시 구움 0 · 다르다 2 · 대조 못 함 2" in out
    assert not (state / "changed-args").exists()  # 모르는 커밋으로는 견주지 않는다


def test_an_image_started_at_this_commit_is_the_same_context(prod) -> None:
    # 이 커밋의 태그로 떠 있는데 digest 가 다르면 같은 트리를 다른 곳에서 다시 구운 것이다 — 견줄 것도 없다.
    repo, env, state, _ = prod
    (state / "running-backend").write_text("sha256:old\n")
    (state / "e2e-backend").write_text("sha256:new\n")

    done = _run(repo, env)

    assert "e2e 대조: backend — 다르다(문맥 같음 — 다시 구운 것)" in done.stdout
    assert not (state / "changed-args").exists()
