"""저장소를 공개해도 되는 HEAD 인가(#930, ADR-0076) — 호스트에서 돈다(git 이 필요하다).

    python3 scripts/test_public_repo.py

셋을 본다.
- 추적 파일에 내부 호스트(`.link` 도메인 — 자체 호스팅 GlitchTip·옛 staging 이 거기 있었다)가 없다.
- `docker/prod.env.example` 의 OCI 스토리지 값이 자리 표시(`<…>`)다 — 네임스페이스·버킷·리전 실값이 없다.
- `.github/workflows/*.yml` 이 공개 저장소의 보안 규칙을 지킨다 — `pull_request_target` 없음, 호스팅 실행기만,
  secrets 없음(토큰은 `github.token` 하나), 워크플로 기본 권한 `contents: read`, 액션은 40자 SHA 로 고정(같은 저장소의
  `./.github/workflows/…` 재사용은 예외). 쓰기 권한은 승격 흐름(#938)의 정해진 자리에만 — `packages: write` 는 image
  (image.yml 과 release.yml 의 image 잡), `contents: write` 는 release.yml 의 promote 잡, `issues: write` 는 같은 파일의 notify 잡.

CI 이미지에는 `.git`·`.github/` 가 없어(.dockerignore) pytest 가 아니라 이 스크립트를 호스트에서 부른다 —
Actions 는 `plan` 잡, Jenkins 는 `scripts/ci/pr-check.sh`.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 속성 대입·호출(`f.link = …`, `x.link(…)`) 같은 코드는 빼고 호스트 꼴만 잡는다.
LINK_HOST = re.compile(r"(?<![\w.$])((?:[a-z0-9-]+\.)+link)\b(?!\s*[=(])")
STORAGE_KEYS = (
    "STORAGE_BUCKET",
    "STORAGE_ENDPOINT_URL",
    "STORAGE_REGION",
    "STORAGE_IMAGES_BUCKET",
    "STORAGE_IMAGES_BASE_URL",
)
PINNED_USES = re.compile(r"^\s*-?\s*uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}(\s|$)")
LOCAL_WORKFLOW_USES = re.compile(r"^\s*uses:\s*\./\.github/workflows/[\w.-]+\.ya?ml\s*$")
# (워크플로 파일, 잡 — 최상위면 "") → 그 자리에서만 허락하는 쓰기 권한(#938). 여기 없는 자리의 쓰기는 모두 실패다.
ALLOWED_WRITES = {
    ("image.yml", ""): {"packages"},
    ("release.yml", "image"): {"packages"},
    ("release.yml", "promote"): {"contents"},
    ("release.yml", "notify"): {"issues"},
    ("e2e.yml", "notify"): {"issues"},  # 매시 e2e 실패 알림(#1111, 본 저장소 #1015)
}
# 잡마다 권한을 따로 적어도 되는 워크플로 — 승격 흐름은 잡마다 권한이 달라야 한다.
JOB_PERMISSIONS_ALLOWED = {"release.yml", "e2e.yml"}


def permission_blocks(code: str) -> list[tuple[str, dict[str, str]]]:
    """(잡 이름 — 최상위면 "", {권한: 값}) 목록. `permissions: {}`·`read-all` 같은 한 줄 꼴도 담는다."""

    lines = code.splitlines()
    blocks: list[tuple[str, dict[str, str]]] = []
    job = ""
    in_jobs = False
    for i, line in enumerate(lines):
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if re.match(r"^\S", line):
            in_jobs = False
            job = ""
        top_job = re.match(r"^  ([\w-]+):\s*$", line)
        if in_jobs and top_job:
            job = top_job.group(1)
        found = re.match(r"^(\s*)permissions:\s*(\S.*)?$", line)
        if not found:
            continue
        indent = len(found.group(1))
        values: dict[str, str] = {}
        if found.group(2):
            values["*"] = found.group(2).strip()
        for follow in lines[i + 1 :]:
            entry = re.match(r"^(\s*)([\w-]+):\s*(\S+)\s*$", follow)
            if not entry or len(entry.group(1)) <= indent:
                break
            values[entry.group(2)] = entry.group(3)
        blocks.append(("" if indent == 0 else job, values))
    return blocks


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return [name for name in out.decode().split("\0") if name]


class PublicRepoTest(unittest.TestCase):
    def test_no_internal_link_hosts(self) -> None:
        found = []
        for name in tracked_files():
            path = ROOT / name
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for match in LINK_HOST.finditer(line):
                    found.append(f"{name}:{lineno}: {match.group(1)}")
        self.assertEqual(found, [], "내부 호스트는 환경변수나 자리 표시로 뺀다")

    def test_prod_env_example_storage_values_are_placeholders(self) -> None:
        values = {}
        for line in (ROOT / "docker/prod.env.example").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key in STORAGE_KEYS:
                values[key] = value
        self.assertEqual(sorted(values), sorted(STORAGE_KEYS))
        for key, value in values.items():
            with self.subTest(key=key):
                self.assertRegex(value, r"<[a-z-]+>", "OCI 실값 대신 자리 표시를 둔다")
                self.assertNotIn("codemit-prod", value)

    def test_workflows_follow_public_repo_rules(self) -> None:
        workflows = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
        self.assertTrue(workflows, "PR 검사 워크플로가 있다")
        for workflow in workflows:
            text = workflow.read_text(encoding="utf-8")
            code = "\n".join(re.sub(r"(^|\s)#.*", "", line) for line in text.splitlines())
            with self.subTest(workflow=workflow.name):
                self.assertNotIn("pull_request_target", code)
                self.assertNotIn("self-hosted", code)
                self.assertNotIn("secrets.", code)
                self.assertRegex(code, r"(?m)^permissions:\n\s+contents: read\s*$")
                if workflow.name not in JOB_PERMISSIONS_ALLOWED:
                    self.assertNotRegex(code, r"(?m)^[ \t]{4}permissions:", "잡마다 권한을 넓히지 않는다")
                for job, values in permission_blocks(code):
                    allowed = ALLOWED_WRITES.get((workflow.name, job), set())
                    for scope, value in values.items():
                        self.assertNotIn(value, ("write-all", "read-all"), f"{job or '최상위'}: 통째 권한")
                        if value == "write":
                            self.assertIn(scope, allowed, f"{workflow.name} {job or '최상위'} 의 {scope}: write")
                for runs_on in re.findall(r"runs-on:\s*(\S+)", code):
                    self.assertTrue(runs_on.startswith("ubuntu-"), runs_on)
                for line in code.splitlines():
                    if "uses:" in line and not LOCAL_WORKFLOW_USES.match(line):
                        self.assertRegex(line, PINNED_USES, "액션은 SHA 로 고정한다")

    def test_release_triggers_and_only_runs_on_main(self) -> None:
        """release 는 push(main)와 수동 실행뿐이고, main 밖 ref 로는 어느 잡도 돌지 않는다(#1018)."""
        code = "\n".join(re.sub(r"(^|\s)#.*", "", l) for l in (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8").splitlines())
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", code)
        self.assertIsNotNone(on)
        self.assertEqual(re.sub(r"\s+", " ", on.group(1)).strip(), "push: branches: [main] workflow_dispatch:")
        jobs = {m.group(1): m.group(2) for m in re.finditer(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", code.split("\njobs:\n", 1)[1])}
        self.assertIn("main_only", jobs)
        self.assertIn("refs/heads/main", jobs["main_only"])
        self.assertIn("exit 1", jobs["main_only"])
        for name, block in jobs.items():
            if name == "main_only":
                continue
            with self.subTest(job=name):
                self.assertRegex(block, r"needs:\s*(\[[^\]]*\bmain_only\b[^\]]*\]|main_only\b)", "main_only 를 기다린다")
                if "!cancelled()" in block:  # 선행 잡이 실패해도 도는 if 는 main_only success 를 직접 요구한다
                    self.assertIn("needs.main_only.result == 'success'", block)

    def test_permission_blocks_reads_top_and_job_levels(self) -> None:
        code = "permissions:\n  contents: read\njobs:\n  a:\n    permissions:\n      packages: write\n    runs-on: x\n"
        self.assertEqual(permission_blocks(code), [("", {"contents": "read"}), ("a", {"packages": "write"})])

    def test_a_write_outside_the_allowed_places_is_caught(self) -> None:
        code = "jobs:\n  check:\n    permissions:\n      contents: write\n"
        [(job, values)] = permission_blocks(code)
        self.assertNotIn("contents", ALLOWED_WRITES.get(("release.yml", job), set()))
        self.assertEqual(values, {"contents": "write"})


if __name__ == "__main__":
    unittest.main()
