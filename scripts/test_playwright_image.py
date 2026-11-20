"""e2e 의 Playwright 이미지(scripts/ci/playwright_image.py, #1109) — 판이 lockfile 과 같고 다이제스트로 고정됐을 때만 쓴다."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "ci"))

import playwright_image  # noqa: E402
from playwright_image import Mismatch, checked_ref  # noqa: E402

DIGEST = "sha256:" + "a" * 64
LOCK = "  '@playwright/test@1.62.1':\n    resolution: {}\n  /@playwright/test@1.62.1(x):\n"


class ThisRepo(unittest.TestCase):
    def test_the_pinned_image_matches_the_lockfile(self) -> None:
        out = subprocess.run([sys.executable, str(Path(playwright_image.__file__))], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), playwright_image.REF_FILE.read_text().strip())

    def test_the_workflow_runs_e2e_in_the_image_without_installing_system_packages(self) -> None:
        pr = (playwright_image.ROOT / ".github/workflows/pr-check.yml").read_text()
        self.assertIn("CODEMIT_E2E_PLAYWRIGHT_IMAGE: 1", pr)
        self.assertNotIn("--with-deps", pr)
        self.assertNotIn("install-deps", pr)


class Check(unittest.TestCase):
    def test_same_version_and_digest_passes(self) -> None:
        ref = f"mcr.microsoft.com/playwright:v1.62.1-noble@{DIGEST}"
        self.assertEqual(checked_ref(ref + "\n", LOCK), ref)

    def test_other_version_fails(self) -> None:
        with self.assertRaisesRegex(Mismatch, "1.61.0 ≠ lockfile 의 @playwright/test 1.62.1"):
            checked_ref(f"mcr.microsoft.com/playwright:v1.61.0-noble@{DIGEST}", LOCK)

    def test_two_locked_versions_fail(self) -> None:
        with self.assertRaises(Mismatch):
            checked_ref(f"mcr.microsoft.com/playwright:v1.62.1-noble@{DIGEST}", LOCK + "  '@playwright/test@1.63.0':\n")

    def test_tag_without_digest_fails(self) -> None:
        with self.assertRaisesRegex(Mismatch, "꼴이 아니다"):
            checked_ref("mcr.microsoft.com/playwright:v1.62.1-noble", LOCK)

    def test_other_registry_fails(self) -> None:
        with self.assertRaises(Mismatch):
            checked_ref(f"docker.io/someone/playwright:v1.62.1-noble@{DIGEST}", LOCK)

    def test_lockfile_without_playwright_fails(self) -> None:
        with self.assertRaisesRegex(Mismatch, "판이 없다"):
            checked_ref(f"mcr.microsoft.com/playwright:v1.62.1-noble@{DIGEST}", "lockfileVersion: '9.0'\n")


if __name__ == "__main__":
    unittest.main()
