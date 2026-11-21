#!/usr/bin/env python3
"""pre-commit 훅이 부르는 백엔드 빠른 검사가 세 실수를 거절하는지 본다(#1226).

닫히지 않은 docstring · 금칙어 표에 없는 새 입력 필드 · Django 검사 실패를 각각 backend 파일에 심고,
임시 index(`GIT_INDEX_FILE`)에만 올려 검사 스크립트를 직접 돌린다 — 실제 index·커밋은 건드리지 않는다. 심은 줄은
끝에서 되돌린다. 마지막에 아무것도 심지 않은 변경은 통과하는지(훅이 모든 것을 막지 않는지)도 본다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "pre_commit_backend_checks.sh"

CASES = {
    "닫히지 않은 docstring": ("backend/core/clock.py", '\n\ndef _probe():\n    """닫히지 않는다\n    return 1\n', "문법 오류"),
    "금칙어 표에 없는 입력 필드": (
        "backend/core/api.py",
        "\n\nimport ninja as _probe_ninja  # noqa: E402\n\n\nclass HookProbeIn(_probe_ninja.Schema):\n    reason: str\n",
        "test_every_scanned_field_is_registered",
    ),
    "Django 검사 실패": (
        "backend/core/checks.py",
        "\n\nfrom django.core.checks import Warning as _ProbeWarning, register as _probe_register  # noqa: E402\n\n\n"
        "@_probe_register()\ndef _hook_probe_check(app_configs, **kwargs):\n"
        "    return [_ProbeWarning('hook probe', id='probe.W001')]\n",
        "probe.W001",
    ),
}


def run_hook(index: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_INDEX_FILE": index}
    env.pop("CODEMIT_UNATTENDED", None)
    return subprocess.run(["bash", str(HOOK)], cwd=ROOT, env=env, capture_output=True, text=True)


def main() -> int:
    git_index = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "index"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        index = os.path.join(tmp, "index")
        for name, (rel, addition, expect) in CASES.items():
            shutil.copy(git_index, index)
            path = ROOT / rel
            original = path.read_bytes()
            try:
                path.write_bytes(original + addition.encode())
                subprocess.run(["git", "add", rel], cwd=ROOT, check=True, env={**os.environ, "GIT_INDEX_FILE": index})
                result = run_hook(index)
            finally:
                path.write_bytes(original)
            out = result.stdout + result.stderr
            ok = result.returncode != 0 and expect in out
            print(f"{'ok  ' if ok else 'FAIL'} {name} (종료 {result.returncode})")
            if not ok:
                failures.append(f"{name}\n{out[-1500:]}")
        # 아무것도 심지 않고 파일 하나만 다시 올린 변경은 통과한다
        shutil.copy(git_index, index)
        os.utime(ROOT / "backend/core/clock.py")
        subprocess.run(["git", "add", "-f", "--intent-to-add", "backend/core/clock.py"], cwd=ROOT, env={**os.environ, "GIT_INDEX_FILE": index})
        # staged 목록이 비면 훅이 건너뛰므로, 깨끗한 변경은 빈 줄 하나를 더해 올린다
        path = ROOT / "backend/core/clock.py"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"\n")
            subprocess.run(["git", "add", "backend/core/clock.py"], cwd=ROOT, check=True, env={**os.environ, "GIT_INDEX_FILE": index})
            result = run_hook(index)
        finally:
            path.write_bytes(original)
        ok = result.returncode == 0
        print(f"{'ok  ' if ok else 'FAIL'} 깨끗한 변경은 통과 (종료 {result.returncode})")
        if not ok:
            failures.append("깨끗한 변경\n" + (result.stdout + result.stderr)[-1500:])
    for f in failures:
        print("---\n" + f, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
