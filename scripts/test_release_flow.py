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
        self.assertNotRegex(jenkinsfile, r"(?m)\b(?:BUILD_ON|BUILDER|MAC_WAIT_SECONDS|buildScript|macWaitSeconds)\b")
        self.assertNotIn("buildCredentials", jenkinsfile, "빌드 노드 자격은 비상 길에도 쓰지 않는다 — GlitchTip 은 배포 단계")
        deploy = (ROOT / "scripts" / "ci" / "deploy-prod.sh").read_text(encoding="utf-8")
        self.assertIn("unset DEPLOY_IMAGE_SOURCE", deploy, "Jenkins 배포는 Actions 가 올린 GHCR 이미지만 받는다")

    def test_jenkins_image_build_emergency_path_is_retired(self) -> None:
        self.assertFalse((ROOT / "scripts" / "ci" / "build-images.sh").exists())


# 기반 이미지는 digest 로만(#945) — 떠다니는 태그는 상류가 옮기면 다음 배포가 상태 있는 컨테이너를 다시 만든다(#790).
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}(?:\s|$)")
# 이 두 파일의 FROM 을 고치면 deploy.sh 가 그 이미지를 새로 구워 운영 search·pgbouncer 컨테이너를 바꿔 끼운다.
# TODO(다음 의도적 교체 때 고정): 그때 digest 를 붙이고 이 목록에서 뺀다.
FROM_PIN_DEFERRED = {"search.Dockerfile", "pgbouncer.Dockerfile"}


def unpinned_external_froms(dockerfile_texts: dict[str, str], deferred: set[str]) -> list[str]:
    bad: list[str] = []
    for name, text in sorted(dockerfile_texts.items()):
        if name in deferred:
            continue
        stages: set[str] = set()
        for lineno, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^FROM\s+(?:--\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
            if not m:
                continue
            image, stage = m.groups()
            if image not in stages and not DIGEST.search(image + " "):
                bad.append(f"{name}:{lineno}: {image}")
            if stage:
                stages.add(stage)
    return bad


class BaseImagePinTest(unittest.TestCase):
    def test_dockerfile_external_from_has_digest(self) -> None:
        texts = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "docker").glob("*.Dockerfile")}
        self.assertEqual(unpinned_external_froms(texts, FROM_PIN_DEFERRED), [], "외부 FROM 은 이름:태그@sha256:<digest>")

    def test_prod_compose_external_image_has_digest(self) -> None:
        text = (ROOT / "docker" / "compose.prod.yaml").read_text(encoding="utf-8")
        bad = []
        for lineno, line in enumerate(text.splitlines(), 1):
            m = re.match(r"^\s+image:\s*(\S+)", line)
            if m and not m.group(1).startswith("${CODEMIT_IMAGE_REPO") and not DIGEST.search(m.group(1) + " "):
                bad.append(f"compose.prod.yaml:{lineno}: {m.group(1)}")
        self.assertEqual(bad, [], "자체 이미지가 아닌 image: 는 @sha256:<digest>")

    def test_checker_rejects_tag_only_and_allows_stage_refs(self) -> None:
        digest = "a" * 64
        ok = f"FROM node:22@sha256:{digest} AS base\nFROM base AS dev\n"
        self.assertEqual(unpinned_external_froms({"x.Dockerfile": ok}, set()), [])
        self.assertEqual(
            unpinned_external_froms({"x.Dockerfile": "FROM node:22 AS base\n"}, set()),
            ["x.Dockerfile:1: node:22"],
        )

    def test_dependabot_watches_docker_dir(self) -> None:
        text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        self.assertIn('package-ecosystem: "docker"', text)
        self.assertIn('directory: "/docker"', text)


if __name__ == "__main__":
    unittest.main()
