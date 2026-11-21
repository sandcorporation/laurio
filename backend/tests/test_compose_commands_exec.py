"""compose 의 `sh -c` 명령은 마지막 장기 실행 명령을 `exec` 한다(#1170).

PID 1 인 sh 는 SIGTERM 을 자식에게 넘기지 않고, `a && b && c` 사슬의 마지막 명령을
exec 하지도 않는다. 그러면 `docker stop` 이 유예(기본 10초)를 다 채운 뒤 SIGKILL 하고,
gunicorn 은 진행 중 요청을 마무리하지 못한 채 죽는다 — 겹쳐 바꾸기에서 옛 backend 를
내리는 순간 받던 요청이 끊긴다. `exec` 로 바꾸면 그 프로세스가 PID 1 이 되어 신호를
직접 받는다(로컬 실측: `compose stop backend` 12.5초 → 0.13초).
"""

from __future__ import annotations

import shlex

import pytest
import yaml
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
COMPOSE_FILES = sorted((REPO_ROOT / "docker").glob("compose*.yaml"))


class _ComposeLoader(yaml.SafeLoader):
    """compose 의 `!reset`·`!override`(덮어쓰기 표식)를 그 값 그대로 읽는다."""


def _as_is(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)  # type: ignore[arg-type]  # 남은 것은 ScalarNode 다


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _as_is)


def _shell_commands() -> list[tuple[str, str, str]]:
    """(파일, 서비스·키, sh -c 에 넘기는 스크립트) — 문자열 명령 중 `sh -c` 인 것만."""
    found: list[tuple[str, str, str]] = []
    for path in COMPOSE_FILES:
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
        for name, service in (doc.get("services") or {}).items():
            for key in ("command", "entrypoint"):
                value = (service or {}).get(key)
                if not isinstance(value, str):
                    continue
                argv = shlex.split(value)
                if argv[:2] == ["sh", "-c"]:
                    found.append((path.name, f"{name}.{key}", argv[2]))
    return found


SHELL_COMMANDS = _shell_commands()


def test_the_scan_sees_the_long_running_services():
    seen = {(f, s) for f, s, _ in SHELL_COMMANDS}
    for expected in [
        ("compose.prod.yaml", "backend.command"),
        ("compose.prod.yaml", "events.command"),
        ("compose.ci.yaml", "backend.command"),
        ("compose.dev.yaml", "backend.command"),
        ("compose.dev.yaml", "events.command"),
    ]:
        assert expected in seen


@pytest.mark.parametrize(("file", "where", "script"), SHELL_COMMANDS, ids=[f"{f}:{s}" for f, s, _ in SHELL_COMMANDS])
def test_the_last_command_of_a_shell_chain_is_execed(file, where, script):
    last = script.split("&&")[-1].strip()
    assert last.startswith("exec "), f"{file} {where}: 마지막 명령을 exec 로 — {last[:60]!r}"
