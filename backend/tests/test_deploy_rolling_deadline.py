"""`deploy.sh` 의 겹쳐 바꾸기 기다림과 `verify` — 진짜 스크립트를 가짜 `docker` 로 돌린다(#1189).

2026-11-21 #1166 리허설(실제 docker): backend 의 새 컨테이너가 진입점에서 죽었는데, 겹쳐 바꾸기가
실패를 판정하기까지 245초를 기다렸다. 문구는 「150초」였다 — 한도를 시도 횟수(30)×간격(5초)으로
셌고, 시도마다 `docker exec` 가 몇 초씩 더 걸려 벽시계와 어긋났다. 새 컨테이너는 이미 재시작을
되풀이하고 있었는데도 끝까지 기다렸다.

같은 날 조사: `verify` 가 `compose ps -q`(실행 중인 것만)로 컨테이너를 찾고, 비면 「없다」만
찍고 넘어갔다 — 끝나 버린 컨테이너(exit)와 아예 없는 서비스가 통과했다(로컬 docker 에서 재현:
`restart: "no"` 로 끝난 서비스는 `ps -q` 에 안 보이고 `ps -a -q` 에만 보인다).

`rolling_replace` 는 `up` 한가운데서 불려 혼자 부를 명령이 없다 — 함수 본문을 스크립트에서 그대로
떼어 내 가짜 `docker` 와 함께 돌린다(고친 함수가 아니라 배포가 쓰는 바로 그 글자를 시험한다).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
DEPLOY_SH = REPO_ROOT / "deploy.sh"

# 상태는 파일로 둔다(`$STATE`) — 가짜는 부를 때마다 새로 뜨는 sh 다(파이썬이면 그것만으로 CPU 한도를 먹는다).
#   scaled       `up --scale` 뒤에는 `ps -q backend` 가 옛 것과 새 것 둘을 낸다
#   new_state    새 컨테이너의 `{{.State.Status}} {{.RestartCount}}` (기본 `running 0`)
#   old_state    옛 컨테이너의 같은 값 — 되돌리기에서는 옛 것이 죽은 판일 수 있다(#1206)
#   ready_after  `exec` 가 몇 번째 시도부터 성공하는가(없으면 늘 실패)
#   exec_delay   `exec` 한 번이 걸리는 초 — 리허설에서 본 「시도마다 몇 초 더」
#   calls        stop·rm·rename·logs 를 부른 기록
#   services     `config --services` 의 답, missing·exited 는 `verify` 시험의 서비스
FAKE_DOCKER = r"""#!/bin/sh
S=$STATE
case "$1" in
  inspect)
    case "$3" in
      *Name*) echo /codemit-prod-backend-1 ;;
      *RestartCount*)
        if [ "$4" = old ]; then cat "$S/old_state" 2>/dev/null || echo "running 0"
        else cat "$S/new_state" 2>/dev/null || echo "running 0"; fi ;;
      *State.Status*)
        svc=${4#cid-}
        if grep -qx "$svc" "$S/exited" 2>/dev/null; then echo exited; else echo running; fi ;;
    esac
    exit 0 ;;
  exec)
    sleep "$(cat "$S/exec_delay" 2>/dev/null || echo 0)"
    n=$(( $(cat "$S/exec_count" 2>/dev/null || echo 0) + 1 )); echo $n >"$S/exec_count"
    [ -f "$S/ready_after" ] && [ "$n" -ge "$(cat "$S/ready_after")" ] && exit 0
    exit 1 ;;
  stop|rm|rename|logs) echo "$*" >>"$S/calls"; exit 0 ;;
  compose) ;;
  *) exit 0 ;;
esac
shift
while [ $# -gt 0 ]; do
  case "$1" in -f|--env-file) shift 2 ;; *) break ;; esac
done
sub=$1; shift
case "$sub" in
  config) [ "$1" = --services ] && cat "$S/services" ;;
  up) case "$*" in *--scale*) touch "$S/scaled" ;; esac ;;
  ps)
    all=; [ "$1" = -a ] && { all=1; shift; }
    [ "$1" = -q ] && shift
    svc=$1
    if [ -f "$S/services" ]; then
      grep -qx "$svc" "$S/missing" 2>/dev/null && exit 0
      if grep -qx "$svc" "$S/exited" 2>/dev/null && [ -z "$all" ]; then exit 0; fi
      echo "cid-$svc"
    else
      echo old
      [ -f "$S/scaled" ] && echo new
    fi ;;
esac
exit 0
"""


def _function(src: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) {{\n.*?^}}\n", src, re.S | re.M)
    assert m, f"deploy.sh 에 {name}() 가 없다"
    return m.group(0)


@pytest.fixture
def fake(tmp_path: Path) -> dict[str, object]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER)
    (bindir / "docker").chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    src = DEPLOY_SH.read_text(encoding="utf-8")
    funcs = "".join(_function(src, n) for n in ("django_answers", "container_gave_up", "rolling_replace"))
    harness = tmp_path / "rolling.sh"
    harness.write_text(
        "set -eu\nCOMPOSE='docker compose -f c.yaml --env-file e'\nUP_FLAGS=''\n"
        'log() { echo "[deploy:prod] $*"; }\n' + funcs + "rolling_replace backend 8000 30\n"
    )
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "STATE": str(state)}
    return {"state": state, "env": env, "harness": harness, "tmp": tmp_path}


def _replace(fake: dict[str, object], **env: str) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    result = subprocess.run(
        ["sh", str(fake["harness"])],
        env={**fake["env"], **env},  # type: ignore[dict-item]
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, time.monotonic() - started


def _calls(state: Path) -> list[str]:
    f = state / "calls"
    return f.read_text().splitlines() if f.exists() else []


def test_기다림은_시도_횟수가_아니라_벽시계_마감으로_끝난다(fake):
    state: Path = fake["state"]  # type: ignore[assignment]
    # 시도 한 번이 간격만큼 걸린다 — 횟수로 세면 마감의 두 배를 기다린다.
    (state / "exec_delay").write_text("1")
    result, took = _replace(fake, ROLLING_READY_SECONDS="3", ROLLING_READY_INTERVAL="1")

    assert result.returncode == 1
    assert "backend 의 새 컨테이너가 3초 안에 응답하지 않았다" in result.stdout
    # 마감 + 걸려 있던 시도 하나 안에서 끝난다
    assert took < 5.5, took
    assert "rm -f new" in _calls(state)
    assert not any(c.startswith("stop") for c in _calls(state)), "옛 것은 그대로 둔다"


def test_새_컨테이너가_이미_죽었으면_마감까지_기다리지_않는다(fake):
    state: Path = fake["state"]  # type: ignore[assignment]
    (state / "new_state").write_text("restarting 2\n")
    result, took = _replace(fake, ROLLING_READY_INTERVAL="1")  # 마감은 기본 150초

    assert result.returncode == 1
    assert "backend 의 새 컨테이너가 죽었다(restarting, 재시작 2번)" in result.stdout
    assert took < 2.5, took
    assert "rm -f new" in _calls(state)
    assert not any(c.startswith("stop") for c in _calls(state))


def test_재시작이_한_번이라도_있었으면_running_이어도_죽은_것이다(fake):
    state: Path = fake["state"]  # type: ignore[assignment]
    (state / "new_state").write_text("running 1\n")
    result, _ = _replace(fake, ROLLING_READY_INTERVAL="1")

    assert result.returncode == 1
    assert "죽었다(running, 재시작 1번)" in result.stdout


def test_정상이면_첫_응답에서_바로_바꾼다(fake):
    state: Path = fake["state"]  # type: ignore[assignment]
    (state / "ready_after").write_text("2")
    result, took = _replace(fake, ROLLING_READY_INTERVAL="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "backend 바꿨다 (codemit-prod-backend-1)" in result.stdout
    assert _calls(state) == ["stop -t 30 old", "rm old", "rename new codemit-prod-backend-1"]
    # 두 번째 시도에서 응답 — 간격 한 번(1초)만 기다렸다
    assert took < 2.5, took
    assert re.search(r"backend 옛 것을 내렸다 — 따뜻한 종료 \d+초", result.stdout), result.stdout


@pytest.mark.parametrize("old_state", ["restarting 3\n", "running 2\n", "exited 0\n"])
def test_옛_컨테이너가_이미_죽었으면_유예_없이_지운다(fake, old_state):
    """되돌리기에서 옛 것은 방금 실패한 판일 수 있다(#1206) — 받던 요청이 없으니 따뜻한 종료를 기다리지 않는다."""
    state: Path = fake["state"]  # type: ignore[assignment]
    (state / "ready_after").write_text("1")
    (state / "old_state").write_text(old_state)
    result, _ = _replace(fake, ROLLING_READY_INTERVAL="1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _calls(state) == ["rm -f old", "rename new codemit-prod-backend-1"]
    assert f"backend 옛 것이 이미 죽었다({old_state.split()[0]}, 재시작 {old_state.split()[1]}번) — 유예 없이 지운다" in result.stdout


# ---------------------------------------------------------------- verify

SERVICES = ("db", "redis", "backend", "frontend", "agent-grader")


def _verify(fake: dict[str, object], *, missing: tuple[str, ...] = (), exited: tuple[str, ...] = ()):
    state: Path = fake["state"]  # type: ignore[assignment]
    tmp: Path = fake["tmp"]  # type: ignore[assignment]
    (state / "services").write_text("\n".join(SERVICES) + "\n")
    (state / "missing").write_text("".join(f"{s}\n" for s in missing))
    (state / "exited").write_text("".join(f"{s}\n" for s in exited))
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    shutil.copy(DEPLOY_SH, repo / "deploy.sh")
    return subprocess.run(
        ["sh", str(repo / "deploy.sh"), "prod", "verify"],
        env=fake["env"],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_verify_는_다_떠_있으면_통과한다(fake):
    result = _verify(fake)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "컨테이너 전부 running (5개 서비스)" in result.stdout


def test_verify_는_아예_없는_서비스를_실패로_본다(fake):
    result = _verify(fake, missing=("agent-grader",))
    assert result.returncode == 1
    assert "[agent-grader] 컨테이너가 없다" in result.stdout


def test_verify_는_끝나버린_컨테이너를_실패로_본다(fake):
    # `ps -q`(실행 중인 것만)에는 안 보이고 `ps -a -q` 에만 보이는 컨테이너
    result = _verify(fake, exited=("frontend",))
    assert result.returncode == 1
    assert "[frontend] 상태가 running 이 아니다: exited" in result.stdout
