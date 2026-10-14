"""`deploy.sh plan` 이 세 앱의 실행 env 어긋남을 견주는 자리(`app_env_drifted`, #711·#727) — 진짜 스크립트를 돌린다.

앱 이미지는 환경을 모르고 공개 값(`CODEMIT_PUBLIC_*`)은 compose 가 `.env.<target>` 에서 넣는다. 그 파일은
gitignore 라 git diff 로는 값이 바뀐 것을 못 보므로, `plan` 은 떠 있는 컨테이너의 compose 설정 해시
(`com.docker.compose.config-hash`)를 **그 컨테이너의 이미지 태그·release 로 다시 낸** 지금 해시와 견준다.

여기서 고정하는 셋:
- env 가 그대로면 코드가 안 바뀐 앱은 다시 뜨지 않는다 — 커밋마다 바뀌는 태그·release 를 옛 값으로 고정해
  견주기 때문이다(고정하지 않으면 「늘 다르다」가 되어 매 배포 세 앱이 다 뜬다).
- 한 앱의 env 만 바뀌면 그 앱만 다시 뜬다.
- `config --hash` 가 실패하면 삼키지 않는다 — 메시지를 로그에 남기고 다시 띄운다(예전에는 「어긋나지 않음」).

가짜 `docker` 의 해시는 `<이미지 태그>/<release>/<그 앱의 env>` 다 — compose 가 렌더한 정의에서 env 와
이미지가 해시에 드는 모양을 흉내 낸다. 떠 있는 컨테이너는 옛 커밋(`oldsha`)으로 떠 있다.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.test_deploy_plan_rolling import _prepare

APPS = ("frontend", "operator", "classroom")

FAKE_DOCKER = """#!/bin/sh
state="$FAKE_DOCKER_STATE"
if [ "$1" = inspect ]; then
  svc=${4#cid-}
  case "$3" in
    *Config.Image*) echo "ghcr.io/sandcorporation/codemit-$svc:oldsha-amd64" ;;
    *Config.Env*) printf 'PORT=3000\\nCODEMIT_PUBLIC_SENTRY_RELEASE=oldsha\\n' ;;
    *config-hash*) cat "$state/label-$svc" 2>/dev/null ;;
  esac
  exit 0
fi
[ "$1" = compose ] || exit 0
shift
while [ $# -gt 0 ]; do
  case "$1" in
    -f|--env-file) shift 2 ;;
    -*) shift ;;
    *) break ;;
  esac
done
case "$1" in
  ps) [ "$2" = -q ] && echo "cid-$3" ;;
  config)
    [ "$2" = --hash ] || exit 0
    if [ -e "$state/hash-fails" ]; then echo "service \\"$3\\" refers to undefined network edge" >&2; exit 15; fi
    if [ -e "$state/env-$3" ]; then echo "$3 $CODEMIT_IMAGE_TAG/$SENTRY_RELEASE/$(cat "$state/env-$3")"; fi
    ;;
esac
exit 0
"""


def _prepare_app_env(tmp_path, *, env_now: dict[str, str] | None = None, hash_fails: bool = False):
    """세 앱이 옛 커밋으로, env `v1` 로 떠 있다. `env_now` 는 지금 `.env.<target>` 이 주는 값."""
    # 앱 코드는 안 바뀐 커밋 — 이미지 문맥 밖(e2e 설정) 파일만 바꾼다.
    repo, env = _prepare(tmp_path, lambda compose: compose, touch=("frontend/playwright.config.ts",))
    (tmp_path / "bin" / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    for app in APPS:
        (state / f"label-{app}").write_text("oldsha/oldsha/v1\n", encoding="utf-8")
        (state / f"env-{app}").write_text((env_now or {}).get(app, "v1"), encoding="utf-8")
    if hash_fails:
        (state / "hash-fails").touch()
    return repo, {**env, "FAKE_DOCKER_STATE": str(state)}


def _plan(prepared) -> tuple[dict[str, str], str]:
    repo, env = prepared
    result = subprocess.run(
        ["sh", "deploy.sh", "prod", "plan"], cwd=repo, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = (repo / ".jenkins-prod-plan").read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in plan.splitlines() if "=" in line), result.stdout


@pytest.fixture
def env_unchanged(tmp_path):
    return _prepare_app_env(tmp_path)


def test_apps_whose_code_and_env_are_unchanged_are_not_restarted(env_unchanged):
    plan, out = _plan(env_unchanged)

    assert [plan[f"BUILD_{app.upper()}"] for app in APPS] == ["false", "false", "false"]
    assert "실행 설정" not in out


@pytest.fixture
def operator_env_changed(tmp_path):
    return _prepare_app_env(tmp_path, env_now={"operator": "v2"})


def test_an_app_whose_env_changed_is_the_only_one_restarted(operator_env_changed):
    plan, out = _plan(operator_env_changed)

    assert plan["BUILD_OPERATOR"] == "true"
    assert plan["BUILD_FRONTEND"] == "false"
    assert plan["BUILD_CLASSROOM"] == "false"
    assert "operator 의 실행 설정이" in out


@pytest.fixture
def hash_fails(tmp_path):
    return _prepare_app_env(tmp_path, hash_fails=True)


def test_a_failing_config_hash_is_logged_and_restarts_instead_of_passing_silently(hash_fails):
    plan, out = _plan(hash_fails)

    assert [plan[f"BUILD_{app.upper()}"] for app in APPS] == ["true", "true", "true"]
    assert "undefined network edge" in out
