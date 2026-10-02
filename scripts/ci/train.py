#!/usr/bin/env python3
"""줄 선 PR 을 묶어 최신 main 위에서 한 번 시험하고, 초록이면 차례로 합친다(2026-10-03, Jenkinsfile.train).

    GH_TOKEN=… scripts/ci/train.py enqueue <커밋>    # PR CI 가 초록이면 그 커밋을 줄 세운다
    GH_TOKEN=… scripts/ci/train.py plan [--max N]    # 줄 선 PR 을 main 위에 쌓고 train.plan 을 쓴다
    GH_TOKEN=… scripts/ci/train.py assemble          # train.plan 그대로 다시 쌓는다(다른 노드·단계)
    GH_TOKEN=… scripts/ci/train.py merge             # 묶음이 초록이면 차례로 rebase 병합한다
    GH_TOKEN=… scripts/ci/train.py fail              # 묶음이 붉으면 다음 묶음 크기를 정한다

`TRAIN_DRY_RUN=1` 이면 GitHub 에 상태도 병합도 쓰지 않는다(손으로 시험할 때).

**왜 묶는가.** 예전에는 PR 마다 macos 에서 e2e 를 따로 돌렸다(이미지 셋 굽기 포함 약 8분, 노드
실행기는 하나). PR 넷이면 줄 서서 32분이었고, 더 나쁘게는 각 PR 이 자기가 갈라진 옛 main 위에서만
시험됐다 — 먼저 합쳐진 PR 과 충돌하거나 함께 깨지는 조합은 아무도 보지 않았다(#530·#532 가 서로
충돌한 채 둘 다 초록이었다). 묶음은 **최신 main + 줄 선 PR 전부**를 한 번 시험하므로 둘 다 닫는다.

**줄은 커밋 상태 하나다.** PR CI(sub 검사)가 초록이면 그 머리 커밋의 `codemit/automerge` 를
`pending`(「다음 묶음을 기다린다」)으로 둔다. 묶음은 열린 main PR 중 머리 커밋의 그 상태가 `pending`
인 것만 고른다 — 새로 push 하면 새 커밋에는 상태가 없으니 저절로 줄에서 빠지고, 그 PR CI 가 다시
세운다. 초안·`hold` 라벨은 줄에 서 있어도 고르지 않는다(풀면 다음 묶음이 가져간다 — 다시 빌드할
필요가 없다). `failure` 는 「이 커밋으로는 안 된다」이고, PR CI 를 다시 돌리면 `pending` 으로 돌아온다.

**쌓기는 cherry-pick 이다.** PR 마다 main 과 갈라진 뒤의 커밋을 차례로 얹는다 — GitHub 의 rebase
병합과 같은 일이다. 얹히지 않는 PR(충돌, 병합 커밋)은 `failure` 로 돌려보내고 나머지로 묶는다.
노드·단계가 바뀌면 같은 계획으로 다시 쌓고, 트리 해시가 계획과 같은지 확인한다.

**붉으면 반으로 가른다.** 묶음이 둘 이상이면 앞의 절반만으로 다시 돈다(`fail` 이 다음 크기를
적는다). 하나만 묶은 시험이 붉으면 그 PR 에 `failure` 를 남긴다. 인프라 고장이면 이 가르기가 PR
하나를 억울하게 잡을 수 있다 — PR CI 를 다시 돌리면 줄로 돌아온다.

표준 라이브러리만 쓴다 — Jenkins 컨테이너(sub)에는 gh 가 없다. 토큰은 URL 이 아니라 헤더로
넘겨 git 의 오류 출력에 실리지 않게 한다.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = "sandcorporation/laurio"
REMOTE = f"https://github.com/{REPO}.git"
CONTEXT = "codemit/automerge"
API = "https://api.github.com"
PLAN = "train.plan"
TIPS = "train.tips"
DEFAULT_MAX = 8
WAITING = "다음 묶음을 기다린다"
GIT_IDENTITY = ["-c", "user.name=codemit-train", "-c", "user.email=ci@codemit.invalid"]


# --- GitHub ------------------------------------------------------------------


def call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    request = urllib.request.Request(
        f"{API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode(errors="replace")


def status(sha: str, state: str, description: str) -> None:
    print(f"  {sha[:12]} {CONTEXT}: {state} — {description}")
    if os.environ.get("TRAIN_DRY_RUN"):  # 손으로 시험할 때 — 상태도 병합도 쓰지 않는다
        return
    call("POST", f"/repos/{REPO}/statuses/{sha}", {"state": state, "context": CONTEXT, "description": description[:140]})


def queue_state(sha: str) -> str | None:
    code, combined = call("GET", f"/repos/{REPO}/commits/{sha}/status")
    if code != 200 or not isinstance(combined, dict):
        return None
    for entry in combined.get("statuses", []):  # 최신이 앞이다
        if entry.get("context") == CONTEXT:
            return entry.get("state")
    return None


def open_pulls() -> list[dict]:
    pulls: list[dict] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"state": "open", "base": "main", "per_page": 100, "page": page})
        code, batch = call("GET", f"/repos/{REPO}/pulls?{query}")
        if code != 200 or not isinstance(batch, list):
            raise SystemExit(f"열린 PR 을 읽지 못했다({code}): {batch}")
        pulls.extend(batch)
        if len(batch) < 100:
            return sorted(pulls, key=lambda pr: pr["number"])
        page += 1


def build_label() -> str:
    return f"묶음 #{os.environ.get('BUILD_NUMBER', '?')}"


# --- git ---------------------------------------------------------------------


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 실패:\n{result.stderr.strip()}")
    return result.stdout.strip()


def fetch(numbers: list[int]) -> None:
    secret = base64.b64encode(f"x-access-token:{os.environ['GH_TOKEN']}".encode()).decode()
    refspecs = ["+refs/heads/main:refs/train/main"] + [f"+refs/pull/{n}/head:refs/train/pr-{n}" for n in numbers]
    git("-c", "credential.helper=", "-c", f"http.extraHeader=AUTHORIZATION: basic {secret}",
        "fetch", "--quiet", "--no-tags", REMOTE, *refspecs)


def reset_to(sha: str) -> None:
    git("cherry-pick", "--abort", check=False)
    git("checkout", "--quiet", "--force", "--detach", sha)
    git("reset", "--quiet", "--hard", sha)
    git("clean", "--quiet", "-fd", "--exclude", PLAN, "--exclude", TIPS)


def stack(fork: str, head: str) -> str | None:
    """main 과 갈라진 뒤의 커밋을 지금 HEAD 위에 얹는다. 실패하면 이유를 돌려주고 HEAD 를 되돌린다."""
    before = git("rev-parse", "HEAD")
    if git("rev-list", "--merges", f"{fork}..{head}"):
        return "병합 커밋이 있어 rebase 로 얹을 수 없다 — main 으로 rebase 해 주세요"
    if not git("rev-list", f"{fork}..{head}"):
        return None
    result = subprocess.run(
        ["git", *GIT_IDENTITY, "cherry-pick", "--allow-empty", "--keep-redundant-commits", f"{fork}..{head}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        reset_to(before)
        return "최신 main 위에 얹히지 않는다(충돌) — main 으로 rebase 해 주세요"
    return None


def touches_code(base: str) -> bool:
    files = git("diff", "--name-only", base, "HEAD").splitlines()
    return not files or any(not (f.endswith(".md") or f.startswith("docs/")) for f in files)


# --- 명령 ----------------------------------------------------------------------


def enqueue(sha: str) -> int:
    status(sha, "pending", WAITING)
    return 0


def plan(limit: int) -> int:
    limit = limit or DEFAULT_MAX
    waiting = []
    for pr in open_pulls():
        if pr.get("draft") or any(label["name"] == "hold" for label in pr.get("labels", [])):
            continue
        if pr["head"]["repo"] is None or pr["head"]["repo"]["full_name"] != REPO:
            continue
        if queue_state(pr["head"]["sha"]) == "pending":
            waiting.append(pr)
    print(f"줄 선 PR: {[pr['number'] for pr in waiting] or '없음'} (이번 묶음 상한 {limit})")
    entries: list[dict] = []
    base = ""
    tree = ""
    if waiting:
        fetch([pr["number"] for pr in waiting])
        base = git("rev-parse", "refs/train/main")
        reset_to(base)
        for pr in waiting:
            if len(entries) >= limit:
                break
            head = git("rev-parse", f"refs/train/pr-{pr['number']}")
            if head != pr["head"]["sha"]:
                print(f"#{pr['number']} 의 머리가 그 사이 바뀌었다 — 다음 묶음에.")
                continue
            fork = git("merge-base", base, head)
            reason = stack(fork, head)
            if reason:
                print(f"#{pr['number']} 을 뺀다: {reason}")
                status(head, "failure", reason)
                continue
            entries.append({"number": pr["number"], "branch": pr["head"]["ref"], "head": head, "fork": fork})
        tree = git("rev-parse", "HEAD^{tree}")
    run_tests = "1" if entries and touches_code(base) else "0"
    with open(PLAN, "w") as out:
        json.dump({"base": base, "tree": tree, "entries": entries}, out, indent=2)
    with open("train.env", "w") as out:
        out.write(f"COUNT={len(entries)}\nRUN_TESTS={run_tests}\n")
    numbers = ", ".join(f"#{e['number']}" for e in entries)
    print(f"{build_label()}: {numbers or '묶을 것이 없다'} (시험 {'함' if run_tests == '1' else '문서만'})")
    for entry in entries:
        status(entry["head"], "pending", f"{build_label()}에서 시험 중 — {numbers}")
    return 0


def load_plan() -> dict:
    with open(PLAN) as source:
        return json.load(source)


def assemble() -> int:
    data = load_plan()
    if not data["entries"]:
        return 0
    fetch([e["number"] for e in data["entries"]])
    reset_to(data["base"])
    tips = []
    for entry in data["entries"]:
        reason = stack(entry["fork"], entry["head"])
        if reason:
            raise SystemExit(f"계획대로 다시 쌓지 못했다(#{entry['number']}): {reason}")
        tips.append(git("rev-parse", "HEAD"))
    tree = git("rev-parse", "HEAD^{tree}")
    if tree != data["tree"]:
        raise SystemExit(f"다시 쌓은 트리({tree[:12]})가 계획({data['tree'][:12]})과 다르다")
    with open(TIPS, "w") as out:
        json.dump(tips, out)
    print(f"계획대로 쌓았다: main {data['base'][:12]} + {len(tips)}개 PR → 트리 {tree[:12]}")
    return 0


def merge() -> int:
    data = load_plan()
    with open(TIPS) as source:
        tips = json.load(source)
    merged = -1
    for index, entry in enumerate(data["entries"]):
        number = entry["number"]
        code, pr = call("GET", f"/repos/{REPO}/pulls/{number}")
        if code != 200 or not isinstance(pr, dict) or pr.get("state") != "open":
            print(f"#{number} 이 더는 열려 있지 않다 — 여기서 멈춘다.")
            break
        if pr["head"]["sha"] != entry["head"]:
            print(f"#{number} 에 그 사이 새 push 가 있었다 — 여기서 멈춘다(새 커밋은 PR CI 가 다시 줄 세운다).")
            break
        if os.environ.get("TRAIN_DRY_RUN"):
            print(f"(시험 실행) #{number} 을 합쳤을 것이다.")
            merged = index
            continue
        code, result = call("PUT", f"/repos/{REPO}/pulls/{number}/merge", {"merge_method": "rebase", "sha": entry["head"]})
        if code != 200:
            message = result.get("message") if isinstance(result, dict) else result
            status(entry["head"], "failure", f"{build_label()} 은 초록이었지만 병합이 거절됐다({code}): {message}")
            break
        status(entry["head"], "success", f"{build_label()}으로 main 에 rebase 병합했다")
        merged = index
    if merged < 0:
        print("합친 것이 없다.")
        return 0
    with open(".train-merged", "w") as out:
        out.write(f"{data['base']} {tips[merged]}\n")
    if merged == len(data["entries"]) - 1:
        code, commit = call("GET", f"/repos/{REPO}/commits/main")
        main_tree = commit["commit"]["tree"]["sha"] if code == 200 and isinstance(commit, dict) else "?"
        if main_tree != data["tree"]:
            print(f"경고: 합친 main 의 트리({main_tree[:12]})가 시험한 트리({data['tree'][:12]})와 다르다 — "
                  "그 사이 main 에 다른 커밋이 들어왔거나 GitHub 의 rebase 가 다르게 풀었다.")
        else:
            print(f"합친 main 의 트리가 시험한 트리와 같다({main_tree[:12]}).")
    return 0


def fail() -> int:
    data = load_plan()
    entries = data["entries"]
    if len(entries) > 1:
        half = math.ceil(len(entries) / 2)
        print(f"{build_label()}({len(entries)}개)이 붉었다 — 앞의 {half}개로 다시 돈다.")
        for entry in entries:
            status(entry["head"], "pending", f"{build_label()}이 붉었다 — 묶음을 반으로 갈라 다시 돈다")
        next_max = half
    else:
        for entry in entries:
            status(entry["head"], "failure", f"이 PR 하나만 묶은 {build_label()}이 붉었다 — 빌드 기록을 보세요")
        next_max = 0
    with open("train.next", "w") as out:
        out.write(f"NEXT_MAX={next_max}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("enqueue").add_argument("sha")
    sub.add_parser("plan").add_argument("--max", type=int, default=0)
    sub.add_parser("assemble")
    sub.add_parser("merge")
    sub.add_parser("fail")
    args = parser.parse_args()
    if args.command == "enqueue":
        return enqueue(args.sha)
    if args.command == "plan":
        return plan(args.max)
    return {"assemble": assemble, "merge": merge, "fail": fail}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
