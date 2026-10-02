#!/usr/bin/env python3
"""PR CI 가 초록이면 그 브랜치의 열린 main PR 을 이 커밋으로 rebase 병합한다(2026-10-02, Jenkinsfile.pr).

    GH_TOKEN=… scripts/ci/automerge.py <브랜치> <커밋>

합치지 않는 경우 — 열린 PR 이 없다, 초안이다, `hold` 라벨이 있다, PR 머리가 이 커밋이 아니다
(그 사이 새로 push 됐다). 결과는 그 커밋의 GitHub 상태 `codemit/automerge` 로 남긴다 — 빌드
자체의 초록·빨강은 시험이 정하고, 병합이 실패해도 빌드를 빨갛게 만들지 않는다(실패 이유는 이
상태의 설명과 콘솔에 있다). 표준 라이브러리만 쓴다 — Jenkins 컨테이너에는 gh 가 없다.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = "sandcorporation/laurio"
CONTEXT = "codemit/automerge"
API = "https://api.github.com"


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
    print(f"{CONTEXT}: {state} — {description}")
    call("POST", f"/repos/{REPO}/statuses/{sha}", {"state": state, "context": CONTEXT, "description": description[:140]})


def main() -> int:
    branch, sha = sys.argv[1], sys.argv[2]
    owner = REPO.split("/")[0]
    query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open", "base": "main"})
    code, pulls = call("GET", f"/repos/{REPO}/pulls?{query}")
    if code != 200:
        print(f"PR 을 찾지 못했다({code}): {pulls}")
        return 0
    if not pulls:
        print(f"{branch} 에 열린 main PR 이 없다 — 합칠 것이 없다.")
        return 0
    pr = pulls[0]
    number = pr["number"]
    if pr.get("draft"):
        status(sha, "success", f"#{number} 은 초안이라 합치지 않았다")
        return 0
    if any(label["name"] == "hold" for label in pr.get("labels", [])):
        status(sha, "success", f"#{number} 에 hold 라벨이 있어 합치지 않았다")
        return 0
    if pr["head"]["sha"] != sha:
        print(f"#{number} 의 머리가 이 커밋이 아니다({pr['head']['sha'][:12]}) — 새 빌드가 합친다.")
        return 0
    code, result = call(
        "PUT", f"/repos/{REPO}/pulls/{number}/merge", {"merge_method": "rebase", "sha": sha}
    )
    if code == 200:
        status(sha, "success", f"#{number} 을 main 에 rebase 병합했다")
    else:
        message = result.get("message") if isinstance(result, dict) else result
        status(sha, "failure", f"#{number} 병합 실패({code}): {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
