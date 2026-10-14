#!/usr/bin/env python3
"""`scripts/ci/image_context.py` — 이미지 건너뛰기의 문맥 해시를 고정한다(#705).

`python3 scripts/test_image_context.py` 하나로 돈다 — 표준 라이브러리 `unittest` 와 임시 git 저장소만
쓴다(네트워크·도커 없음). PR CI 의 sub 검사가 돌린다(`scripts/ci/sub-checks-inside.sh`).

가장 무거운 시험은 맨 위의 것이다: 저장소의 Dockerfile 이 문맥에서 읽는 경로가 전부 해시 표 안에
있어야 한다. 빠지면 그 경로를 고친 커밋이 옛 이미지로 배포된다.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

import image_context as ic  # noqa: E402


class RepoDockerfiles(unittest.TestCase):
    def test_every_copy_source_is_in_the_context_table(self) -> None:
        for svc in ic.SERVICES.values():
            text = (ROOT / svc.dockerfile).read_text(encoding="utf-8")
            with self.subTest(service=svc.name):
                self.assertEqual(ic.uncovered(svc, text), [])

    def test_the_parser_actually_sees_the_copies(self) -> None:
        # 파서가 아무것도 못 읽으면 위 시험은 늘 초록이다 — 실제로 읽는지 못 박는다.
        backend = ic.copy_sources((ROOT / "docker/backend.Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("backend/", backend)
        classroom = ic.copy_sources((ROOT / "docker/classroom.Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("classroom/", classroom)
        self.assertIn("pnpm-lock.yaml", classroom)
        pgbouncer = ic.copy_sources((ROOT / "docker/pgbouncer.Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("docker/pgbouncer/docker-entrypoint.sh", pgbouncer)

    def test_every_service_has_its_dockerfile_and_paths(self) -> None:
        for svc in ic.SERVICES.values():
            for path in ic.context_paths(svc):
                with self.subTest(service=svc.name, path=path):
                    self.assertTrue((ROOT / path).exists())

    def test_every_dockerfile_in_the_image_set_is_a_service(self) -> None:
        # 배포 이미지 Dockerfile 이 늘었는데 표에 없으면 굽지도 해시하지도 않는다.
        not_deployed = {"ci"}
        names = {p.name.removesuffix(".Dockerfile") for p in (ROOT / "docker").glob("*.Dockerfile")}
        self.assertEqual(names - not_deployed, set(ic.SERVICES))


class CopySources(unittest.TestCase):
    def test_reads_flags_continuations_json_and_bind_mounts(self) -> None:
        text = "\n".join(
            [
                "FROM x AS base",
                "# COPY ignored/ ./",
                "COPY --chown=a:b package.json \\",
                "     pnpm-lock.yaml ./",
                'COPY ["docs/a b.txt", "/x/"]',
                "COPY --from=base /app/out ./out",
                "ADD https://example.com/f.tgz /tmp/",
                "ADD vendor/lib.tgz /opt/",
                "RUN --mount=type=cache,target=/c --mount=type=bind,source=tools,target=/t make",
                "RUN --mount=type=bind,from=base,source=/app,target=/a true",
            ]
        )
        self.assertEqual(
            ic.copy_sources(text),
            ["package.json", "pnpm-lock.yaml", "docs/a b.txt", "vendor/lib.tgz", "tools"],
        )

    def test_coverage(self) -> None:
        paths = ["backend", "docker/pgbouncer", "package.json"]
        self.assertTrue(ic.is_covered("backend/", paths))
        self.assertTrue(ic.is_covered("./backend/uv.lock", paths))
        self.assertTrue(ic.is_covered("docker/pgbouncer/docker-entrypoint.sh", paths))
        self.assertTrue(ic.is_covered("package.json", paths))
        self.assertTrue(ic.is_covered("backend/*.toml", paths))
        self.assertFalse(ic.is_covered("backend-extra/x", paths))
        self.assertFalse(ic.is_covered("docker/other.sh", paths))
        self.assertFalse(ic.is_covered(".", paths))
        self.assertFalse(ic.is_covered("*.json", paths))

    def test_an_unlisted_copy_is_reported(self) -> None:
        svc = ic.SERVICES["backend"]
        text = "FROM x\nCOPY backend/ ./\nCOPY scripts/entry.sh /e\n"
        self.assertEqual(ic.uncovered(svc, text), ["scripts/entry.sh"])


class Digest(unittest.TestCase):
    base = dict(objects={"backend": "a" * 40, "docker/backend.Dockerfile": "b" * 40}, target="", platform="linux/amd64")

    def digest(self, **over: object) -> str:
        kw = {**self.base, "build_args": {}, **over}
        return ic.context_digest(**kw)  # type: ignore[arg-type]

    def test_same_inputs_same_digest_regardless_of_order(self) -> None:
        a = ic.context_digest({"x": "1", "y": "2"}, "", "p", {"A": "1", "B": "2"})
        b = ic.context_digest({"y": "2", "x": "1"}, "", "p", {"B": "2", "A": "1"})
        self.assertEqual(a, b)
        self.assertEqual(len(a), 24)

    def test_every_input_moves_the_digest(self) -> None:
        plain = self.digest()
        self.assertNotEqual(plain, self.digest(objects={"backend": "c" * 40, "docker/backend.Dockerfile": "b" * 40}))
        self.assertNotEqual(plain, self.digest(target="runner"))
        self.assertNotEqual(plain, self.digest(platform="linux/arm64"))
        self.assertNotEqual(plain, self.digest(build_args={"NEXT_PUBLIC_SUPPORT_EMAIL": "a@b"}))
        self.assertNotEqual(
            self.digest(build_args={"K": "1"}), self.digest(build_args={"K": "2"})
        )

    def test_build_args_file(self) -> None:
        self.assertEqual(
            ic.parse_build_args("# c\nA=1\r\nB=x=y\n\nC=\n"),
            {"A": "1", "B": "x=y", "C": ""},
        )


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class GitObjects(unittest.TestCase):
    """서비스가 읽는 경로가 바뀔 때만 해시가 바뀐다 — 다른 서비스의 커밋은 건너뛴다."""

    def test_only_own_paths_move_the_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            _git(repo, "init", "-q")
            for rel in ("backend/app.py", "docker/backend.Dockerfile", ".dockerignore", "classroom/page.tsx"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(rel)
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "one")

            svc = ic.SERVICES["backend"]
            paths = ic.context_paths(svc)

            def digest() -> str:
                cwd = pathlib.Path.cwd()
                try:
                    os.chdir(repo)
                    return ic.context_digest(ic.git_objects(paths), svc.target, "linux/amd64", {})
                finally:
                    os.chdir(cwd)

            first = digest()
            (repo / "classroom/page.tsx").write_text("changed")
            _git(repo, "commit", "-qam", "classroom only")
            self.assertEqual(digest(), first)

            (repo / "backend/app.py").write_text("changed")
            _git(repo, "commit", "-qam", "backend")
            self.assertNotEqual(digest(), first)

            (repo / ".dockerignore").write_text("changed")
            _git(repo, "commit", "-qam", "dockerignore")
            second = digest()
            self.assertNotEqual(second, first)

            cwd = pathlib.Path.cwd()
            os.chdir(repo)
            try:
                with self.assertRaises(SystemExit):
                    ic.git_objects(["nope"])
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
