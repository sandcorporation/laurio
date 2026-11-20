"""승격 흐름(#938, ADR-0077)의 배선 — 호스트에서 돈다(CI 이미지에는 `.github/` 가 없다).

    python3 scripts/test_release_flow.py

PR → 병합 대기열(pr-check.yml, 배포 가능 판정 한 번) → main push → release.yml: image(image.yml) → promote(promote.sh) →
production. Jenkins 는 production 머리의 이미지를 받아 배포한다(Jenkinsfile 의 `deployFrom`). 셋이 어긋나면 조용히 깨진다:
- 이미지 목록이 다르면 Jenkins 가 오지 않을 이미지를 기다리거나(배포 실패), 굽지 않은 이미지를 compose 가 찾는다.
- pr-check.yml 이 main push 나 release 에서도 돌면 같은 커밋을 두 번 검사한다(#1090).
- promote 가 image 를 기다리지 않으면 production 이 이미지보다 먼저 움직인다.
- release 의 cache 잡 키가 pr-check.yml 의 복원 키와 다르면 PR 이 늘 차가운 캐시로 굽는다.
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


def resolve(key: str, name: str) -> str:
    """캐시 키 식을 한 이름(matrix.app·matrix.name)으로 풀고 공백을 걷는다."""
    key = re.sub(r"format\('docker/\{0\}\.Dockerfile', matrix\.(?:app|name)\)", f"'docker/{name}.Dockerfile'", key)
    return re.sub(r"\s+", "", key.replace("${{ matrix.app }}", name))


def release_key(expr: str, name: str) -> str:
    """release.yml cache 잡의 KEY 식(이름별 format(...) 셋)에서 그 이름이 고르는 키를 pr-check.yml 꼴로 쓴다."""
    special = dict(re.findall(r"format\('bk-(\w+)-\{0\}', (hashFiles\([^)]*\))\)", expr))
    if name in special:
        return resolve(f"bk-{name}-${{{{ {special[name]} }}}}", name)
    default = re.search(r"format\('bk-\{0\}-\{1\}', matrix\.name, (hashFiles\(.*\))\) \}\}$", expr)
    assert default, expr
    return resolve(f"bk-{name}-${{{{ {default.group(1)} }}}}", name)


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

    def test_pr_check_runs_on_pr_and_queue_only(self) -> None:
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", read(WORKFLOWS / "pr-check.yml"))
        assert on
        self.assertEqual(sorted(re.findall(r"(?m)^  ([\w-]+):", on.group(1))), ["merge_group", "pull_request"])

    def test_release_builds_and_promotes_without_checking(self) -> None:
        code = read(WORKFLOWS / "release.yml")
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", code)
        assert on
        self.assertEqual(re.sub(r"\s+", " ", on.group(1)).strip(), "push: branches: [main] workflow_dispatch:")
        # 판정은 대기열 한 번(#1090) — release 는 PR 검사를 부르지도, 이미 검사했는지 따지지도 않는다
        self.assertNotIn("pr-check.yml", code)
        self.assertNotIn("verified_tree", code)
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", code.split("\njobs:\n", 1)[1])
        self.assertEqual(sorted(jobs), ["cache", "cache-node", "image", "main_only", "notify", "promote"])
        self.assertFalse((ROOT / "scripts" / "ci" / "verified_tree.py").exists())
        image = job_block(code, "image")
        self.assertIn("uses: ./.github/workflows/image.yml", image)
        self.assertRegex(image, r"needs:\s*main_only\s*\n")
        promote = job_block(code, "promote")
        self.assertRegex(promote, r"needs:\s*\[main_only, image\]")
        self.assertIn("needs.image.result == 'success'", promote)
        self.assertIn('bash scripts/ci/promote.sh ff "$SHA"', promote)
        self.assertIn("fetch-depth: 0", promote)
        # 캐시를 못 채워도 배포는 간다
        self.assertNotIn("cache", re.search(r"needs:\s*(\[[^\]]*\]|\S+)", promote).group(1))

    def test_release_saves_the_cache_keys_pr_check_restores(self) -> None:
        pr = read(WORKFLOWS / "pr-check.yml")
        self.assertNotIn("actions/cache/save", pr, "PR·대기열 ref 에서 저장한 캐시는 다른 PR 이 못 읽는다 — 저장은 release 에서만")
        restored = set(re.findall(r"(?m)^          key: (bk-.+)$", pr))
        release = read(WORKFLOWS / "release.yml")
        cache = job_block(release, "cache")
        names = re.findall(r"(?m)^          - \{ name: (\w+), target: [^}]*\}", cache)
        self.assertEqual(sorted(names), ["backend", "ci", "classroom", "frontend", "operator"])
        key_expr = re.sub(r"\s+", " ", re.search(r"(?ms)KEY: >-\n(.*?)\n        run:", cache).group(1)).strip()
        for name in names:
            with self.subTest(cache=name):
                self.assertIn(release_key(key_expr, name), {resolve(k, name) for k in restored})
        node = job_block(release, "cache-node")
        for key in ("pnpm-store-${{ hashFiles('pnpm-lock.yaml') }}",):
            with self.subTest(cache=key):
                self.assertIn(f"key: {key}", pr)
                self.assertIn(f"key: {key}", node)

    def test_fork_does_not_publish_promote_schedule_or_open_issues(self) -> None:
        # 포크(#1084)에는 비밀값이 없지만 GITHUB_TOKEN 으로 운영 이미지 저장소에 올리고 production 을 옮기고 이슈를 열 수 있다.
        # 본 저장소에서만 도는 조건이 그 잡들 머리에 있어야 한다(본 저장소에서는 늘 참).
        only_upstream = "github.repository == 'sandcorporation/laurio'"
        release = read(WORKFLOWS / "release.yml")
        # 승격·이미지·알림은 모두 main_only success 를 기다린다 — main_only 하나를 막으면 다 멈춘다.
        self.assertIn(f"if: {only_upstream}", job_block(release, "main_only"))
        for job in ("image", "cache", "cache-node", "notify", "promote"):
            self.assertRegex(job_block(release, job), r"needs:\s*(main_only|\[main_only)")
        self.assertIn(f"if: {only_upstream}", job_block(read(WORKFLOWS / "image.yml"), "build"))
        # 캐시 잡만은 포크 main 에서도 돈다(#1116) — 포크 PR 검사의 층 캐시가 비어 e2e 조각마다 처음부터 굽던 것.
        # 저장하는 것은 Actions 캐시뿐이고, 본 저장소에서는 main_only success 를, 포크에서는 main ref 를 요구한다.
        fork_cache = "needs.main_only.result == 'skipped' && github.repository != 'sandcorporation/laurio' && github.ref == 'refs/heads/main'"
        for job in ("cache", "cache-node"):
            with self.subTest(fork_cache=job):
                block = job_block(release, job)
                self.assertIn(fork_cache, block)
                self.assertNotRegex(block, r"(?m)^\s+permissions:")
        for job in ("image", "notify", "promote"):
            with self.subTest(upstream_only=job):
                self.assertNotIn("result == 'skipped'", job_block(release, job))
        # 매시 e2e(#1111): 실제 실패 이슈는 본 저장소에서만 — 포크는 알림 시험만
        self.assertIn("github.repository == 'sandcorporation/laurio'", job_block(read(WORKFLOWS / "e2e.yml"), "notify"))

    def test_e2e_runs_on_prs_and_hourly_on_main_not_in_the_merge_queue(self) -> None:
        # 대표 결정(#1111): PR 은 바뀐 앱의 e2e 가 「결과」 필수, 대기열은 e2e 없음, 전부는 매시 main
        pr = read(WORKFLOWS / "pr-check.yml")
        plan = job_block(pr, "plan")
        self.assertIn("pull_request) e2e_plan=$(python3 scripts/ci/e2e_plan.py --base", plan)
        self.assertNotIn("merge_group) e2e_plan", plan)
        self.assertIn('"e2e:$E2E:$want_e2e"', job_block(pr, "result"))
        hourly = read(WORKFLOWS / "e2e.yml")
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", hourly)
        assert on
        self.assertRegex(on.group(1), r"(?m)^  schedule:")
        self.assertRegex(on.group(1), r"(?m)^  workflow_dispatch:")
        self.assertIn("e2e_plan.py --all", job_block(hourly, "gate"))
        self.assertIn("CODEMIT_E2E_PLAYWRIGHT_IMAGE: 1", job_block(hourly, "e2e"))
        # 조율자 점검(stall-check.sh)이 이 제목으로 찾는다 — 바꾸지 않는다
        self.assertIn('title="e2e 실패 — main 의 화면이 깨졌을 수 있다"', job_block(hourly, "notify"))
        # 이미지 층·pnpm 캐시 저장은 release 에서만 — 매시 e2e 가 저장하는 것은 조각 시간 기록(#1112) 하나다
        saves = re.findall(r"uses: actions/cache/save@\S+[^\n]*\n\s+with:\n((?:\s{10}\S[^\n]*\n)+)", hourly)
        self.assertEqual(len(saves), hourly.count("actions/cache/save"))
        for block in saves:
            self.assertRegex(block, r"key: e2e-durations-\$\{\{ github.run_id \}\}", "매시 e2e 가 저장하는 캐시는 시간 기록뿐")
        self.assertIn("e2e_plan.py --all --durations .e2e-durations/record.json", job_block(hourly, "gate"))
        self.assertIn("e2e_plan.py --base \"$base\" --durations .e2e-durations/record.json", plan)

    def test_pr_check_also_judges_the_merge_queue(self) -> None:
        on = re.search(r"(?ms)^on:\n(.*?)(?=^\S)", read(WORKFLOWS / "pr-check.yml"))
        assert on
        self.assertRegex(on.group(1), r"(?m)^  merge_group:")

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
