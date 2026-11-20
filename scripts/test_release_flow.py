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
from verified_tree import TESTED_STEP, Job, Run, decide, tested_commit  # noqa: E402

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
        self.assertEqual(re.sub(r"\s+", " ", on.group(1)).strip(), "push: branches: [main] workflow_dispatch:")
        self.assertIn("uses: ./.github/workflows/pr-check.yml", job_block(code, "check"))
        image = job_block(code, "image")
        self.assertIn("uses: ./.github/workflows/image.yml", image)
        # check 와 image 는 병렬 — 승격만 둘을 기다린다.
        self.assertRegex(image, r"needs:\s*main_only\s*\n")
        self.assertNotRegex(image, r"needs:.*(verify|check)")
        promote = job_block(code, "promote")
        self.assertRegex(promote, r"needs:\s*\[main_only, verify, check, image\]")
        # 건너뛴 check 로 승격하는 길은 verify 가 증명했을 때 하나뿐(#959)
        self.assertIn("needs.image.result == 'success'", promote)
        self.assertIn(
            "(needs.check.result == 'skipped' && needs.verify.result == 'success' && needs.verify.outputs.skip == '1')",
            re.sub(r"\s+", " ", promote),
        )
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


class ReleaseSkipsAlreadyCheckedTreeTest(unittest.TestCase):
    """#959 — release 는 PR 검사가 같은 트리를 초록으로 돌았다고 증명할 때만 check 를 건너뛴다."""

    TREE = "a" * 40
    X = "b" * 40

    def run_(self, tree: str | None = TREE, conclusion: str = "success", tests: str = "success", guard: str = "skipped") -> Run:
        jobs = (
            Job("guard (frontend)", guard, ()),
            Job("guard (classroom)", guard, ()),
            Job("plan", "success", ("Set up job", f"검사한 커밋 {self.X}", "무엇을 돌릴지")),
            Job("checks static", tests, ()),
            Job("e2e classroom", tests, ()),
            Job("결과", "success", ()),
        )
        return Run(1, conclusion, jobs, tree)

    def test_same_tree_from_a_full_green_run_skips(self) -> None:
        decision = decide(self.TREE, 1, ["backend/app.py"], [self.run_()])
        self.assertTrue(decision.skip, decision.reason)

    def test_guard_skipped_on_pr_is_green_but_any_other_skipped_job_is_not(self) -> None:
        self.assertTrue(decide(self.TREE, 1, ["backend/app.py"], [self.run_(guard="skipped")]).skip)
        self.assertFalse(decide(self.TREE, 1, ["backend/app.py"], [self.run_(guard="failure")]).skip)
        self.assertFalse(decide(self.TREE, 1, ["backend/app.py"], [self.run_(tests="skipped")]).skip)

    def test_main_moved_between_check_and_merge_runs_full_check(self) -> None:
        self.assertFalse(decide(self.TREE, 1, ["backend/app.py"], [self.run_(tree="c" * 40)]).skip)

    def test_docs_only_run_that_skipped_tests_is_not_proof(self) -> None:
        self.assertFalse(decide(self.TREE, 1, ["docs/a.md"], [self.run_(tests="skipped")]).skip)

    def test_red_or_unreadable_or_missing_runs_are_not_proof(self) -> None:
        self.assertFalse(decide(self.TREE, 1, [], [self.run_(conclusion="failure")]).skip)
        self.assertFalse(decide(self.TREE, 1, [], [self.run_(tree=None)]).skip)
        self.assertFalse(decide(self.TREE, 1, [], []).skip)
        no_result = Run(1, "success", (Job("plan", "success", ()),), self.TREE)
        self.assertFalse(decide(self.TREE, 1, [], [no_result]).skip)

    def test_any_matching_run_is_enough(self) -> None:
        self.assertTrue(decide(self.TREE, 1, [], [self.run_(tree="c" * 40), self.run_()]).skip)

    def test_cache_key_files_force_full_check_so_main_saves_the_cache(self) -> None:
        for path in ("backend/uv.lock", "pnpm-lock.yaml", "docker/ci.Dockerfile", "docker/backend.Dockerfile"):
            with self.subTest(path=path):
                self.assertFalse(decide(self.TREE, 1, [path], [self.run_()]).skip)

    def test_non_squash_commit_runs_full_check(self) -> None:
        self.assertFalse(decide(self.TREE, 2, [], [self.run_()]).skip)

    def test_tested_commit_is_read_from_the_plan_step_name(self) -> None:
        self.assertEqual(tested_commit(self.run_().jobs), self.X)
        self.assertIsNone(tested_commit((Job("plan", "success", ("검사한 커밋 ",)),)))

    def test_pr_check_plan_names_the_step_the_way_verify_reads_it(self) -> None:
        plan = job_block(read(WORKFLOWS / "pr-check.yml"), "plan")
        names = re.findall(r"name:\s*(검사한 커밋 .*)", plan)
        self.assertEqual(names, ["검사한 커밋 ${{ github.sha }}"])
        self.assertTrue(TESTED_STEP.match(names[0].replace("${{ github.sha }}", self.X)))

    def test_release_check_is_skipped_only_on_proof_and_verify_only_reads(self) -> None:
        code = read(WORKFLOWS / "release.yml")
        check = job_block(code, "check")
        self.assertIn("needs: [main_only, verify]", check)
        self.assertIn("if: ${{ !cancelled() && needs.main_only.result == 'success' && needs.verify.outputs.skip != '1' }}", check)
        verify = job_block(code, "verify")
        self.assertIn('python3 scripts/ci/verified_tree.py "$SHA"', verify)
        scopes = dict(re.findall(r"(?m)^      ([\w-]+): (read|write)$", verify))
        self.assertEqual(scopes, {"contents": "read", "pull-requests": "read", "actions": "read"})


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
