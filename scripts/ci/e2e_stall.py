#!/usr/bin/env python3
"""붉은 e2e 가 Docker VM 의 정지 탓인지 가린다(#716). 열차의 macos 단계가 e2e 뒤에 부른다.

    python3 scripts/ci/e2e_stall.py test-results > test-results/e2e-verdict.json

**모양.** 열차 #1840·#1890 에서 강의실 e2e 넷이 한꺼번에 3초 한도에 걸렸다. #1890 의 증거는
backend 접근 로그의 **3.9초 동안 요청 0건**(앞뒤는 초당 50~146건, 틈 앞뒤 요청은 전부 8~25ms)과,
시험 넷의 마지막 요청이 서로 다른 두 Next 컨테이너에서 같은 시각에 미완료로 끝난 것이었다 —
코드가 느린 것이 아니라 Docker VM(또는 호스트 → 컨테이너 포트 전달) 전체가 멈췄다.

그래서 판정은 셋이 모두 맞을 때만 「인프라 고장」이다.
  1. 실패한 시험이 하나 이상이고, `.last-run.json` 이 센 실패 수와 거둔 실패 폴더 수가 같다
     (못 본 실패가 있으면 판정하지 않는다). `status: failed` 인데 `failedTests` 가 빈 프로젝트
     (「No tests found」, globalSetup 오류)가 하나라도 있으면 판정하지 않는다(#719).
  2. 실패가 전부 「Test timeout of …ms exceeded」다(단언 실패가 하나라도 있으면 코드 탓이다).
  3. 시험마다 그 마감 시각(trace 의 시작 wallTime + testTimeout)이 backend 접근 로그의
     **3초 이상 요청 0건 틈** 안에 있다. 틈은 앞뒤에 요청이 있는 것만 센다(로그 끝의 정적은 틈이 아니다).
     testTimeout 은 설정의 한도라, 스펙이 `test.setTimeout`·`test.slow` 로 한도를 바꾸면 마감이 어긋난다
     (지금 스펙은 쓰지 않는다 — #719).

2 는 거르는 힘이 거의 없다 — 시험 한도(3초)가 `expect` 의 기본 기다림(5초)보다 짧아 흔한 화면 회귀도
거의 다 timeout 으로 끝난다. 판정은 사실상 3 에 기댄다. 그런데 브라우저가 없는 요소를 기다리는 동안은
backend 를 부르지 않을 수 있어, 일꾼 하나인 `@exclusive` 패스나 프로젝트 끝에 시험 하나만 남았을 때
코드 탓의 멈춤도 3 을 만족할 수 있다. 그 대가는 빌드 한 번이다 — `train.py fail` 의 인프라 재실행은
가르기 사슬 전체에 한 번이고, 가른 묶음은 그 몫을 물려받는다(#718).

표준 라이브러리만 쓴다 — macos 노드의 시스템 python3 로 돈다.
"""

from __future__ import annotations

import calendar
import json
import pathlib
import re
import sys
import time
import zipfile

MIN_GAP_SECONDS = 3.0
# Docker `logs --timestamps` 의 접두(나노초, UTC) + gunicorn 접근 로그의 「메서드 경로 HTTP/」.
ACCESS = re.compile(
    r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?Z (?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \S+ HTTP/"
)
TIMEOUT = re.compile(r"Test timeout of \d+ms exceeded")


def epoch(stamp: str, fraction: str | None) -> float:
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S")) + (float(fraction) if fraction else 0.0)


def iso(seconds: float) -> str:
    whole = int(seconds)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(whole)) + f".{int((seconds - whole) * 1000):03d}Z"


def access_times(lines) -> list[float]:
    """backend 로그 줄에서 접근 로그의 시각(초, UTC)만 뽑는다 — celery·마이그레이션 줄은 뺀다."""
    times = []
    for line in lines:
        match = ACCESS.search(line)
        if match:
            times.append(epoch(match.group(1), match.group(2)))
    return sorted(times)


def quiet_gaps(times: list[float], min_seconds: float = MIN_GAP_SECONDS) -> list[tuple[float, float]]:
    """이웃한 두 요청 사이가 min_seconds 이상인 틈 — (앞 요청 시각, 뒤 요청 시각)."""
    return [(a, b) for a, b in zip(times, times[1:]) if b - a >= min_seconds]


def gap_at(gaps: list[tuple[float, float]], moment: float) -> tuple[float, float] | None:
    for start, end in gaps:
        if start <= moment <= end:
            return start, end
    return None


def trace_window(trace_zip: pathlib.Path) -> tuple[float, float] | None:
    """trace.zip 의 test.trace 첫 줄(시작 wallTime ms, testTimeout ms) → (시작, 마감) 초."""
    try:
        with zipfile.ZipFile(trace_zip) as archive:
            first = archive.read("test.trace").decode("utf-8", "replace").splitlines()[0]
        head = json.loads(first)
        start = float(head["wallTime"]) / 1000
        return start, start + float(head["testTimeout"]) / 1000
    except (OSError, KeyError, IndexError, ValueError, zipfile.BadZipFile):
        return None


def classify(results: pathlib.Path) -> dict:
    playwright = results / "playwright"
    expected = 0
    for last_run in playwright.glob("*/.last-run.json"):
        try:
            run = json.loads(last_run.read_text())
        except (OSError, ValueError):
            return {"infra": False, "reason": f"{last_run} 을 읽지 못했다"}
        failed = run.get("failedTests", [])
        if run.get("status") == "failed" and not failed:
            # 「No tests found」·globalSetup 오류 — 시험 없이 깨진 프로젝트는 정지로 설명되지 않는다.
            return {"infra": False, "reason": f"{last_run.parent.name} 은 실패한 시험 없이 실패했다"}
        expected += len(failed)
    folders = sorted(p.parent for p in playwright.glob("*/*/error-context.md"))
    if not folders:
        return {"infra": False, "reason": "실패한 시험이 없다"}
    if len(folders) != expected:
        return {"infra": False, "reason": f"실패 {expected}건 중 {len(folders)}건만 거뒀다"}
    try:
        with open(results / "stack" / "backend.log", encoding="utf-8", errors="replace") as log:
            gaps = quiet_gaps(access_times(log))
    except OSError:
        return {"infra": False, "reason": "backend.log 가 없다"}
    found = None
    for folder in folders:
        if not TIMEOUT.search((folder / "error-context.md").read_text(encoding="utf-8", errors="replace")):
            return {"infra": False, "reason": f"{folder.name} 은 시간 초과가 아니다"}
        window = trace_window(folder / "trace.zip")
        if window is None:
            return {"infra": False, "reason": f"{folder.name} 의 trace 를 읽지 못했다"}
        gap = gap_at(gaps, window[1])
        if gap is None:
            return {"infra": False, "reason": f"{folder.name} 의 마감({iso(window[1])})에 backend 는 요청을 받고 있었다"}
        found = found or gap
    start, end = found
    return {
        "infra": True,
        "failed": len(folders),
        "gap": {"start": iso(start), "end": iso(end), "seconds": round(end - start, 1)},
        "reason": f"backend 요청 0건 {end - start:.1f}초 틈 @{iso(start)}",
    }


def main(argv: list[str]) -> int:
    results = pathlib.Path(argv[1] if len(argv) > 1 else "test-results")
    print(json.dumps(classify(results), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
