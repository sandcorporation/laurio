#!/usr/bin/env python3
"""브랜치를 주어진 커밋으로 fast-forward 한다 — 앞으로만 간다(2026-10-02).

    GH_TOKEN=… scripts/ci/fast_forward.py <브랜치> <커밋>

Jenkinsfile 이 이미지·가드가 초록이면 `staging` 을, prod 배포 단계까지 초록이면 `production` 을
그 커밋으로 앞당긴다(2026-10-23 #779 전에는 `production` 의 push 가 별도 prod 잡을 깨웠다 — 지금은
아무 잡도 깨우지 않는 기록이다). `production` 은 언제나 「prod 에 배포돼 초록이었던 커밋」 그
자체여야 하므로 머지 커밋을 만들지 않는다.

- 브랜치가 이미 그 커밋을 품으면(더 새 커밋이 먼저 올라갔다) 아무것도 하지 않고 성공한다.
- 브랜치가 그 커밋에서 갈라져 있으면(누가 브랜치에 직접 커밋했다) 밀어붙이지 않고 실패한다.
- 브랜치가 없으면 그 커밋으로 만든다.

git push 가 아니라 API 로 하는 이유: Jenkins 의 체크아웃은 자격증명을 잡 설정에만 갖고 있어
워크스페이스에서 push 할 수 없다. 표준 라이브러리만 쓴다 — Jenkins 컨테이너에는 gh 가 없다.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

REPO = "sandcorporation/laurio"
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


def main() -> int:
    branch, sha = sys.argv[1], sys.argv[2]
    code, compared = call("GET", f"/repos/{REPO}/compare/{branch}...{sha}")
    if code == 404:
        code, result = call("POST", f"/repos/{REPO}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
        if code != 201:
            print(f"{branch} 를 만들지 못했다({code}): {result}")
            return 1
        print(f"{branch} 를 {sha[:12]} 로 만들었다")
        return 0
    if code != 200 or not isinstance(compared, dict):
        print(f"{branch} 와 {sha[:12]} 를 비교하지 못했다({code}): {compared}")
        return 1
    state = compared["status"]
    if state in ("identical", "behind"):
        print(f"{branch} 가 이미 {sha[:12]} 를 품는다 — 할 일 없음")
        return 0
    if state != "ahead":
        print(f"{branch} 가 {sha[:12]} 에서 갈라져 있다({state}) — fast-forward 할 수 없다. {branch} 에만 있는 커밋을 확인하라")
        return 1
    code, result = call("PATCH", f"/repos/{REPO}/git/refs/heads/{branch}", {"sha": sha, "force": False})
    if code != 200:
        # 워크플로 파일을 바꾼 커밋이면 토큰에 Workflows 쓰기 권한이 있어야 한다.
        print(f"{branch} 를 앞당기지 못했다({code}): {result}")
        return 1
    print(f"{branch} -> {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
