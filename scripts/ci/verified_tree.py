"""release.yml 의 verify 잡 — 이 main 커밋의 트리를 PR 검사가 이미 초록으로 돌았는가(#959).

    python3 scripts/ci/verified_tree.py <main 커밋 sha>    # GH_TOKEN·GITHUB_REPOSITORY·GITHUB_OUTPUT 을 읽는다

`skip=1` 은 **증명했을 때만** 낸다. 증명은 트리 해시가 같다는 것 하나다:

    PR 검사(pull_request)는 refs/pull/N/merge 커밋 X 를 검사한다 — plan 잡의 「검사한 커밋 <X>」 단계 이름이 X 를 남긴다.
    병합(squash) 커밋 M 의 트리 == X 의 트리  →  production 에 나갈 파일이 「결과」 초록을 받은 파일과 한 바이트도 다르지 않다.

그사이 main 이 움직여 squash 가 다른 조합을 만들었으면 트리가 달라지고, 그때는 지금처럼 전체 check 를 돈다(ruleset 의
strict 가 꺼져 있어 release check 가 「동시에 병합된 두 PR 의 조합」을 잡는 자리다). 다음도 전체 check 다:
- 그 PR 검사가 시험을 건너뛰었다(문서만) — 그 판단은 그때의 base 에 기댔다.
- 이미지 층 캐시 키(Dockerfile·lockfile)를 바꾼 커밋 — 캐시는 main 의 check 만 저장한다(#932). 건너뛰면 새 키가 영영 비어 PR 이 느려진다.
- API 가 무엇이든 실패했다 — 증명 못 함 = 전체 check.

PR 검사는 바뀐 경로로 일부 잡만 돈다(#1082, `changed.sh`). 건너뛴 잡을 받는 조건은 둘이다(#1097):
- PR 실행의 건너뜀이 **병합 커밋의 diff(`sha^..sha`)에 `changed.sh` 를 다시 돌려 나온 계획과 정확히 같다**(더 건너뛰었으면 거절).
- 건너뛴 쪽이 기대는 부모 커밋이 검증된 판이다 — 부모의 release 실행이 success(check 초록 또는 같은 증명으로 생략)였다.
  이 조건이 없으면 앞 커밋의 release 가 빨강일 때 건너뛴 쪽(예: 프런트만 PR 의 백엔드)이 어디서도 검사되지 않은 채 승격된다.
  부모의 release 가 아직 돌고 있으면 증명 못 함 = 전체 check.

GitHub API 는 GITHUB_TOKEN 의 읽기 권한(contents·pull-requests·actions: read)으로만 읽는다.
판정(`decide`)은 순수 함수라 scripts/test_release_flow.py 가 고정한다.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

# pr-check.yml plan 잡의 단계 이름 — 이 문자열을 바꾸면 release 가 증명을 못 해 늘 전체 check 를 돈다(안전한 쪽).
TESTED_STEP = re.compile(r"^검사한 커밋 ([0-9a-f]{40})$")
# pr-check.yml 의 hashFiles(...) 입력 — 캐시 키가 바뀌는 파일
CACHE_KEY_FILES = ("docker/*.Dockerfile", "backend/uv.lock", "pnpm-lock.yaml")
RESULT_JOB = "결과"
ALL_ON = ("1", "1", "1")  # changed.sh 의 (TESTS, BACK, FRONT) — 아무것도 건너뛰지 않는 계획
# PR 검사에서 guard(matrix: `guard (frontend)` …)는 늘 skipped 다(#1015, plan 출력 guard=''). 이것만 초록으로 받는다.
GUARD_JOB = re.compile(r"^guard( \(.*\))?$")


@dataclass(frozen=True)
class Job:
    name: str
    conclusion: str | None
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Run:
    run_id: int
    conclusion: str | None
    jobs: tuple[Job, ...]
    tested_tree: str | None  # 「검사한 커밋」 X 의 트리 — 못 읽었으면 None


@dataclass(frozen=True)
class Decision:
    skip: bool
    reason: str


def tested_commit(jobs: tuple[Job, ...]) -> str | None:
    for job in jobs:
        if job.name == "plan":
            for step in job.steps:
                found = TESTED_STEP.match(step)
                if found:
                    return found.group(1)
    return None


def job_role(name: str) -> str:
    """잡 이름 → changed.sh 가 켜고 끄는 묶음. 그 밖의 잡은 other(늘 success 여야 한다)."""
    if GUARD_JOB.match(name):
        return "guard"
    if name == "checks static":
        return "static"
    if name.startswith("checks pytest"):
        return "pytest"
    if name == "checks web":
        return "web"
    if name.startswith("checks "):  # 건너뛰어 matrix 이름이 풀리지 않은 잡(`checks ${{ matrix.name }}`)
        return "checks-unresolved"
    if name in ("celery", "agent-grader"):
        return name
    return "other"


def needed_roles(plan: tuple[str, str, str]) -> set[str]:
    """계획(TESTS, BACK, FRONT)이 돌려야 한다고 하는 묶음."""
    tests, back, front = plan
    roles: set[str] = set()
    if tests == "1":
        roles.add("static")
    if back == "1":
        roles |= {"pytest", "celery", "agent-grader"}
    if front == "1":
        roles.add("web")
    return roles


def run_is_full_green(run: Run, plan: tuple[str, str, str] | None = None) -> str | None:
    """초록이고 시험을 다 돌았으면 None, 아니면 까닭.

    plan 이 없으면 guard 말고는 모두 success 여야 한다. plan 이 있으면 계획이 돌리라는 묶음은 있고 success,
    계획이 건너뛰라는 묶음은 없거나 skipped 여야 한다 — 계획과 다르게 건너뛰었거나 더 돌았으면 거절."""
    if plan is None:
        return run_is_green_strict(run)
    if run.conclusion != "success":
        return f"실행 {run.run_id} 결론 {run.conclusion}"
    if RESULT_JOB not in {job.name for job in run.jobs}:
        return f"실행 {run.run_id} 에 「{RESULT_JOB}」 잡이 없다"
    need = needed_roles(plan)
    seen: set[str] = set()
    bad: list[str] = []
    for job in run.jobs:
        role = job_role(job.name)
        seen.add(role)
        if role == "guard":
            ok = job.conclusion in ("success", "skipped")
        elif role in need or role == "other":
            ok = job.conclusion == "success"
        else:  # 계획이 건너뛰라는 묶음
            ok = job.conclusion == "skipped"
        if not ok:
            bad.append(f"{job.name}={job.conclusion}")
    missing = sorted(need - seen)
    if missing:
        bad.append(f"계획이 돌리라는 묶음이 없다: {', '.join(missing)}")
    if bad:
        return f"실행 {run.run_id} 가 계획(TESTS={plan[0]} BACK={plan[1]} FRONT={plan[2]})과 다르다: {', '.join(sorted(bad))}"
    return None


def run_is_green_strict(run: Run) -> str | None:
    if run.conclusion != "success":
        return f"실행 {run.run_id} 결론 {run.conclusion}"
    names = {job.name for job in run.jobs}
    if RESULT_JOB not in names:
        return f"실행 {run.run_id} 에 「{RESULT_JOB}」 잡이 없다"
    not_green = sorted(
        f"{job.name}={job.conclusion}"
        for job in run.jobs
        if job.conclusion != "success" and not (job.conclusion == "skipped" and GUARD_JOB.match(job.name))
    )
    if not_green:
        # guard 말고는 skipped 도 받지 않는다 — 문서만이라 시험을 건너뛴 실행은 그때 base 에 기댄 판단이다
        return f"실행 {run.run_id} 에 초록이 아닌 잡: {', '.join(not_green)}"
    return None


def decide(
    merge_tree: str,
    parent_count: int,
    changed: list[str],
    runs: list[Run],
    plan: tuple[str, str, str] | None = None,
    parent_released: bool = False,
) -> Decision:
    """plan: 병합 커밋 diff 에 changed.sh 를 돌린 (TESTS, BACK, FRONT). 없으면(못 읽음) 건너뜀을 받지 않는다.
    parent_released: 부모 커밋의 release 실행이 success 였다."""
    # 건너뜀을 받는 것은 계획이 읽혔고(None 아님), 일부만 돌리라는 계획이며, 부모가 검증된 판일 때뿐이다.
    # 아니면 guard 말고는 모두 success 인 실행만 증명으로 받는다(옛 규칙).
    accepts_skips = plan is not None and plan != ALL_ON and parent_released
    plan_for_runs = plan if accepts_skips else None
    if parent_count != 1:
        return Decision(False, f"부모가 {parent_count} 개 — squash 병합 커밋이 아니다")
    touched = sorted(p for p in changed if any(fnmatch.fnmatch(p, g) for g in CACHE_KEY_FILES))
    if touched:
        return Decision(False, f"이미지 층 캐시 키 파일이 바뀌었다({', '.join(touched)}) — main check 가 캐시를 저장해야 한다")
    if not runs:
        return Decision(False, "이 커밋을 만든 PR 의 초록 PR 검사 실행이 없다")
    whys = []
    for run in runs:
        why = run_is_full_green(run, plan_for_runs)
        if why:
            whys.append(why)
            continue
        if run.tested_tree is None:
            whys.append(f"실행 {run.run_id} 의 「검사한 커밋」을 읽지 못했다")
            continue
        if run.tested_tree == merge_tree:
            return Decision(True, f"PR 검사 실행 {run.run_id} 가 같은 트리 {merge_tree[:12]} 를 초록으로 돌았다")
        whys.append(f"실행 {run.run_id} 의 트리 {run.tested_tree[:12]} ≠ 병합 트리 {merge_tree[:12]}(그사이 main 이 움직였다)")
    return Decision(False, "; ".join(whys))


# ---- GitHub·git 에서 읽기 -------------------------------------------------------------


def gh_json(path: str) -> object:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"객체가 아니다: {type(value).__name__}")
    return value


def as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"목록이 아니다: {type(value).__name__}")
    return value


def opt_str(value: object) -> str | None:
    return None if value is None else str(value)


def read_runs(repo: str, sha: str) -> list[Run]:
    pulls = [as_dict(p) for p in as_list(gh_json(f"repos/{repo}/commits/{sha}/pulls"))]
    merged = [p for p in pulls if p.get("merge_commit_sha") == sha]
    if len(merged) != 1:
        return []
    head = as_dict(merged[0]["head"])["sha"]
    listed = as_dict(gh_json(f"repos/{repo}/actions/workflows/pr-check.yml/runs?event=pull_request&head_sha={head}&per_page=20"))
    runs = []
    for raw in as_list(listed["workflow_runs"])[:5]:  # 최근 것부터
        item = as_dict(raw)
        if item.get("head_sha") != head:
            continue
        run_id = int(str(item["id"]))
        jobs_raw = as_list(as_dict(gh_json(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"))["jobs"])
        jobs = tuple(
            Job(
                name=str(as_dict(j)["name"]),
                conclusion=opt_str(as_dict(j).get("conclusion")),
                steps=tuple(str(as_dict(s)["name"]) for s in as_list(as_dict(j).get("steps") or [])),
            )
            for j in jobs_raw
        )
        tested = tested_commit(jobs)
        tree = None
        if tested:
            tree = str(as_dict(as_dict(gh_json(f"repos/{repo}/git/commits/{tested}"))["tree"])["sha"])
        runs.append(Run(run_id, opt_str(item.get("conclusion")), jobs, tree))
    return runs


def release_succeeded(repo: str, sha: str) -> bool:
    listed = as_dict(gh_json(f"repos/{repo}/actions/workflows/release.yml/runs?head_sha={sha}&event=push&per_page=10"))
    return any(
        as_dict(r).get("head_sha") == sha and as_dict(r).get("conclusion") == "success" for r in as_list(listed["workflow_runs"])
    )


def changed_plan(sha: str) -> tuple[str, str, str]:
    out = subprocess.run(["bash", "scripts/ci/changed.sh", f"{sha}^", sha], check=True, capture_output=True, text=True).stdout
    found = dict(line.split("=", 1) for line in out.split())
    return found["TESTS"], found["BACK"], found["FRONT"]


def main(argv: list[str]) -> int:
    sha = argv[1]
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        merge_tree = git("rev-parse", f"{sha}^{{tree}}")
        parents = git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        changed = git("diff", "--name-only", f"{sha}^", sha).splitlines() if len(parents) == 1 else []
        plan = changed_plan(sha) if len(parents) == 1 else None
        released = plan is not None and plan != ALL_ON and release_succeeded(repo, parents[0])
        decision = decide(merge_tree, len(parents), changed, read_runs(repo, sha), plan, released)
    except (subprocess.CalledProcessError, ValueError, KeyError, TypeError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else repr(error)
        decision = Decision(False, f"증명 실패 — {detail[:300]}")
    verdict = "건너뜀(이미 검사한 트리)" if decision.skip else "전체 check"
    print(f"판정: {verdict} — {decision.reason}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a", encoding="utf-8") as out:
        out.write(f"skip={'1' if decision.skip else '0'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"### release check 판정: {verdict}\n\n{decision.reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
