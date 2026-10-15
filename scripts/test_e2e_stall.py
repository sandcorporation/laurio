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
import shutil
import subprocess
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


# 이미지 굽기(#729) — buildx 가 실제로 남기는 줄 모양.
REGISTRY_502 = """#12 exporting to image
#12 pushing layers 2.1s done
ERROR: failed to solve: failed to push ghcr.io/sandcorporation/codemit-backend:abc-arm64: unexpected status from PUT request to https://ghcr.io/v2/sandcorporation/codemit-backend/blobs/uploads/x: 502 Bad Gateway
"""
RUN_FAILED = """#18 [build 6/9] RUN pnpm --filter frontend build
#18 ERROR: process "/bin/sh -c pnpm --filter frontend build" did not complete successfully: exit code: 1
ERROR: failed to solve: process "/bin/sh -c pnpm --filter frontend build" did not complete successfully: exit code: 1
"""
COPY_MISSING = 'ERROR: failed to solve: failed to compute cache key: failed to calculate checksum of ref x: "/backend/nope": not found\n'
BUILDKIT_GONE = "ERROR: failed to receive status: rpc error: code = Unavailable desc = error reading from server: EOF\n"


def images_run(root: pathlib.Path, arch: str, results: dict, logs: dict) -> None:
    """images.sh 가 남기는 모양 — `.images-<arch>.result` 와 실패 로그."""
    (root / f".images-{arch}.result").write_text("".join(f"{k}={v}\n" for k, v in results.items()))
    folder = root / "test-results" / f"images-{arch}"
    folder.mkdir(parents=True, exist_ok=True)
    for svc, text in logs.items():
        (folder / f"{svc}.log").write_text(text)


class ImagesClassify(unittest.TestCase):
    """`e2e_stall.py images <arch>` — 레지스트리·buildx 탓만 인프라, Dockerfile·소스 탓은 코드."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_registry_5xx_is_infra(self) -> None:
        images_run(self.root, "arm64", {"backend": "failed", "frontend": "skipped"}, {"backend": REGISTRY_502})
        verdict = e2e_stall.classify_images("arm64", self.root)
        self.assertTrue(verdict["infra"])
        self.assertIn("backend", verdict["reason"])

    def test_buildkit_losing_its_daemon_is_infra(self) -> None:
        images_run(self.root, "amd64", {"backend": "failed", "search": "failed"},
                   {"backend": BUILDKIT_GONE, "search": REGISTRY_502})
        self.assertTrue(e2e_stall.classify_images("amd64", self.root)["infra"])

    def test_a_failed_run_step_is_the_code(self) -> None:
        images_run(self.root, "arm64", {"frontend": "failed"}, {"frontend": RUN_FAILED})
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])

    def test_a_missing_copy_path_is_the_code(self) -> None:
        images_run(self.root, "arm64", {"backend": "failed"}, {"backend": COPY_MISSING})
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])

    def test_one_code_failure_among_infra_failures_is_the_code(self) -> None:
        images_run(self.root, "arm64", {"backend": "failed", "frontend": "failed"},
                   {"backend": REGISTRY_502, "frontend": RUN_FAILED + REGISTRY_502})
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])

    def test_an_unknown_failure_is_not_judged(self) -> None:
        images_run(self.root, "arm64", {"backend": "failed"}, {"backend": "ERROR: something odd\n"})
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])

    def test_preflight_without_a_result_is_not_judged(self) -> None:
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])

    def test_a_failure_without_its_log_is_not_judged(self) -> None:
        images_run(self.root, "arm64", {"backend": "failed"}, {})
        self.assertFalse(e2e_stall.classify_images("arm64", self.root)["infra"])


FAKE_DOCKER = """#!/bin/sh
# 가짜 docker — FAKE_HAVE 에 든 ref 만 레지스트리에 있다, build 는 FAKE_BUILD_LOG 를 내고 실패한다.
echo "$*" >> "$FAKE_CALLS"
case "$*" in
  "buildx version") [ -z "$FAKE_NO_BUILDX" ]; exit $? ;;
  "buildx imagetools create --help") echo "--prefer-index" ; exit 0 ;;
  "buildx imagetools inspect "*) case " $FAKE_HAVE " in *" $4 "*) exit 0 ;; esac; exit 1 ;;
  "buildx imagetools create "*) exit 0 ;;
  "buildx inspect"*|"buildx create"*|"buildx prune"*) exit 0 ;;
  "buildx build "*) cat "$FAKE_BUILD_LOG"; exit 1 ;;
esac
exit 0
"""


class ImagesScript(unittest.TestCase):
    """images.sh 를 가짜 docker 로 — 실패 로그를 남기는가, retag 는 굽지도 빌더를 띄우지도 않는가(#729)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.repo = base / "repo"
        (self.repo / "scripts" / "ci").mkdir(parents=True)
        for name in ("images.sh", "ghcr-login.sh"):
            shutil.copy(ROOT / "scripts" / "ci" / name, self.repo / "scripts" / "ci" / name)
        # 문맥 해시는 서비스 이름 그대로 — 해시 계산은 test_image_context.py 가 본다.
        (self.repo / "scripts" / "ci" / "image_context.py").write_text(
            "import sys\nif sys.argv[1] == 'hash': print('h' + sys.argv[2])\n")
        git = ["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-qm", "x"], check=True)
        bin_dir = base / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(FAKE_DOCKER)
        (bin_dir / "docker").chmod(0o755)
        self.calls = base / "calls"
        self.build_log = base / "build.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_CALLS": str(self.calls),
                    "FAKE_BUILD_LOG": str(self.build_log), "CODEMIT_IMAGES_SERVICES": "backend frontend",
                    "CODEMIT_IMAGE_REGISTRY": "r", "TMPDIR": str(base)}
        self.env.pop("GHCR_TOKEN", None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_images(self, mode: str, have: str) -> int:
        env = {**self.env, "CODEMIT_IMAGES_MODE": mode, "FAKE_HAVE": have}
        done = subprocess.run(["bash", "scripts/ci/images.sh", "arm64"], cwd=self.repo, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return done.returncode

    def test_a_failed_build_leaves_its_log_for_the_verdict(self) -> None:
        self.build_log.write_text(REGISTRY_502)
        self.assertEqual(self.run_images("push", "r/codemit-frontend:ctx-hfrontend-arm64"), 1)
        self.assertEqual((self.repo / ".images-arm64.result").read_text(), "backend=failed\nfrontend=skipped\n")
        self.assertIn("502 Bad Gateway", (self.repo / "test-results/images-arm64/backend.log").read_text())
        self.assertFalse((self.repo / "test-results/images-arm64/frontend.log").exists())
        self.assertTrue(e2e_stall.classify_images("arm64", self.repo)["infra"])

    def test_a_stale_result_does_not_survive_a_preflight_stop(self) -> None:
        (self.repo / ".images-arm64.result").write_text("backend=failed\n")
        env = {**self.env, "CODEMIT_IMAGES_MODE": "nope"}
        subprocess.run(["bash", "scripts/ci/images.sh", "arm64"], cwd=self.repo, env=env, capture_output=True)
        # 사용법 오류는 지우기 전에 멈춘다 — preflight(buildx 없음)는 지운 뒤라 옛 결과가 남지 않는다.
        env = {**self.env, "FAKE_NO_BUILDX": "1"}
        subprocess.run(["bash", "scripts/ci/images.sh", "arm64"], cwd=self.repo, env=env, capture_output=True)
        self.assertFalse((self.repo / ".images-arm64.result").exists())

    def test_retag_tags_what_it_can_and_leaves_the_rest_pending(self) -> None:
        self.assertEqual(self.run_images("retag", "r/codemit-frontend:ctx-hfrontend-arm64"), 0)
        self.assertEqual((self.repo / ".images-arm64.result").read_text(), "backend=pending\nfrontend=skipped\n")
        self.assertEqual((self.repo / ".images-arm64.ctx").read_text(), "")
        calls = self.calls.read_text()
        self.assertIn("imagetools create --prefer-index=false --tag r/codemit-frontend:", calls)
        self.assertNotIn("buildx build", calls)
        self.assertNotIn("buildx inspect", calls)  # 빌더를 띄우지 않는다 — 어느 노드에서나 돈다

    def test_retag_with_everything_skipped_is_all_skipped(self) -> None:
        have = "r/codemit-backend:ctx-hbackend-arm64 r/codemit-frontend:ctx-hfrontend-arm64"
        self.assertEqual(self.run_images("retag", have), 0)
        self.assertEqual((self.repo / ".images-arm64.result").read_text(), "backend=skipped\nfrontend=skipped\n")


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

    def run_fail_many(self, count: int, verdicts: list) -> str:
        entries = [{"number": 700 + i, "branch": f"b{i}", "head": f"{i:040d}", "fork": "f"} for i in range(count)]
        pathlib.Path(train.PLAN).write_text(json.dumps({"base": "b", "tree": "t", "entries": entries}))
        paths = []
        for i, verdict in enumerate(verdicts):
            paths.append(f"verdict-{i}.json")
            pathlib.Path(paths[-1]).write_text(json.dumps(verdict, ensure_ascii=False))
        with contextlib.redirect_stdout(io.StringIO()):
            train.fail(paths, False)
        return pathlib.Path("train.next").read_text()

    def test_every_red_side_infra_reruns(self) -> None:
        # sub 의 이미지 굽기와 macos 의 e2e 가 둘 다 인프라로 붉었다(#729).
        images = {"infra": True, "reason": "이미지 굽기(amd64)의 인프라 실패: backend 502 Bad Gateway"}
        self.assertEqual(self.run_fail_many(4, [images, self.STALL]), "NEXT_MAX=4\nINFRA_RETRY=1\n")

    def test_one_red_side_that_is_the_code_splits(self) -> None:
        images = {"infra": True, "reason": "502"}
        code = {"infra": False, "reason": "frontend(arm64) 은 빌드가 실패했다"}
        self.assertEqual(self.run_fail_many(4, [images, code]), "NEXT_MAX=2\nINFRA_RETRY=0\n")

    def test_the_pipeline_passes_a_verdict_only_when_every_red_side_has_one(self) -> None:
        # 붉은 쪽 하나라도 판정이 없으면(검사·가드·celery) 판정을 넘기지 않는다 — Jenkinsfile.train 의 post.
        failure = (ROOT / "Jenkinsfile.train").read_text().split("    failure {", 1)[1]
        self.assertIn("judgeable = false", failure)
        self.assertIn("if (judgeable && verdicts) {", failure)

    def test_a_code_failure_splits_as_before(self) -> None:
        _, nxt = self.run_fail(4, {"infra": False, "reason": "단언 실패"})
        self.assertEqual(nxt, "NEXT_MAX=2\nINFRA_RETRY=0\n")
        printed, nxt = self.run_fail(1, None)
        self.assertIn("failure", printed)
        self.assertEqual(nxt, "NEXT_MAX=0\nINFRA_RETRY=0\n")


if __name__ == "__main__":
    unittest.main()
