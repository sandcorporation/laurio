#!/usr/bin/env python3
"""붉은 e2e 가 Docker VM 의 정지 탓인지 가린다(#716). 열차의 macos 단계가 e2e 뒤에 부른다.

    python3 scripts/ci/e2e_stall.py test-results > test-results/e2e-verdict.json
    python3 scripts/ci/e2e_stall.py images arm64 > test-results/e2e-verdict.json   # 아래 「이미지 굽기의 실패」

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

**이미지 굽기의 실패**(#729). 열차의 sub·macos 가 `scripts/ci/images.sh` 로 이미지를 굽다 붉으면
`images <arch>` 가 같은 모양의 판정을 낸다.

    python3 scripts/ci/e2e_stall.py images arm64 > test-results/e2e-verdict.json

images.sh 는 서비스마다 `.images-<arch>.result` 에 `서비스=built|skipped|failed` 를 적고, 실패한 서비스의
로그를 `test-results/images-<arch>/<서비스>.log` 에 남긴다. 판정은 셋이 모두 맞을 때만 「인프라 고장」이다.
  1. 결과 파일이 있고 `failed` 가 하나 이상이다(없으면 preflight·사용법 오류 — buildx 가 없다 같은 노드
     설정은 다시 돌아도 낫지 않으므로 판정하지 않는다).
  2. 실패한 서비스마다 로그가 있고, 그 로그에 **코드 탓 문구**(`CODE_FAILURE`)가 없다 — Dockerfile 의 RUN
     단계가 0 아닌 코드로 끝났다(`did not complete successfully: exit code`), COPY 할 경로가 없다
     (`failed to compute cache key`), Dockerfile 을 못 읽었다, 대상 단계가 없다. RUN 안의 `pnpm install`
     이 네트워크로 죽어도 이 문구가 나오므로 코드 탓으로 센다(좁게 잡는다 — 잘못 넣은 대가가 더 크다).
  3. 그 로그마다 **인프라 문구**(`INFRA_FAILURE`)가 하나 이상 있다 — 레지스트리의 5xx·429, 연결 끊김·시간
     초과·이름 풀이 실패, BuildKit 데몬과의 연결(rpc Unavailable), 디스크가 찼다. 어느 쪽도 아니면 판정하지
     않는다(모르는 실패를 인프라라 부르지 않는다).
종료코드는 images.sh 의 것(1 = 서비스 실패, 2 = 사용법)이 아니라 이 결과 파일과 로그로 가른다 — buildx 는
어느 실패든 1 로 끝나 둘을 가르지 못한다.

`train.py fail` 은 붉은 쪽(sub·macos)마다 판정이 있고 **전부** 인프라일 때만 같은 묶음을 다시 돈다 —
붉은 쪽 하나라도 판정이 없으면(검사·가드·celery 가 붉다) 가른다.

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
# 이미지 굽기(#729) — 머리말 「이미지 굽기의 실패」. 코드 탓이 하나라도 있으면 인프라가 아니다.
CODE_FAILURE = re.compile(
    r"did not complete successfully: exit code"
    r"|failed to compute cache key"
    r"|dockerfile parse error|failed to parse dockerfile|unknown instruction"
    r"|target stage \S+ could not be found",
    re.IGNORECASE,
)
INFRA_FAILURE = re.compile(
    r"unexpected status(?: from \w+ request to \S+)?: (?:5\d\d|429)"
    r"|\b(?:500 Internal Server Error|502 Bad Gateway|503 Service Unavailable|504 Gateway Time-?out)\b"
    r"|toomanyrequests|429 Too Many Requests"
    r"|connection reset by peer|connection refused|broken pipe|i/o timeout|TLS handshake timeout"
    r"|no such host|context deadline exceeded|unexpected EOF|failed to do request"
    r"|rpc error: code = (?:Unavailable|Canceled|DeadlineExceeded)"
    r"|Cannot connect to the Docker daemon|no space left on device",
    re.IGNORECASE,
)


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


def classify_images(arch: str, root: pathlib.Path = pathlib.Path(".")) -> dict:
    """images.sh 의 결과와 실패 로그 → 판정(머리말 「이미지 굽기의 실패」)."""
    try:
        lines = (root / f".images-{arch}.result").read_text().split()
    except OSError:
        return {"infra": False, "reason": f"images.sh({arch}) 가 결과를 남기지 않았다 — preflight 에서 멈췄다"}
    failed = [line.split("=", 1)[0] for line in lines if line.endswith("=failed")]
    if not failed:
        return {"infra": False, "reason": f"images.sh({arch}) 에 실패한 서비스가 없다"}
    hits = []
    for svc in failed:
        try:
            text = (root / "test-results" / f"images-{arch}" / f"{svc}.log").read_text(errors="replace")
        except OSError:
            return {"infra": False, "reason": f"{svc}({arch}) 의 굽기 로그가 없다"}
        code = CODE_FAILURE.search(text)
        if code:
            return {"infra": False, "reason": f"{svc}({arch}) 은 빌드가 실패했다: {code.group(0)}"}
        infra = INFRA_FAILURE.search(text)
        if not infra:
            return {"infra": False, "reason": f"{svc}({arch}) 의 실패를 가르지 못했다"}
        hits.append(f"{svc} {infra.group(0)}")
    return {"infra": True, "failed": len(failed), "reason": f"이미지 굽기({arch})의 인프라 실패: " + ", ".join(hits)}


def main(argv: list[str]) -> int:
    if len(argv) > 2 and argv[1] == "images":
        print(json.dumps(classify_images(argv[2]), ensure_ascii=False))
        return 0
    results = pathlib.Path(argv[1] if len(argv) > 1 else "test-results")
    print(json.dumps(classify(results), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
