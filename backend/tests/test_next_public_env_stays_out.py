"""세 Next 앱(과 그 앱들이 묶는 `packages/`)에 `process.env.NEXT_PUBLIC_*` 가 다시 들어오지 못한다 (#711·#727, ADR-0062).

`NEXT_PUBLIC_*` 는 **빌드 때** 브라우저 번들에 굳는다. 그래서 예전에는 같은 코드를 staging·prod 로 두 번
구웠고, #711 이 공개 값을 실행 때 읽는 `CODEMIT_PUBLIC_*` 로 옮겼다 — 브라우저에는 `<앱>/lib/public-config.ts`
의 허용 목록만 레이아웃이 `window.__CODEMIT_PUBLIC__` 로 넘긴다. 그 뒤로 누가 `process.env.NEXT_PUBLIC_X` 를
한 줄 쓰면 이미지가 다시 환경을 알게 되는데(빌드에 그 값이 없으면 빈 값으로 굳는다), 타입 검사도 e2e 도
조용히 지나간다 — 그래서 기계가 매 커밋 본다. 앱 경계 시험(`test_app_boundaries.py`)처럼 쓰는 순간 막는다.

시험 파일(`*.test.*`·`*.spec.*`)과 주석 줄은 보지 않는다 — 금지를 설명하는 문장은 남아야 한다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
ROOTS = ("frontend", "operator", "classroom", "packages")
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "coverage", "test-results", "playwright-report"}
SOURCE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs)$")
TEST_FILE = re.compile(r"\.(test|spec)\.[a-z]+$")
BUILD_TIME_ENV = re.compile(r"process\.env(\.|\[\s*[\"'`])NEXT_PUBLIC_")
COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*)")


def _sources() -> list[Path]:
    found: list[Path] = []
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT / root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            found.extend(
                Path(dirpath) / f for f in filenames if SOURCE.search(f) and not TEST_FILE.search(f)
            )
    return found


def test_no_app_reads_a_build_time_public_env():
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()}"
        for path in _sources()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if BUILD_TIME_ENV.search(line) and not COMMENT_LINE.match(line)
    ]
    assert not hits, (
        "공개 값은 `CODEMIT_PUBLIC_*` 로 실행 때 읽는다 — `<앱>/lib/public-config.ts` 의 목록에 더하고 "
        "`publicConfig()` 로 읽는다(docs/ops/frontend.md):\n" + "\n".join(hits)
    )


def test_the_scan_sees_the_apps_and_catches_the_pattern():
    # 걷는 길이 비거나 정규식이 무뎌지면 위 시험은 늘 통과한다.
    names = {p.relative_to(REPO_ROOT).as_posix() for p in _sources()}
    assert {f"{app}/lib/public-config.ts" for app in ("frontend", "operator", "classroom")} <= names
    assert BUILD_TIME_ENV.search('const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;')
    assert BUILD_TIME_ENV.search('process.env["NEXT_PUBLIC_X"]')
    assert not BUILD_TIME_ENV.search("process.env.CODEMIT_PUBLIC_SENTRY_DSN")
