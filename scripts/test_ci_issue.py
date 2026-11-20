#!/usr/bin/env python3
"""`scripts/ci/ci-issue.sh` 의 담당 지정을 고정한다(#1113). `python3 scripts/test_ci_issue.py` 하나로 돈다. 가짜 gh 를 PATH 앞에 둔다."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ci" / "ci-issue.sh"

# 호출을 한 줄씩 CALLS 에 남긴다. FAKE_OPEN=1 이면 열린 이슈 7 이 있고, FAKE_ASSIGNED=1 이면 담당이 있다.
FAKE_GH = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$1 $2" in
  "issue list") [ "${FAKE_OPEN:-0}" = 1 ] && echo 7 ;;
  "issue view") [ "${FAKE_ASSIGNED:-0}" = 1 ] && echo 1 || echo 0 ;;
  "issue create") echo "https://github.com/o/r/issues/9" ;;
  "issue edit") [ "${FAKE_EDIT_FAIL:-0}" = 1 ] && exit 1 ;;
esac
exit 0
"""


class CiIssue(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "bin").mkdir()
        gh = d / "bin" / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.calls = d / "calls"
        self.calls.touch()
        self.summary = d / "summary"
        self.summary.touch()
        self.d = d

    def run_script(self, mode: str, **env: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        full = {
            "PATH": f"{self.d / 'bin'}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "HOME": str(self.d),
            **env,
        }
        r = subprocess.run(["bash", str(SCRIPT), mode, "제목", "본문"], env=full, text=True, capture_output=True)
        return r, self.calls.read_text().splitlines()

    def test_new_issue_with_assignee(self) -> None:
        r, calls = self.run_script("fail", CI_RED_ASSIGNEE="someone")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c.startswith("issue create") and "--assignee" not in c for c in calls))
        self.assertIn("issue edit 9 --add-assignee someone", calls)

    def test_new_issue_without_variable_warns(self) -> None:
        r, calls = self.run_script("fail", CI_RED_ASSIGNEE="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c.startswith("issue create") for c in calls))
        self.assertFalse(any(c.startswith("issue edit") for c in calls))
        self.assertIn("CI_RED_ASSIGNEE", self.summary.read_text())

    def test_assign_failure_keeps_issue(self) -> None:
        r, calls = self.run_script("fail", CI_RED_ASSIGNEE="nobody", FAKE_EDIT_FAIL="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c.startswith("issue create") for c in calls))
        self.assertIn("::warning::", r.stdout)

    def test_comment_on_open_issue_assigns_when_empty(self) -> None:
        r, calls = self.run_script("fail", CI_RED_ASSIGNEE="someone", FAKE_OPEN="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c.startswith("issue comment 7") for c in calls))
        self.assertFalse(any(c.startswith("issue create") for c in calls))
        self.assertIn("issue edit 7 --add-assignee someone", calls)

    def test_comment_on_open_issue_keeps_existing_assignee(self) -> None:
        r, calls = self.run_script("fail", CI_RED_ASSIGNEE="someone", FAKE_OPEN="1", FAKE_ASSIGNED="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(any(c.startswith("issue edit") for c in calls))

    def test_ok_comments_then_closes(self) -> None:
        r, calls = self.run_script("ok", CI_RED_ASSIGNEE="someone", FAKE_OPEN="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c.startswith("issue comment 7") for c in calls))
        self.assertIn("issue close 7", calls)
        self.assertFalse(any(c.startswith("issue edit") for c in calls))


if __name__ == "__main__":
    unittest.main()
