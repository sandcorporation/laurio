"""PR 검사 잡 하나가 실패하면 그 실행을 바로 멈춘다(#1139) — pr-check.yml 의 `fail-fast` 잡과 「결과」가 부른다.

    python3 scripts/ci/fail_fast.py watch   --skip 결과 --skip "빨리 멈춤"   # 실패를 보면 실행 취소
    python3 scripts/ci/fail_fast.py summary --skip 결과 --skip "빨리 멈춤"   # 처음 실패한 잡 · 취소된 잡

matrix 의 `fail-fast` 는 같은 matrix 안만 멈춘다. 감시 잡은 needs 없이 plan 과 함께 뜬다(실행기 줄에서 늦지 않게). 잡 사이(checks ↔ e2e ↔ celery …)는 이 감시가 멈춘다:
이 실행의 잡 목록(`filter=latest` — 「실패한 잡만 다시」 시도의 잡도 그 시도의 것)을 몇 초마다 읽어,
`--skip` 밖의 잡 하나가 failure·timed_out 으로 끝나면 실행을 취소한다. 「결과」는 `if: always()` 라 취소돼도 돌아
취소된 잡을 실패로 읽는다(거짓 초록 없음). 이 스크립트는 판정하지 않는다 — 판정은 「결과」가 needs 로만 한다.

토큰은 `GITHUB_TOKEN`(watch 는 `actions: write`, summary 는 `actions: read`). 포크 PR 은 토큰이 읽기 전용이라
취소가 403 이다 — 경고만 남기고 끝낸다(나머지 잡이 끝까지 돌고, 「결과」의 판정은 같다).
조회가 거듭 실패해도 경고로 끝낸다 — 감시가 죽으면 빨라지지 않을 뿐 틀리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from typing import Literal, Protocol, TypedDict

#: 「처음 실패」로 세는 결론 — cancelled 는 실패의 결과(취소)라 세지 않는다
FAILED = ("failure", "timed_out")

Decision = Literal["cancel", "done", "wait"]


class Job(TypedDict):
    name: str
    status: str  # queued · in_progress · completed …
    conclusion: str | None  # success · failure · cancelled · skipped · timed_out …
    completed_at: str | None


class Api(Protocol):
    def jobs(self) -> list[Job]: ...

    def cancel(self) -> int:
        """HTTP 상태 코드(202 = 취소 시작)."""
        ...


def call_prefix(jobs: Iterable[Job], skip: Sequence[str]) -> str:
    """workflow_call 로 불렸으면(after-push.yml, #1325) 잡 이름이 「<부른 잡> / <이름>」이다 — skip 이름에 붙은 그 머리.

    머리가 있으면 그 머리의 잡만 본다: 부른 쪽의 잡(뒤따른 알림 등)은 이 실행이 끝나야 도므로 기다리면 끝나지 않는다.
    """
    for j in jobs:
        for s in skip:
            if j["name"].endswith(" / " + s):
                return j["name"][: -len(s)]
    return ""


def watched(jobs: Iterable[Job], skip: Sequence[str]) -> list[Job]:
    jobs = list(jobs)
    prefix = call_prefix(jobs, skip)
    if prefix:
        return [j for j in jobs if j["name"].startswith(prefix) and j["name"][len(prefix):] not in skip]
    return [j for j in jobs if j["name"] not in skip]


def first_failure(jobs: Iterable[Job], skip: Sequence[str]) -> Job | None:
    failed = [j for j in watched(jobs, skip) if j["conclusion"] in FAILED]
    return min(failed, key=lambda j: j["completed_at"] or "~") if failed else None


def decide(jobs: Sequence[Job], skip: Sequence[str]) -> Decision:
    if first_failure(jobs, skip):
        return "cancel"
    rest = watched(jobs, skip)
    if rest and all(j["status"] == "completed" for j in rest):
        return "done"
    return "wait"


def summary(jobs: Sequence[Job], skip: Sequence[str]) -> list[str]:
    """첫 줄이 처음 실패한 잡이다 — 취소된 잡들에 묻히지 않게."""

    first = first_failure(jobs, skip)
    if first is None:
        return []
    lines = [f"처음 실패: {first['name']} ({first['conclusion']}, {first['completed_at'] or '?'})"]
    others = sorted(j["name"] for j in watched(jobs, skip) if j["conclusion"] in FAILED and j is not first)
    if others:
        lines.append(f"그 밖의 실패: {', '.join(others)}")
    cancelled = sorted(j["name"] for j in watched(jobs, skip) if j["conclusion"] == "cancelled")
    if cancelled:
        lines.append(f"취소된 잡 {len(cancelled)}개(처음 실패로 멈춤): {', '.join(cancelled)}")
    return lines


def watch(api: Api, skip: Sequence[str], *, interval: float = 10, max_errors: int = 6,
          sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print) -> int:
    errors = 0
    done_seen = 0
    while True:
        try:
            jobs = api.jobs()
            errors = 0
        except (urllib.error.URLError, OSError, ValueError) as exc:
            errors += 1
            log(f"::warning::잡 목록을 못 읽었다({errors}/{max_errors}): {exc}")
            if errors >= max_errors:
                log("::warning::감시를 그만둔다 — 실패해도 나머지 잡이 끝까지 돈다(「결과」 판정은 같다)")
                return 0
            sleep(interval)
            continue
        decision = decide(jobs, skip)
        # 「끝남」은 두 번 잇달아 봐야 믿는다 — 감시는 plan 과 함께 뜨므로, plan 이 끝난 직후 뒤 잡(matrix)이
        # 아직 목록에 펼쳐지지 않은 틈을 「모두 끝남」으로 읽고 일찍 나가지 않게
        done_seen = done_seen + 1 if decision == "done" else 0
        if done_seen >= 2:
            log("모든 잡이 끝났다 — 실패 없음")
            return 0
        if decision == "cancel":
            for line in summary(jobs, skip):
                log(line)
            try:
                code = api.cancel()
            except urllib.error.HTTPError as exc:
                code = exc.code
            except (urllib.error.URLError, OSError) as exc:
                log(f"::warning::실행 취소 요청이 닿지 않았다: {exc}")
                return 0
            if code == 202:
                log("실행을 취소했다 — 나머지 잡이 멈추고 「결과」가 실패로 난다")
            elif code == 403:
                log("::warning::취소 권한이 없다(포크 PR 의 읽기 전용 토큰) — 나머지 잡이 끝까지 돈다, 「결과」 판정은 같다")
            else:
                log(f"::warning::실행 취소가 {code} 로 끝났다(이미 끝났거나 취소 중)")
            return 0
        sleep(interval)


class GitHub:
    def __init__(self, env: dict[str, str]) -> None:
        api = env.get("GITHUB_API_URL", "https://api.github.com")
        self.run = f"{api}/repos/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
        self.token = env["GITHUB_TOKEN"]

    def _request(self, url: str, method: str = "GET") -> tuple[int, bytes]:
        req = urllib.request.Request(url, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, res.read()

    def jobs(self) -> list[Job]:
        _, body = self._request(f"{self.run}/jobs?filter=latest&per_page=100")
        data: dict[str, list[dict[str, object]]] = json.loads(body)  # 응답 JSON — 쓰는 열만 아래에서 고른다
        return [
            Job(name=str(j["name"]), status=str(j["status"]),
                conclusion=None if j.get("conclusion") is None else str(j["conclusion"]),
                completed_at=None if j.get("completed_at") is None else str(j["completed_at"]))
            for j in data["jobs"]
        ]

    def cancel(self) -> int:
        status, _ = self._request(f"{self.run}/cancel", method="POST")
        return status


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("watch", "summary"))
    parser.add_argument("--skip", action="append", default=[], help="보지 않을 잡 이름(감시 자신·「결과」)")
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args(argv)
    api = GitHub(dict(os.environ))
    if args.command == "watch":
        return watch(api, args.skip, interval=args.interval)
    try:
        lines = summary(api.jobs(), args.skip)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"::warning::잡 목록을 못 읽었다: {exc}")
        return 0
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
