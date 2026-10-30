"""방문 메트릭 스니펫(Sandcorp 공통, #785)은 사용자가 보는 두 앱(`frontend/`·`classroom/`)에만 있고, 운영자 앱에는 없다.

태그는 `<script defer src=… data-site="codemit">` 한 줄이고, `src` 는 실행 때 env `CODEMIT_PUBLIC_METRICS_SNIPPET_URL`
에서 온다(ADR-0062 — 빌드에 굳히지 않는다, `test_next_public_env_stays_out.py`). 비어 있으면 태그를 그리지 않으므로
로컬·시험·CI 에는 태그가 없다. 배선은 compose prod 의 frontend·classroom 서비스에만 있다 —
operator 에 누가 같은 줄을 더하면 여기서 걸린다.

시험 파일(`*.test.*`·`*.spec.*`)은 보지 않는다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from django.conf import settings

REPO_ROOT = settings.BASE_DIR.parent
SKIP_DIRS = {"node_modules", ".next", "dist", "build", "coverage", "test-results", "playwright-report"}
SOURCE = re.compile(r"\.(ts|tsx|js|jsx|mjs|cjs)$")
TEST_FILE = re.compile(r"\.(test|spec)\.[a-z]+$")
SNIPPET_MARKS = ("data-site=", "metricsSnippetSrc", "METRICS_SNIPPET_URL")
ENV_NAME = "CODEMIT_PUBLIC_METRICS_SNIPPET_URL"
PUBLIC_APPS = ("frontend", "classroom")


def _sources(root: str) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT / root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if SOURCE.search(name) and not TEST_FILE.search(name):
                found.append(Path(dirpath) / name)
    return found


def _marks_in(root: str) -> list[str]:
    return [
        f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()}"
        for path in _sources(root)
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(mark in line for mark in SNIPPET_MARKS)
    ]


def test_operator_app_has_no_metrics_snippet():
    hits = _marks_in("operator")
    assert not hits, "운영자 앱에는 방문 메트릭 스니펫을 넣지 않는다(#785):\n" + "\n".join(hits)


def test_the_two_public_apps_render_the_snippet_from_runtime_env():
    # 운영자 쪽 검사가 무뎌지지 않았는지 — 같은 표지가 공개 앱 둘의 루트 레이아웃에는 있어야 한다.
    for app in PUBLIC_APPS:
        layout = (REPO_ROOT / app / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert 'data-site="codemit"' in layout, app
        assert "metricsSnippetSrc(process.env)" in layout, app
        config = (REPO_ROOT / app / "lib" / "public-config.ts").read_text(encoding="utf-8")
        assert ENV_NAME in config, app
    assert _marks_in("frontend") and _marks_in("classroom")


def _app_env(compose: str, service: str) -> dict:
    with open(REPO_ROOT / "docker" / compose, encoding="utf-8") as f:
        return yaml.safe_load(f)["services"][service].get("environment") or {}


def test_compose_wires_the_env_to_the_two_public_apps_only():
    for compose in ("compose.prod.yaml",):
        for app in PUBLIC_APPS:
            assert _app_env(compose, app).get(ENV_NAME) == "${METRICS_SNIPPET_URL:-}", (compose, app)
        assert ENV_NAME not in _app_env(compose, "operator"), compose
        assert ENV_NAME not in (REPO_ROOT / "docker" / "compose.dev.yaml").read_text(encoding="utf-8")
    for example in ("prod.env.example",):
        text = (REPO_ROOT / "docker" / example).read_text(encoding="utf-8")
        assert re.search(r"^METRICS_SNIPPET_URL=$", text, re.M), example
