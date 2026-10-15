"""세 Next 앱(과 `packages/`)이 `next/font/google` 을 다시 들이지 못한다 (#743).

`next/font/google` 은 **빌드 때** fonts.gstatic.com 에서 woff2 를 받는다. 그래서 이미지 굽기가 빌더의
외부 네트워크에 매달렸고, 그 연결이 한 번 끊기자 `pnpm build` 가 죽어 열차가 붉었다(#1945) — 코드는
멀쩡한데 빌드 안의 실패라 코드 탓으로 셌다(#729). 서체는 이제 전부 `<앱>/app/fonts/` 의 파일을
`next/font/local` 로 읽고, 빌드는 외부 네트워크를 쓰지 않는다(docs/ops/next-build.md). 누가 Google
서체 하나를 한 줄로 더하면 타입 검사도 e2e 도 조용히 지나가므로 기계가 매 커밋 본다.

시험 파일과 주석 줄은 보지 않는다 — 금지를 설명하는 문장은 남아야 한다.
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
GOOGLE_FONT = re.compile(r"[\"'`](@next/font/google|next/font/google)[\"'`]")
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


def test_no_app_fetches_a_font_at_build_time():
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()}"
        for path in _sources()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if GOOGLE_FONT.search(line) and not COMMENT_LINE.match(line)
    ]
    assert not hits, (
        "서체는 `<앱>/app/fonts/` 에 woff2 로 담고 `next/font/local` 로 읽는다 — 빌드가 외부 네트워크를 "
        "쓰면 안 된다(docs/ops/next-build.md):\n" + "\n".join(hits)
    )


def test_the_scan_sees_the_layouts_and_catches_the_pattern():
    # 걷는 길이 비거나 정규식이 무뎌지면 위 시험은 늘 통과한다.
    names = {p.relative_to(REPO_ROOT).as_posix() for p in _sources()}
    assert {f"{app}/app/layout.tsx" for app in ("frontend", "operator", "classroom")} <= names
    assert GOOGLE_FONT.search('import { IBM_Plex_Mono } from "next/font/google";')
    assert GOOGLE_FONT.search("import { Inter } from '@next/font/google';")
    assert not GOOGLE_FONT.search('import localFont from "next/font/local";')
