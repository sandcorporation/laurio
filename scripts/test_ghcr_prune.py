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

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import ghcr_prune as gp  # noqa: E402
import image_context  # noqa: E402

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



class Unmerged(unittest.TestCase):
    """병합되지 않은 묶음의 이미지(main 에 없는 쌓은 sha, ctx 없음)를 순서보다 먼저 지운다(#729)."""

    MAIN = {"1" * 40, "2" * 40}
    NOW = gp.datetime.datetime(2026, 10, 31, tzinfo=gp.datetime.timezone.utc)

    def doomed(self, listed: list[dict], keep: int = 2, main=None) -> list[int]:
        return [v["id"] for v in gp.doomed_versions(listed, keep, [], self.MAIN if main is None else main, now=self.NOW)]

    def test_red_bundles_go_first_and_do_not_take_the_window(self) -> None:
        # 최근 셋이 붉은 묶음(쌓은 sha) — 예전 규칙은 main 커밋 1·2 를 밀어냈다.
        listed = [version(1, ["1" * 40 + "-arm64"]), version(2, ["2" * 40 + "-arm64"])] + [
            version(n, [f"{n}" * 40 + "-arm64"]) for n in (3, 4, 5)
        ]
        self.assertEqual(sorted(self.doomed(listed)), [3, 4, 5])

    def test_a_ctx_tag_keeps_it_in_the_order(self) -> None:
        # 초록 묶음 — 병합 전에 ctx 가 붙었다. 재사용될 이미지라 순서로만 센다.
        listed = [version(1, ["1" * 40 + "-arm64"]), version(5, ["5" * 40 + "-arm64", "ctx-h-arm64"])]
        self.assertEqual(self.doomed(listed), [])

    def test_a_version_also_holding_a_main_tag_is_not_unmerged(self) -> None:
        listed = [version(5, ["5" * 40 + "-arm64", "2" * 40 + "-arm64"])]
        self.assertEqual(self.doomed(listed, keep=0), [5])  # 순서로는 지워진다(keep 0) — 먼저 지울 것은 아니다
        self.assertFalse(gp.unmerged(listed[0], self.MAIN))

    def test_a_train_still_running_is_left_alone(self) -> None:
        listed = [version(30, ["3" * 40 + "-arm64"], updated="2026-10-30T22:00:00Z")]
        self.assertEqual(self.doomed(listed), [])
        listed = [version(30, ["3" * 40 + "-arm64"], updated="2026-10-30T23:59:00Z"), version(1, ["1" * 40 + "-arm64"])]
        self.assertEqual(self.doomed(listed, keep=5), [])  # 30-23:59 는 유예 6시간 안이다

    def test_without_a_main_list_it_only_orders(self) -> None:
        listed = [version(n, [f"{n}" * 40 + "-arm64"]) for n in (3, 4, 5)]
        self.assertEqual(self.doomed(listed, keep=3, main=set()), [])

    def test_the_prune_job_passes_the_main_list(self) -> None:
        jenkinsfile = (ROOT / "Jenkinsfile.ghcr-prune").read_text()
        self.assertIn("--main-shas .prune-main", jenkinsfile)


class Packages(unittest.TestCase):
    def test_prune_walks_every_image_the_build_pushes(self) -> None:
        # 어긋나면 새 서비스의 빌드 캐시 태그가 LIVE_CACHE_TAG 에 안 걸려 매일 「옛 이름」으로 지워진다.
        self.assertEqual({i.removeprefix("codemit-") for i in gp.IMAGES}, set(image_context.SERVICES))


if __name__ == "__main__":
    unittest.main()
