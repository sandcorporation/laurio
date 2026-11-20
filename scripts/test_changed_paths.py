"""scripts/ci/changed.sh 경로 표 — 바뀐 파일이 어느 잡을 돌리는가(#1082).

임시 git 저장소에 파일을 바꿔 커밋하고 changed.sh 를 돌려 TESTS·BACK·FRONT 를 읽는다.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ci" / "changed.sh"


def plan(*paths: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()

        git("init", "-q")
        (root / "seed").write_text("x")
        git("add", "-A")
        git("commit", "-q", "-m", "seed")
        base = git("rev-parse", "HEAD")
        for p in paths:
            f = root / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("y")
        git("add", "-A")
        git("commit", "-q", "--allow-empty", "-m", "change")
        out = subprocess.run(["bash", str(SCRIPT), base], cwd=root, check=True, capture_output=True, text=True).stdout
    return dict(line.split("=", 1) for line in out.split())


class ChangedPathsTest(unittest.TestCase):
    def check(self, paths: tuple[str, ...], tests: str, back: str, front: str) -> None:
        self.assertEqual(plan(*paths), {"TESTS": tests, "BACK": back, "FRONT": front}, paths)

    def test_docs_only_runs_nothing(self) -> None:
        self.check(("docs/a.md", "README.md"), "0", "0", "0")

    def test_frontend_only_runs_web_not_backend(self) -> None:
        for p in ("frontend/a.ts", "operator/a.ts", "classroom/a.ts", "packages/ui/a.ts"):
            self.check((p, "docs/a.md"), "1", "0", "1")

    def test_backend_only_runs_backend_not_web(self) -> None:
        for p in ("backend/a.py", "backend/uv.lock", "docker/backend.Dockerfile"):
            self.check((p,), "1", "1", "0")

    def test_both_sides(self) -> None:
        self.check(("backend/a.py", "frontend/a.ts"), "1", "1", "1")

    def test_common_paths_run_everything(self) -> None:
        for p in (".github/workflows/pr-check.yml", "scripts/ci/changed.sh", "pnpm-lock.yaml", "Makefile"):
            self.check((p,), "1", "1", "1")

    def test_unknown_base_or_no_diff_runs_everything(self) -> None:
        all_on = {"TESTS": "1", "BACK": "1", "FRONT": "1"}
        out = subprocess.run(["bash", str(SCRIPT)], check=True, capture_output=True, text=True).stdout
        self.assertEqual(dict(line.split("=", 1) for line in out.split()), all_on)
        self.assertEqual(plan(), all_on)


if __name__ == "__main__":
    unittest.main()
