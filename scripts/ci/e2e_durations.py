#!/usr/bin/env python3
"""e2e 시험 파일마다의 시간 기록(#1112) — 조각을 시험 수가 아니라 시간으로 나누는 데 쓴다(e2e_plan.py).

    e2e_durations.py update --out OUT [--from PREV] REPORT.json...   Playwright JSON 리포트로 기록을 다시 쓴다

기록은 `{frontend 기준 시험 파일: 초}` JSON 이다(pytest-durations.json 과 같은 꼴, #1083). 어디서 읽는가:
- 매시 main 전체 e2e(e2e.yml)의 `durations` 잡이 조각마다의 JSON 리포트(e2e.sh 가 `test-results/timings/` 에 남긴다)를
  합쳐 Actions 캐시 `e2e-durations-<실행>` 으로 저장한다. PR 검사·e2e.yml 의 계획 잡은 가장 새 것을 복원해
  `--durations` 로 넘긴다 — 커밋하지 않으니 쓰기 권한이 늘지 않는다.
- 캐시가 없으면(첫 실행·7일 넘게 안 쓴 캐시가 지워졌을 때) 저장소의 씨앗 기록 `scripts/ci/e2e-durations.json` 을 쓴다.
  씨앗은 사람이 가끔 다시 쓴다 — durations 잡이 올린 산출물 `e2e-durations` 를 받아 그대로 커밋한다.

갱신 규칙: 이번 리포트에서 시험이 모두 통과(또는 건너뜀)한 파일만 새 값을 받는다 — 직전 기록과의 평균(한 번의
흔들림에 조각이 크게 뒤바뀌지 않게). 실패가 있거나 리포트에 없는(조각이 죽은) 파일은 직전 값을 그대로 둔다.
지금 저장소에 없는 파일은 지운다. 기록에 없는 파일(새 시험)은 계획이 기록의 평균값으로 센다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SEED = Path(__file__).resolve().parent / "e2e-durations.json"
#: 통과로 치는 결과 — 건너뛴 시험(live 표식 등)은 0초로 센다
OK_STATUSES = frozenset({"passed", "skipped"})


class _Result(TypedDict, total=False):
    duration: float  # 밀리초
    status: str


class _Test(TypedDict, total=False):
    results: list[_Result]


class _Spec(TypedDict, total=False):
    file: str
    tests: list[_Test]


class _Suite(TypedDict, total=False):
    file: str
    specs: list[_Spec]
    suites: list[_Suite]


def spec_files(frontend: Path = FRONTEND) -> set[str]:
    """frontend 기준 시험 파일 전부(e2e_plan.folders 와 같은 것)."""

    return {p.relative_to(frontend).as_posix() for p in (frontend / "e2e").rglob("*.spec.ts")}


def read_record(path: Path | None = None) -> dict[str, float]:
    """기록을 읽는다. 경로가 없거나 파일이 없으면 씨앗 기록."""

    target = path if path is not None and path.exists() else SEED
    if not target.exists():
        return {}
    data: dict[str, float] = json.loads(target.read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in data.items()}


def _walk(suite: _Suite, out: dict[str, tuple[float, bool]]) -> None:
    for spec in suite.get("specs", []):
        f = spec.get("file") or suite.get("file", "")
        seconds, ok = out.get(f, (0.0, True))
        for test in spec.get("tests", []):
            # 결과가 없는 시험(실행이 중간에 끊겼거나 --list)은 잰 것이 아니다
            ok = ok and bool(test.get("results"))
            for result in test.get("results", []):
                seconds += float(result.get("duration", 0)) / 1000
                ok = ok and result.get("status") in OK_STATUSES
        out[f] = (seconds, ok)
    for child in suite.get("suites", []):
        _walk(child, out)


def measured(reports: Iterable[Path]) -> dict[str, float]:
    """리포트들에서 파일별 시간 합(초) — 시험이 모두 통과·건너뜀인 파일만. 같은 파일이 두 패스에 나뉘면 합친다."""

    acc: dict[str, tuple[float, bool]] = {}
    for path in reports:
        data = json.loads(path.read_text(encoding="utf-8"))
        for suite in data.get("suites", []):
            _walk(suite, acc)
    return {f: s for f, (s, ok) in acc.items() if ok}


def merge(previous: Mapping[str, float], fresh: Mapping[str, float], present: set[str]) -> dict[str, float]:
    """새 기록 — 이번에 잰 파일은 직전 값과의 평균(직전 값이 없으면 잰 값), 못 잰 파일은 직전 값, 없는 파일은 뺀다."""

    out: dict[str, float] = {}
    for f in sorted(present):
        if f in fresh:
            out[f] = round((previous[f] + fresh[f]) / 2 if f in previous else fresh[f], 2)
        elif f in previous:
            out[f] = previous[f]
    return out


def dump(record: Mapping[str, float]) -> str:
    return json.dumps(dict(sorted(record.items())), ensure_ascii=False, indent=0) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("update", help="Playwright JSON 리포트로 기록을 다시 쓴다")
    up.add_argument("--out", type=Path, required=True)
    up.add_argument("--from", dest="prev", type=Path, help="직전 기록(없으면 씨앗)")
    up.add_argument("reports", nargs="*", type=Path)
    args = parser.parse_args(argv)
    fresh = measured(args.reports)
    previous = read_record(args.prev)
    record = merge(previous, fresh, spec_files())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dump(record), encoding="utf-8")
    print(f"리포트 {len(args.reports)}개 · 잰 파일 {len(fresh)}개 · 기록 {len(record)}개, 합 {sum(record.values()):.0f}초 → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
