"""승격 흐름(#938, ADR-0077)의 배선 — 호스트에서 돈다(CI 이미지에는 `.github/` 가 없다).

    python3 scripts/test_release_flow.py

main push → release.yml: check(pr-check.yml) → image(image.yml) → promote(promote.sh) → production. Jenkins 는
production 머리의 이미지를 받아 배포한다(Jenkinsfile 의 `deployFrom`). 셋이 어긋나면 조용히 깨진다:
- 이미지 목록이 다르면 Jenkins 가 오지 않을 이미지를 기다리거나(배포 실패), 굽지 않은 이미지를 compose 가 찾는다.
- pr-check.yml 이 main push 로도 돌면 검사가 두 번 돌고, workflow_call 이 없으면 release.yml 이 부르지 못한다.
- promote 가 image 를 기다리지 않으면 production 이 이미지보다 먼저 움직인다.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "ci"))

from image_context import SERVICES  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"


def read(path: Path) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*", "", line) for line in path.read_text(encoding="utf-8").splitlines())


def job_block(code: str, job: str) -> str:
    match = re.search(rf"(?ms)^  {re.escape(job)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", code)
    assert match, f"잡 {job} 이 없다"
    return match.group(1)


class ReleaseFlowTest(unittest.TestCase):
    def test_image_lists_agree(self) -> None:
        image = read(WORKFLOWS / "image.yml")
        matrix = re.search(r"service:\s*\[([^\]]*)\]", image)
        assert matrix
        in_matrix = [s.strip() for s in matrix.group(1).split(",")]
        jenkins = re.findall(
            r"repo:\s*'ghcr\.io/sandcorporation/codemit-([\w-]+)'", (ROOT / "Jenkinsfile").read_text(encoding="utf-8")
        )
        self.assertEqual(sorted(in_matrix), sorted(SERVICES))
        self.assertEqual(sorted(jenkins), sorted(SERVICES))

    def test_pr_check_is_called_not_pushed(self) -> None:
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", read(WORKFLOWS / "pr-check.yml"))
        assert on
        self.assertRegex(on.group(1), r"(?m)^  pull_request:")
        self.assertRegex(on.group(1), r"(?m)^  workflow_call:")
        self.assertNotRegex(on.group(1), r"(?m)^  push:")

    def test_release_runs_check_and_image_then_promote_on_main_only(self) -> None:
        code = read(WORKFLOWS / "release.yml")
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", code)
        assert on
        self.assertEqual(re.sub(r"\s+", " ", on.group(1)).strip(), "push: branches: [main]")
        self.assertIn("uses: ./.github/workflows/pr-check.yml", job_block(code, "check"))
        image = job_block(code, "image")
        self.assertIn("uses: ./.github/workflows/image.yml", image)
        # check 와 image 는 병렬 — 승격만 둘을 기다린다.
        self.assertNotIn("needs:", image)
        promote = job_block(code, "promote")
        self.assertRegex(promote, r"needs:\s*\[check, image\]")
        self.assertIn('bash scripts/ci/promote.sh ff "$SHA"', promote)
        self.assertIn("fetch-depth: 0", promote)

    def test_image_is_only_built_from_main_or_by_hand(self) -> None:
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", read(WORKFLOWS / "image.yml"))
        assert on
        self.assertEqual(sorted(re.findall(r"(?m)^  ([\w-]+):", on.group(1))), ["workflow_call", "workflow_dispatch"])

    def test_image_tags_what_jenkins_waits_for_and_what_compose_pulls(self) -> None:
        image = read(WORKFLOWS / "image.yml")
        self.assertIn("runs-on: ubuntu-24.04-arm", image)
        self.assertIn("bash scripts/ci/images.sh arm64", image)
        self.assertIn('--tag "$REPO:$SHA" "$REPO:$SHA-arm64"', image)
        compose = (ROOT / "docker" / "compose.prod.yaml").read_text(encoding="utf-8")
        for name in SERVICES:
            with self.subTest(service=name):
                self.assertIn(f"/codemit-{name}:${{CODEMIT_IMAGE_TAG:-local}}-arm64", compose)

    def test_jenkins_deploys_production_only(self) -> None:
        jenkinsfile = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")
        self.assertIn("deployFrom: 'production'", jenkinsfile)
        self.assertNotIn("buildCredentials", jenkinsfile, "빌드 노드 자격은 비상 길에도 쓰지 않는다 — GlitchTip 은 배포 단계")


if __name__ == "__main__":
    unittest.main()
