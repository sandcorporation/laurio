#!/usr/bin/env python3
"""`glitchtip_pick.py` 의 청소가 「병합됐는가」를 바르게 가르는지 고정한다(2026-10-03).

`python3 scripts/test_glitchtip_pick.py` 하나로 돈다 — 표준 라이브러리 `unittest` 와
임시 git 저장소만 쓴다(네트워크·토큰 없음).

고정하는 사실: 2026-10-02 부터 Jenkins 가 PR 을 **rebase 병합**해 `main` 의 커밋 sha 가
분기와 다르다. 옛 판정(`merge-base --is-ancestor`)은 병합된 자동 진단 분기를 영영
「머지 안 됨」으로 봤고, 반대로 커밋 없는 분기는 `main` 이 앞서 나가면 「머지됨」으로 봐
도는 세션의 워크트리를 걷을 수 있었다(#459 의 모양).
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest

import glitchtip_pick as gp


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: pathlib.Path, name: str, text: str) -> None:
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"{name}: {text}")


class BranchStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        _commit(self.repo, "a.txt", "1")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _publish_main(self) -> None:
        _git(self.repo, "update-ref", "refs/remotes/origin/main", "main")

    def test_rebase_merged_branch_is_merged(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "auto-x")
        _commit(self.repo, "fix.txt", "fix")
        # main 이 앞서 나간 뒤, 그 위로 분기 커밋을 다시 얹는다 — rebase 병합의 모양.
        _git(self.repo, "checkout", "-q", "main")
        _commit(self.repo, "other.txt", "other")
        _git(self.repo, "cherry-pick", "auto-x")
        self._publish_main()
        # 옛 판정이 실패하던 바로 그 조건이다.
        ancestor = subprocess.run(
            ["git", "-C", str(self.repo), "merge-base", "--is-ancestor", "auto-x", "origin/main"]
        ).returncode
        self.assertNotEqual(ancestor, 0)
        self.assertEqual(gp._branch_state(self.repo, "auto-x"), "merged")

    def test_unmerged_branch_is_kept(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "auto-x")
        _commit(self.repo, "fix.txt", "fix")
        _git(self.repo, "checkout", "-q", "main")
        self._publish_main()
        self.assertEqual(gp._branch_state(self.repo, "auto-x"), "unmerged")

    def test_partly_merged_branch_is_kept(self) -> None:
        _git(self.repo, "checkout", "-q", "-b", "auto-x")
        _commit(self.repo, "fix.txt", "fix")
        _commit(self.repo, "more.txt", "more")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "cherry-pick", "auto-x~1")
        self._publish_main()
        self.assertEqual(gp._branch_state(self.repo, "auto-x"), "unmerged")

    def test_fresh_branch_is_empty_even_after_main_moves_on(self) -> None:
        """막 만들어진 세션 분기 — main 이 앞서 나가도 「머지됨」이 아니라 「빔」이다."""

        _git(self.repo, "branch", "auto-x")
        _commit(self.repo, "other.txt", "other")
        self._publish_main()
        self.assertEqual(gp._branch_state(self.repo, "auto-x"), "empty")

    def test_unknown_branch_is_kept(self) -> None:
        self._publish_main()
        self.assertEqual(gp._branch_state(self.repo, "auto-missing"), "unmerged")


class ProjectFilterTest(unittest.TestCase):
    """조직 단위 이슈 목록에는 다른 제품의 프로젝트도 섞인다 — slug 접두어로 가른다."""

    def test_codemit_projects_are_ours(self) -> None:
        for slug in ("codemit-backend", "codemit-classroom", "codemit-frontend", "codemit-operator"):
            self.assertTrue(gp._is_ours({"project": {"slug": slug}}), slug)

    def test_other_products_are_not_ours(self) -> None:
        self.assertFalse(gp._is_ours({"project": {"slug": "daypage"}}))
        self.assertFalse(gp._is_ours({"project": {"slug": "daypage-frontend"}}))

    def test_missing_project_is_not_ours(self) -> None:
        self.assertFalse(gp._is_ours({}))
        self.assertFalse(gp._is_ours({"project": None}))


class AutomationBranchTest(unittest.TestCase):
    """Orca 가 분기 이름 앞에 사용자 접두어를 붙여도 자동 진단 분기를 알아본다."""

    def test_bare_and_prefixed_names(self) -> None:
        self.assertTrue(gp._is_automation_branch("auto-glitchtip-prod-run-1-20261019T0513"))
        self.assertTrue(gp._is_automation_branch("farrar142/auto-glitchtip-prod-run-1-20261019T0513"))

    def test_human_worktrees_are_left_alone(self) -> None:
        for name in ("main", "chain-3", "int-2", "farrar142/guitarfish", "t755-test-db-template-clone"):
            self.assertFalse(gp._is_automation_branch(name), name)


if __name__ == "__main__":
    unittest.main()
