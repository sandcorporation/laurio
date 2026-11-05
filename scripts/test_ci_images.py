#!/usr/bin/env python3
"""배포 이미지 스크립트 — `scripts/ci/images.sh`(건너뛰기·retag·실패 로그)와 `scripts/ci/images-e2e.sh`(e2e 가 본 digest 에
`e2e-<트리>-arm64` 태그). 가짜 docker 로 돈다.

`python3 scripts/test_ci_images.py` 하나로 돈다 — 표준 라이브러리 `unittest` 와 임시 폴더만 쓴다
(네트워크·도커 없음). PR 검사가 돌린다(`scripts/ci/sub-checks-inside.sh`). 2026-11-05(#873) 전에는 열차의
인프라 판정(`e2e_stall.py`·`train.py fail`) 시험과 한 파일(`test_e2e_stall.py`)이었다 — 열차와 함께 그쪽은 지웠다.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

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

    def test_a_failed_build_leaves_its_log(self) -> None:
        self.build_log.write_text(REGISTRY_502)
        self.assertEqual(self.run_images("push", "r/codemit-frontend:ctx-hfrontend-arm64"), 1)
        self.assertEqual((self.repo / ".images-arm64.result").read_text(), "backend=failed\nfrontend=skipped\n")
        self.assertIn("502 Bad Gateway", (self.repo / "test-results/images-arm64/backend.log").read_text())
        self.assertFalse((self.repo / "test-results/images-arm64/frontend.log").exists())

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


class ImagesE2eTag(unittest.TestCase):
    """images-e2e.sh — e2e 가 받은 우리 이미지 digest 마다 한 번 `e2e-<트리>-arm64` 를 붙인다(#729)."""

    def test_tags_each_of_our_digests_once_with_the_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            repo = base / "repo"
            (repo / "scripts" / "ci").mkdir(parents=True)
            for name in ("images-e2e.sh", "ghcr-login.sh"):
                shutil.copy(ROOT / "scripts" / "ci" / name, repo / "scripts" / "ci" / name)
            (base / "bin").mkdir()
            (base / "bin" / "docker").write_text(FAKE_DOCKER)
            (base / "bin" / "docker").chmod(0o755)
            a, b = "a" * 64, "b" * 64
            listing = base / "images.txt"
            listing.write_text(
                f"backend ghcr.io/sandcorporation/codemit-backend@sha256:{a}\n"
                f"celery-worker ghcr.io/sandcorporation/codemit-backend@sha256:{a}\n"
                f"frontend ghcr.io/sandcorporation/codemit-frontend@sha256:{b}\n"
                f"db postgres@sha256:{a}\n"
            )
            calls = base / "calls"
            env = {**os.environ, "PATH": f"{base / 'bin'}:{os.environ['PATH']}", "FAKE_CALLS": str(calls), "TMPDIR": tmp}
            env.pop("GHCR_TOKEN", None)
            done = subprocess.run(["bash", "scripts/ci/images-e2e.sh", str(listing), "t" * 40], cwd=repo, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(done.returncode, 0, done.stdout)
            created = sorted(line for line in calls.read_text().splitlines() if "imagetools create --prefer" in line)
            self.assertEqual(created, [
                f"buildx imagetools create --prefer-index=false --tag ghcr.io/sandcorporation/codemit-backend:e2e-{'t' * 40}-arm64 "
                f"ghcr.io/sandcorporation/codemit-backend@sha256:{a}",
                f"buildx imagetools create --prefer-index=false --tag ghcr.io/sandcorporation/codemit-frontend:e2e-{'t' * 40}-arm64 "
                f"ghcr.io/sandcorporation/codemit-frontend@sha256:{b}",
            ])


if __name__ == "__main__":
    unittest.main()
