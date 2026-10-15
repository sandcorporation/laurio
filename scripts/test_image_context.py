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
        self.assertNotEqual(plain, self.digest(build_args={"SOME_ARG": "a@b"}))
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

    def test_a_per_service_dockerignore_moves_the_hash(self) -> None:
        # BuildKit 은 `docker/<서비스>.Dockerfile.dockerignore` 가 있으면 루트 `.dockerignore` 대신 그것을 쓴다 —
        # 문맥을 바꾸는 파일이므로 해시에 들어야 한다(#709). 없으면 표에 넣지 않는다(git_objects 가 멈춘다).
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            _git(repo, "init", "-q")
            for rel in ("backend/app.py", "docker/backend.Dockerfile", ".dockerignore"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(rel)
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "one")
            svc = ic.SERVICES["backend"]
            own = "docker/backend.Dockerfile.dockerignore"

            def digest() -> str:
                cwd = pathlib.Path.cwd()
                try:
                    os.chdir(repo)
                    return ic.context_digest(ic.git_objects(ic.context_paths(svc)), svc.target, "linux/amd64", {})
                finally:
                    os.chdir(cwd)

            first = digest()
            (repo / own).write_text("node_modules")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "own ignore")
            second = digest()
            self.assertNotEqual(second, first)
            (repo / own).write_text("node_modules\n.env")
            _git(repo, "commit", "-qam", "own ignore changed")
            self.assertNotEqual(digest(), second)


class DockerIgnore(unittest.TestCase):
    """BuildKit 의 `.dockerignore` 규칙(moby patternmatcher)을 그대로 따른다 — 해시가 문맥과 같은 것을 보게."""

    def ignored(self, text: str, path: str) -> bool:
        return ic.is_ignored(path, ic.parse_dockerignore(text))

    def test_double_star_reaches_any_depth_and_whole_directories(self) -> None:
        self.assertTrue(self.ignored("**/e2e/", "frontend/e2e/auth.spec.ts"))
        self.assertTrue(self.ignored("**/e2e/", "frontend/e2e/lib/seed.ts"))
        self.assertTrue(self.ignored("**/e2e/", "e2e/x.ts"))
        self.assertFalse(self.ignored("**/e2e/", "frontend/lib/e2e-helper.ts"))
        self.assertTrue(self.ignored("**/*.test.ts", "classroom/lib/auth/session.test.ts"))
        self.assertFalse(self.ignored("**/*.test.ts", "classroom/lib/auth/session.ts"))
        self.assertTrue(self.ignored("**/vitest.config.*", "packages/markdown/vitest.config.mts"))

    def test_root_anchored_patterns_stay_at_the_root(self) -> None:
        self.assertTrue(self.ignored("docs/", "docs/ops/ci.md"))
        self.assertFalse(self.ignored("docs/", "frontend/docs/page.tsx"))
        self.assertFalse(self.ignored(".git/", "frontend/.gitignore"))
        self.assertFalse(self.ignored("*.md", "frontend/README.md"))
        self.assertTrue(self.ignored("/*.md", "README.md"))

    def test_last_matching_rule_wins_and_comments_are_skipped(self) -> None:
        text = "# c\n**/.env\n**/.env.*\n!**/.env.example\n"
        self.assertTrue(self.ignored(text, "frontend/.env.local"))
        self.assertFalse(self.ignored(text, "frontend/.env.example"))
        self.assertFalse(self.ignored(text, "frontend/app/page.tsx"))

    def test_question_mark_and_literal_dots(self) -> None:
        self.assertTrue(self.ignored("**/*.py[cod]", "backend/a.pyc"))
        self.assertFalse(self.ignored("**/*.py[cod]", "backend/a.py"))
        self.assertFalse(self.ignored("a.b", "axb"))
        self.assertTrue(self.ignored("a?b", "axb"))

    def test_the_repo_dockerignore_drops_tests_but_keeps_app_sources(self) -> None:
        rules = ic.parse_dockerignore((ROOT / ".dockerignore").read_text(encoding="utf-8"))
        for path in (
            "frontend/e2e/auth.spec.ts",
            "frontend/playwright.config.ts",
            "classroom/vitest.config.mts",
            "operator/lib/home/home.test.ts",
            "frontend/lib/ui/__snapshots__/classnames.test.ts.snap",
            "frontend/.env.local",
        ):
            with self.subTest(path=path):
                self.assertTrue(ic.is_ignored(path, rules))
        for path in (
            "frontend/app/page.tsx",
            "frontend/package.json",
            "frontend/tsconfig.json",
            "frontend/next.config.ts",
            "classroom/lib/auth/session.ts",
            "packages/route-audit/src/route-scan.ts",
            "pnpm-lock.yaml",
            "frontend/.env.example",
        ):
            with self.subTest(path=path):
                self.assertFalse(ic.is_ignored(path, rules))


class IgnoredFilesDoNotMoveTheHash(unittest.TestCase):
    """`.dockerignore` 가 문맥에서 뺀 파일은 해시에도 들지 않는다(#714) — 시험만 고친 커밋은 굽지 않는다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        files = {
            ".dockerignore": "**/e2e/\n**/*.test.ts\n",
            "docker/frontend.Dockerfile": "FROM x\nCOPY frontend/ ./frontend/\n",
            "frontend/app/page.tsx": "page",
            "frontend/e2e/auth.spec.ts": "spec",
            "frontend/lib/a.test.ts": "unit",
        }
        for name in ic.NODE_WORKSPACE:
            files[f"{name}/x" if name == "packages" else name] = name
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "one")
        self.svc = ic.SERVICES["frontend"]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def in_repo(self, fn):  # type: ignore[no-untyped-def]
        cwd = pathlib.Path.cwd()
        try:
            os.chdir(self.repo)
            return fn()
        finally:
            os.chdir(cwd)

    def digest(self) -> str:
        return self.in_repo(
            lambda: ic.context_digest(ic.service_objects(self.svc), self.svc.target, "linux/amd64", {})
        )

    def commit(self, rel: str, text: str) -> str:
        (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / rel).write_text(text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", rel)
        return _git(self.repo, "rev-parse", "HEAD")

    def test_e2e_and_unit_test_changes_keep_the_hash(self) -> None:
        first = self.digest()
        self.commit("frontend/e2e/auth.spec.ts", "spec changed")
        self.commit("frontend/e2e/new.spec.ts", "new spec")
        self.commit("frontend/lib/a.test.ts", "unit changed")
        self.assertEqual(self.digest(), first)

    def test_app_source_changes_move_the_hash(self) -> None:
        first = self.digest()
        self.commit("frontend/app/page.tsx", "page changed")
        self.commit("frontend/e2e/auth.spec.ts", "spec changed")
        self.assertNotEqual(self.digest(), first)

    def test_a_new_ignore_rule_moves_the_hash(self) -> None:
        first = self.digest()
        self.commit(".dockerignore", "**/e2e/\n")
        self.assertNotEqual(self.digest(), first)

    def test_the_per_service_ignore_replaces_the_root_one(self) -> None:
        # BuildKit 은 `docker/<서비스>.Dockerfile.dockerignore` 가 있으면 루트 것을 읽지 않는다.
        self.commit("docker/frontend.Dockerfile.dockerignore", "**/node_modules/\n")
        before = self.digest()
        self.commit("frontend/e2e/auth.spec.ts", "spec changed")
        self.assertNotEqual(self.digest(), before)


class ChangedServices(unittest.TestCase):
    """deploy.sh plan 이 두 커밋 사이에 바꿔 끼울 서비스를 문맥 해시로 고른다(#712, codemit-deploy-staging #474 —
    `frontend/playwright.config.ts` 주석만 바뀐 커밋에 frontend 를 다시 띄웠다)."""

    FILES = (
        ".dockerignore", "backend/app.py", "frontend/page.tsx", "operator/page.tsx", "classroom/page.tsx",
        "packages/shared/index.ts", "package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml",
        "docker/pgbouncer/entry.sh",
        *(f"docker/{name}.Dockerfile" for name in ("backend", "frontend", "operator", "classroom", "search", "pgbouncer")),
    )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self._tmp.name)
        _git(self.repo, "init", "-q")
        for rel in self.FILES:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(rel)
        (self.repo / ".dockerignore").write_text("**/playwright.config.ts\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "one")
        self.base = _git(self.repo, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def commit(self, rel: str, text: str) -> str:
        (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / rel).write_text(text)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", rel)
        return _git(self.repo, "rev-parse", "HEAD")

    def changed(self, old: str, new: str) -> list[str]:
        cwd = pathlib.Path.cwd()
        os.chdir(self.repo)
        try:
            return ic.changed_services(old, new)
        finally:
            os.chdir(cwd)

    def test_a_file_outside_the_context_changes_nothing(self) -> None:
        head = self.commit("frontend/playwright.config.ts", "// 주석만")
        self.assertEqual(self.changed(self.base, head), [])

    def test_a_shared_package_changes_the_three_apps(self) -> None:
        head = self.commit("packages/shared/index.ts", "changed")
        self.assertEqual(self.changed(self.base, head), ["frontend", "operator", "classroom"])

    def test_a_dockerfile_changes_only_its_service(self) -> None:
        head = self.commit("docker/search.Dockerfile", "changed")
        self.assertEqual(self.changed(self.base, head), ["search"])

    def test_a_path_missing_at_the_old_commit_counts_as_changed(self) -> None:
        # 표가 옛 커밋에 없는 경로를 요구하면 모른다 — 모르면 바꿔 끼운다.
        _git(self.repo, "rm", "-q", "-r", "docker/pgbouncer")
        _git(self.repo, "commit", "-qm", "no pgbouncer dir")
        old = _git(self.repo, "rev-parse", "HEAD")
        head = self.commit("docker/pgbouncer/entry.sh", "back")
        self.assertEqual(self.changed(old, head), ["pgbouncer"])


if __name__ == "__main__":
    unittest.main()
