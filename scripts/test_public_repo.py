"""저장소를 공개해도 되는 HEAD 인가(#930, ADR-0076) — 호스트에서 돈다(git 이 필요하다).

    python3 scripts/test_public_repo.py

셋을 본다.
- 추적 파일에 내부 호스트(`.link` 도메인 — 자체 호스팅 GlitchTip·옛 staging 이 거기 있었다)가 없다.
- `docker/prod.env.example` 의 OCI 스토리지 값이 자리 표시(`<…>`)다 — 네임스페이스·버킷·리전 실값이 없다.
- `.github/workflows/*.yml` 이 공개 저장소의 보안 규칙을 지킨다 — `pull_request_target` 없음, 호스팅 실행기만,
  secrets 없음, `permissions: contents: read`, 액션은 40자 SHA 로 고정.

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
                self.assertNotRegex(code, r"(?m)^[ \t]+permissions:", "잡마다 권한을 넓히지 않는다")
                for runs_on in re.findall(r"runs-on:\s*(\S+)", code):
                    self.assertTrue(runs_on.startswith("ubuntu-"), runs_on)
                for line in code.splitlines():
                    if "uses:" in line:
                        self.assertRegex(line, PINNED_USES, "액션은 SHA 로 고정한다")


if __name__ == "__main__":
    unittest.main()
