#!/usr/bin/env python3
"""프런트·e2e 시험이 시간으로 기다리지 못하게 막는다(#808).

고정 대기(`waitForTimeout`·`setTimeout` 으로 기다리기·폴링)는 느린 머신에서는 모자라 시험을
흔들고 빠른 머신에서는 남아 시험을 느리게 한다. 기다릴 **사건**(응답·요소·주소·소켓 닫힘)을
이름 붙여 그 사건에서 풀리게 한다 — `docs/ops/frontend.md` 「고정 대기를 쓰지 않는다」.

이 저장소에는 JS 린터(eslint·oxlint)가 없다. 문서 검사(`check_screen_language.py` 등)와 같은
방식으로 파이썬 하나가 시험 파일을 훑는다. 커밋 훅과 PR CI(`scripts/ci/sub-checks-inside.sh`)가 부른다.

훑는 곳: 시험 파일(`*.test.ts(x)`·`*.spec.ts(x)`)과 `e2e/` 아래 지원 파일. 앱 코드의 정당한
`setTimeout`(디바운스·복사 안내 끄기)은 보지 않는다.

막는 것
- 어디서나: `waitForTimeout`·`waitForFunction`·`toPass`·`expect.poll`·`networkidle`,
  `setTimeout`·`setInterval`·`requestAnimationFrame` 호출(`test.setTimeout` 은 한도라서 아니다).
- e2e 에서만: `while (` 되풀이 루프.

바꿀 수 없는 것(시험의 대기가 아니라 고장 주입·부정 단언의 창·브라우저 안 흉내)은 그 줄 또는 바로
윗줄에 `TEST-WAIT-EXCEPTION: <이유>` 를 남긴다. 이유가 비어 있으면 실패한다.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCEPTION_RE = re.compile(r"TEST-WAIT-EXCEPTION:\s*(.*?)\s*(?:\*/)?\s*$")

ANYWHERE = [
    (re.compile(r"\bwaitForTimeout\b"), "waitForTimeout — 시간이 아니라 사건(응답·요소·주소)을 기다린다"),
    (re.compile(r"\bwaitForFunction\b"), "waitForFunction 은 폴링이다 — web-first 단언이나 waitForResponse 를 쓴다"),
    (re.compile(r"\btoPass\b"), "toPass 는 되풀이 폴링이다 — 기다릴 사건을 이름 붙인다"),
    (re.compile(r"\bexpect\.poll\b"), "expect.poll 은 폴링이다 — 기다릴 사건을 이름 붙인다"),
    (re.compile(r"waitForLoadState\(\s*['\"]networkidle"), "networkidle — 그 화면이 「그려졌다」를 뜻하는 요소를 기다린다"),
    (
        re.compile(r"(?<![\w.])(?:window\.|globalThis\.)?(?:setTimeout|setInterval|requestAnimationFrame)\s*\("),
        "시간 타이머로 기다리지 않는다 — 사건을 기다리거나 vi.useFakeTimers 로 시간을 앞당긴다",
    ),
]
E2E_ONLY = [
    (re.compile(r"\bwhile\s*\("), "e2e 는 되풀이 루프로 기다리지 않는다 — web-first 단언을 쓴다"),
]

STRING_RE = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")


def test_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", "*.ts", "*.tsx", "*.mts", "*.mjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    keep = []
    for path in out:
        if path.startswith("backend/") or "/node_modules/" in path or path.endswith(".gen.ts"):
            continue
        if is_e2e(path) or re.search(r"\.(test|spec)\.tsx?$", path):
            keep.append(path)
    return keep


def is_e2e(path: str) -> bool:
    return "/e2e/" in path or path.startswith("e2e/")


def code_part(line: str) -> str:
    """문자열 내용과 줄 끝 주석을 지운다 — 설명·인용에 든 낱말은 호출이 아니다."""
    line = STRING_RE.sub('""', line)
    line = re.sub(r"(?<!:)//.*$", "", line)
    return line


def exception_reason(lines: list[str], i: int) -> str | None:
    """i 줄 또는 바로 윗줄의 예외 표시 — 없으면 None, 이유 없으면 빈 문자열."""
    for j in (i, i - 1):
        if j < 0:
            continue
        m = EXCEPTION_RE.search(lines[j])
        if m and "TEST-WAIT-EXCEPTION" in lines[j]:
            return m.group(1)
    return None


def check_text(path: str, text: str) -> list[str]:
    problems: list[str] = []
    lines = text.splitlines()
    rules = ANYWHERE + (E2E_ONLY if is_e2e(path) else [])
    in_block_comment = False
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block_comment = True
            continue
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        code = code_part(raw)
        with_strings = re.sub(r"(?<!:)//.*$", "", raw)
        for pattern, why in rules:
            if not pattern.search(with_strings if "networkidle" in pattern.pattern else code):
                continue
            reason = exception_reason(lines, i)
            if reason is None:
                problems.append(f"{path}:{i + 1}: {why}")
            elif reason == "":
                problems.append(f"{path}:{i + 1}: TEST-WAIT-EXCEPTION 에 이유가 없다 — 왜 시간으로 기다려야 하는지 적는다")
            break
    return problems


def main() -> int:
    problems: list[str] = []
    files = test_files()
    for path in files:
        problems += check_text(path, (ROOT / path).read_text(encoding="utf-8"))
    if problems:
        print("고정 대기 검사 실패 (#808) — 사건을 기다리도록 바꾸거나, 정말 시험의 대기가 아니면")
        print("그 줄 윗줄에 `// TEST-WAIT-EXCEPTION: <이유>` 를 남긴다:")
        for p in problems:
            print("  " + p)
        return 1
    print(f"고정 대기 검사 통과 ({len(files)}개 시험 파일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
