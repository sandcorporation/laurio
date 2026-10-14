#!/usr/bin/env python3
"""`scripts/ci/ghcr_prune.py` 가 살아 있는 커밋의 이미지를 지우지 않는지 고정한다(#705).

`python3 scripts/test_ghcr_prune.py` — 표준 라이브러리만, 네트워크 없음.

바뀌지 않은 서비스는 옛 매니페스트에 커밋 태그만 더해지므로, 지금 배포된 커밋의 이미지가 오래전에
만든 버전일 수 있다. 만든 순서로만 자르면 그것을 지운다.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ci"))

import ghcr_prune as gp  # noqa: E402

LIVE = "a" * 40


def version(n: int, tags: list[str], updated: str | None = None) -> dict:
    created = f"2026-10-{n:02d}T00:00:00Z"
    return {"id": n, "created_at": created, "updated_at": updated or created, "metadata": {"container": {"tags": tags}}}


class Doomed(unittest.TestCase):
    def test_keeps_newest_and_drops_the_rest(self) -> None:
        listed = [version(n, [f"{n}-amd64"]) for n in range(1, 6)]
        self.assertEqual([v["id"] for v in gp.doomed_versions(listed, 2, [])], [3, 2, 1])

    def test_an_old_version_holding_a_live_commit_tag_survives(self) -> None:
        listed = [version(1, ["ctx-x-amd64", f"{LIVE}-amd64"])] + [version(n, [f"{n}-amd64"]) for n in range(2, 6)]
        self.assertEqual([v["id"] for v in gp.doomed_versions(listed, 2, [LIVE])], [3, 2])

    def test_a_recently_retagged_version_counts_as_recent(self) -> None:
        listed = [version(1, ["ctx-x-amd64"], updated="2026-10-30T00:00:00Z")] + [
            version(n, [f"{n}-amd64"]) for n in range(2, 6)
        ]
        self.assertNotIn(1, [v["id"] for v in gp.doomed_versions(listed, 2, [])])


if __name__ == "__main__":
    unittest.main()
