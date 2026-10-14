#!/usr/bin/env python3
"""`scripts/ci/e2e_stall.py` 와 `train.py fail` 의 인프라 분기 — Docker VM 정지를 인프라 고장으로 가른다(#716).

`python3 scripts/test_e2e_stall.py` 하나로 돈다 — 표준 라이브러리 `unittest` 와 임시 폴더만 쓴다
(네트워크·도커 없음). PR CI 의 sub 검사가 돌린다(`scripts/ci/sub-checks-inside.sh`).

픽스처는 열차 #1890(2026-10-15, 강의실 e2e 넷이 3초 한도에 걸린 빌드)의 산출물에서 그대로 옮긴 줄이다
— backend 접근 로그의 3.9초 틈 앞뒤와, 실패한 시험의 `test.trace` 첫 줄·`error-context.md` 의 오류.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import e2e_stall  # noqa: E402
import train  # noqa: E402

# 열차 #1890 의 backend.log 1627~1631 줄 — 19:48:42.667 → 46.544 사이에 접근 로그가 없다.
BACKEND_1890 = """\
backend-1  | 2026-10-14T19:48:36.076343801Z [2026-10-15 04:48:36,076] INFO celery.app.trace: Task contests.index_contest[67d8ddd1] succeeded
backend-1  | 2026-10-14T19:48:42.635970804Z GET /api/accounts/me HTTP/1.1 401 26 0ms pid=<13>
backend-1  | 2026-10-14T19:48:42.648139054Z POST /api/auth/social/kakao/login HTTP/1.1 200 494 11ms pid=<13>
backend-1  | 2026-10-14T19:48:42.667323596Z POST /api/classroom/classes/12/copy HTTP/1.1 201 969 18ms pid=<13>
backend-1  | 2026-10-14T19:48:46.544804542Z POST /api/classroom/oauth/register HTTP/1.1 201 305 12ms pid=<12>
backend-1  | 2026-10-14T19:48:46.553338708Z POST /api/auth/social/kakao/login HTTP/1.1 200 494 20ms pid=<11>
"""
# 넷 중 가장 이른 시험(19:48:42.308 시작 → 45.308 마감)과 가장 늦은 시험(42.784 → 45.784).
TRACE_HEADS_1890 = [1792007322308, 1792007322784]
TIMEOUT_1890 = """\
# Test info

- Name: e2e/classroom/instructors-tab.spec.ts >> 강사 탭 — 소유자가 초대 링크를 만들고 소유권을 넘기겠다 요청했다가 취소한다

# Error details

```
Test timeout of 3000ms exceeded.
```
"""
ASSERTION = TIMEOUT_1890.replace("Test timeout of 3000ms exceeded.", "Error: expect(locator).toBeVisible() failed")


def trace_head(wall_ms: int) -> str:
    return json.dumps({"version": 8, "type": "context-options", "origin": "testRunner", "wallTime": wall_ms,
                       "monotonicTime": 2582.424, "testTimeout": 3000})


def results(root: pathlib.Path, backend: str = BACKEND_1890, tests=None, last_run_failed=None) -> pathlib.Path:
    """열차 산출물 모양의 test-results 를 만든다 — tests 는 (시작 wallTime ms, error-context 본문)."""
    tests = [(wall, TIMEOUT_1890) for wall in TRACE_HEADS_1890] if tests is None else tests
    out = root / "test-results"
    (out / "stack").mkdir(parents=True)
    (out / "stack" / "backend.log").write_text(backend)
    project = out / "playwright" / "classroom"
    project.mkdir(parents=True)
    (project / ".last-run.json").write_text(json.dumps({
        "status": "failed" if tests else "passed",
        "failedTests": [f"id-{i}" for i in range(len(tests) if last_run_failed is None else last_run_failed)],
    }))
    for index, (wall, error) in enumerate(tests):
        folder = project / f"spec-{index}-classroom"
        folder.mkdir()
        (folder / "error-context.md").write_text(error)
        with zipfile.ZipFile(folder / "trace.zip", "w") as archive:
            archive.writestr("test.trace", trace_head(wall) + "\n{\"type\":\"before\"}\n")
    return out


class AccessLog(unittest.TestCase):
    def test_finds_the_1890_gap_and_ignores_celery_lines(self) -> None:
        times = e2e_stall.access_times(BACKEND_1890.splitlines())
        self.assertEqual(len(times), 5)
        gaps = e2e_stall.quiet_gaps(times)
        self.assertEqual(len(gaps), 1)
        start, end = gaps[0]
        self.assertEqual(e2e_stall.iso(start), "2026-10-14T19:48:42.667Z")
        self.assertAlmostEqual(end - start, 3.877, places=3)

    def test_a_short_pause_is_not_a_gap(self) -> None:
        times = e2e_stall.access_times(BACKEND_1890.replace("19:48:46.5", "19:48:44.5").splitlines())
        self.assertEqual(e2e_stall.quiet_gaps(times), [])


class Classify(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_1890_is_an_infra_stall(self) -> None:
        verdict = e2e_stall.classify(results(self.root))
        self.assertTrue(verdict["infra"], verdict)
        self.assertEqual(verdict["failed"], 2)
        self.assertEqual(verdict["reason"], "backend 요청 0건 3.9초 틈 @2026-10-14T19:48:42.667Z")

    def test_an_assertion_failure_is_the_code(self) -> None:
        tests = [(TRACE_HEADS_1890[0], TIMEOUT_1890), (TRACE_HEADS_1890[1], ASSERTION)]
        self.assertFalse(e2e_stall.classify(results(self.root, tests=tests))["infra"])

    def test_a_timeout_while_backend_was_busy_is_the_code(self) -> None:
        # 마감(45.308)이 틈 밖 — 틈이 44.5 에 끝났다.
        busy = BACKEND_1890.replace("19:48:46.544804542Z", "19:48:44.544804542Z")
        busy += "backend-1  | 2026-10-14T19:48:45.300000000Z GET /api/accounts/me HTTP/1.1 200 1 3ms pid=<1>\n"
        self.assertFalse(e2e_stall.classify(results(self.root, backend=busy))["infra"])

    def test_a_failure_without_its_folder_is_not_judged(self) -> None:
        self.assertFalse(e2e_stall.classify(results(self.root, last_run_failed=3))["infra"])

    def test_a_project_that_failed_without_a_failed_test_is_not_judged(self) -> None:
        # 「No tests found」·globalSetup 오류 — 프로젝트는 failed 인데 failedTests 가 빈다. 진짜 정지와
        # 한 실행에서 겹쳐도 그 실패는 정지로 설명되지 않는다.
        out = results(self.root)
        broken = out / "playwright" / "operator"
        broken.mkdir()
        (broken / ".last-run.json").write_text(json.dumps({"status": "failed", "failedTests": []}))
        verdict = e2e_stall.classify(out)
        self.assertFalse(verdict["infra"], verdict)
        self.assertIn("operator", verdict["reason"])

    def test_a_green_run_is_not_a_stall(self) -> None:
        self.assertFalse(e2e_stall.classify(results(self.root, tests=[]))["infra"])

    def test_no_backend_log_is_not_a_stall(self) -> None:
        out = results(self.root)
        (out / "stack" / "backend.log").unlink()
        self.assertFalse(e2e_stall.classify(out)["infra"])


class TrainFail(unittest.TestCase):
    """`train.py fail` — 인프라 판정이면 같은 묶음을 한 번 더, 두 번째는 지금 규칙대로."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        os.environ["TRAIN_DRY_RUN"] = "1"
        os.environ["BUILD_NUMBER"] = "1890"

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_fail(self, count: int, verdict: dict | None, retried: bool = False) -> tuple[str, str]:
        entries = [{"number": 700 + i, "branch": f"b{i}", "head": f"{i:040d}", "fork": "f"} for i in range(count)]
        pathlib.Path(train.PLAN).write_text(json.dumps({"base": "b", "tree": "t", "entries": entries}))
        path = None
        if verdict is not None:
            path = "e2e-verdict.json"
            pathlib.Path(path).write_text(json.dumps(verdict, ensure_ascii=False))
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            train.fail(path, retried)
        return printed.getvalue(), pathlib.Path("train.next").read_text()

    STALL = {"infra": True, "reason": "backend 요청 0건 3.9초 틈 @2026-10-14T19:48:42.667Z"}

    def test_a_stall_reruns_the_same_bundle_once(self) -> None:
        printed, nxt = self.run_fail(1, self.STALL)
        self.assertIn("인프라 고장으로 분류: backend 요청 0건 3.9초 틈 @2026-10-14T19:48:42.667Z", printed)
        self.assertNotIn("failure", printed)
        self.assertEqual(nxt, "NEXT_MAX=1\nINFRA_RETRY=1\n")

    def test_a_stall_keeps_the_whole_bundle(self) -> None:
        _, nxt = self.run_fail(4, self.STALL)
        self.assertEqual(nxt, "NEXT_MAX=4\nINFRA_RETRY=1\n")

    def test_the_second_stall_follows_the_usual_rule(self) -> None:
        printed, nxt = self.run_fail(1, self.STALL, retried=True)
        self.assertIn("failure", printed)
        self.assertEqual(nxt, "NEXT_MAX=0\nINFRA_RETRY=0\n")
        _, nxt = self.run_fail(4, self.STALL, retried=True)
        self.assertEqual(nxt, "NEXT_MAX=2\nINFRA_RETRY=1\n")

    def test_a_split_after_the_rerun_is_not_judged_infra_again(self) -> None:
        # 재실행 몫은 가르기 사슬 전체에 한 번이다(#718) — 가른 묶음은 몫을 물려받아 판정을 읽지 않는다.
        printed, nxt = self.run_fail(2, self.STALL, retried=True)
        self.assertNotIn("인프라 고장으로 분류", printed)
        self.assertEqual(nxt, "NEXT_MAX=1\nINFRA_RETRY=1\n")

    def test_a_chain_that_always_looks_infra_reruns_only_once(self) -> None:
        # 코드 탓 실패가 매번 인프라로 잘못 분류돼도 8 → 재8 → 4 → 2 → 1, 다섯 번에 끝난다.
        builds, size, retried = [], 8, False
        while size:
            builds.append(size)
            _, nxt = self.run_fail(size, self.STALL, retried)
            values = dict(line.split("=") for line in nxt.split())
            size, retried = int(values["NEXT_MAX"]), values["INFRA_RETRY"] == "1"
        self.assertEqual(builds, [8, 8, 4, 2, 1])
        self.assertFalse(retried)

    def test_a_green_bundle_hands_the_budget_back(self) -> None:
        # 초록 뒤의 다음 묶음은 INFRA_RETRY 를 넘기지 않는다 — 기본값 0 으로 새 사슬이 몫을 다시 받는다.
        jenkinsfile = (ROOT / "Jenkinsfile.train").read_text()
        success = jenkinsfile[jenkinsfile.index("    success {"):]
        self.assertIn("string(name: 'MAX_PRS', value: '0')", success)
        self.assertNotIn("INFRA_RETRY", success)

    def test_a_code_failure_splits_as_before(self) -> None:
        _, nxt = self.run_fail(4, {"infra": False, "reason": "단언 실패"})
        self.assertEqual(nxt, "NEXT_MAX=2\nINFRA_RETRY=0\n")
        printed, nxt = self.run_fail(1, None)
        self.assertIn("failure", printed)
        self.assertEqual(nxt, "NEXT_MAX=0\nINFRA_RETRY=0\n")


if __name__ == "__main__":
    unittest.main()
