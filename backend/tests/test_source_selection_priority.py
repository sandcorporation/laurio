"""#986: 선택기가 예산(300KB)을 앱 코드부터 채운다 — 앞 글자 폴더가 큰 트리에서도 앱 코드가 든다.

공모전 3에서 경로 이름 순으로 채우던 선택기가 `.scratch/`·`deploy/`·`docs/`(617),
`backend/.sqlx/`(866), 설정 파일(809)로 예산을 다 써 앱 코드가 0파일인 채로 0%가 나왔다.
아래 가짜 zip 은 그 세 저장소의 꼴이다(GitHub zip 처럼 맨 위에 `<저장소>-<sha>/` 폴더가 있다).
"""

from __future__ import annotations

import io
import zipfile

import pytest

from core import source_selection
from core.model_context import DEFAULT_CONTEXT_WINDOW_TOKENS, context_window_tokens, source_budget_bytes
from core.source_selection import (
    LOW_PRIORITY_TIER,
    MAX_SOURCE_BYTES,
    select_source_files,
    select_source_files_with_omission,
    selection_tier,
)


def _zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _filler(kb: int) -> str:
    return ("# 메모 " + "x" * 90 + "\n") * (kb * 10)


def _app_code(root: str) -> dict[str, str]:
    return {
        f"{root}/wbb-backend/app/main.py": "def login():\n    return 'ok'\n" * 50,
        f"{root}/wbb-backend/app/stream.py": "def start_stream():\n    pass\n" * 50,
        f"{root}/wbb-frontend/src/App.tsx": "export function App() { return null }\n" * 50,
        f"{root}/wbb-frontend/src/pages/Live.tsx": "export const Live = () => null\n" * 50,
    }


def _selected_paths(raw: bytes) -> set[str]:
    return {f.path for f in select_source_files([(1, "저장소", raw)])}


def test_app_code_fits_when_scratch_deploy_and_docs_come_first_alphabetically():
    """617 wbb-live 꼴 — `.scratch` 25·`deploy` 10·`docs` 7 이 앞 글자로 예산을 다 쓰던 트리."""

    root = "wbb-live-0123abc"
    files = {f"{root}/.scratch/note-{i:02}.md": _filler(20) for i in range(25)}
    files |= {f"{root}/deploy/step-{i:02}.yaml": _filler(15) for i in range(10)}
    files |= {f"{root}/docs/design-{i:02}.md": _filler(15) for i in range(7)}
    app = _app_code(root)
    files |= app
    assert sum(len(c) for c in files.values()) > 2 * MAX_SOURCE_BYTES

    assert set(app) <= _selected_paths(_zip(files))


def test_app_code_fits_when_generated_sqlx_queries_fill_the_backend_folder():
    """866 flutch 꼴 — `backend/.sqlx/` 120개가 `backend/src`·`frontend` 보다 앞서던 트리."""

    root = "flutch-9f8e7d"
    files = {f"{root}/backend/.sqlx/query-{i:03}.json": _filler(4) for i in range(120)}
    app = {
        f"{root}/backend/src/main.rs": "fn main() {}\n" * 100,
        f"{root}/backend/src/routes.rs": "pub fn routes() {}\n" * 100,
        f"{root}/frontend/src/App.tsx": "export const App = () => null\n" * 100,
    }
    files |= app

    assert set(app) <= _selected_paths(_zip(files))


def test_app_code_fits_when_config_files_come_first():
    """809 live-streaming-platform 꼴 — 설정 파일만 실려 앱 코드가 없던 트리."""

    root = "live-streaming-platform-55aa"
    files = {f"{root}/a-config/service-{i:02}.yaml": _filler(30) for i in range(13)}
    files[f"{root}/README.md"] = "# 라이브 스트리밍\n"
    app = {
        f"{root}/services/api/server.go": "package main\nfunc main() {}\n" * 100,
        f"{root}/web/src/player.ts": "export const play = () => {}\n" * 100,
    }
    files |= app

    selected = _selected_paths(_zip(files))
    assert set(app) <= selected
    assert f"{root}/README.md" in selected


def test_the_order_is_deterministic_and_app_code_comes_first():
    root = "r-1"
    files = {
        f"{root}/docs/a.md": "문서\n",
        f"{root}/.github/workflows/ci.yml": "on: push\n",
        f"{root}/package.json": "{}\n",
        f"{root}/tests/test_app.py": "def test_x(): pass\n",
        f"{root}/README.md": "# r\n",
        f"{root}/src/app.py": "print(1)\n",
    }
    raw = _zip(files)

    first = [f.path for f in select_source_files([(1, "저장소", raw)])]
    second = [f.path for f in select_source_files([(1, "저장소", raw)])]

    assert first == second
    assert first == [
        f"{root}/src/app.py",
        f"{root}/README.md",
        f"{root}/package.json",
        f"{root}/.github/workflows/ci.yml",
        f"{root}/docs/a.md",
        f"{root}/tests/test_app.py",
    ]


def test_selection_tier_puts_generated_scratch_and_ci_last():
    assert selection_tier("r/src/main.py") == 0
    assert selection_tier("r/tests/test_main.py") == LOW_PRIORITY_TIER
    assert selection_tier("r/web/src/App.test.tsx") == LOW_PRIORITY_TIER
    assert selection_tier("r/README.md") == 1
    assert selection_tier("r/Dockerfile") == 2
    assert selection_tier("r/backend/.sqlx/query-1.json") == LOW_PRIORITY_TIER
    assert selection_tier("r/backend/app/migrations/0001_initial.py") == LOW_PRIORITY_TIER
    assert selection_tier("r/.scratch/a.py") == LOW_PRIORITY_TIER


def test_what_did_not_fit_is_reported():
    root = "big"
    files = {f"{root}/src/mod_{i:03}.py": "x = 1\n" * 1900 for i in range(40)}  # 40 × 11.4KB — 예산 경계가 파일 중간에 온다
    files[f"{root}/docs/guide.md"] = "문서\n"

    selected, omission = select_source_files_with_omission([(1, "저장소", _zip(files))])

    assert omission.any
    assert omission.omitted_code_files > 0
    assert omission.omitted_files == 41 - len(selected)
    assert omission.truncated_files == 1
    assert omission.truncated_code_files == 1
    assert omission.app_code_cut
    assert omission.omitted_bytes > 0


def test_nothing_is_reported_when_everything_fits():
    _selected, omission = select_source_files_with_omission([(1, "저장소", _zip({"r/src/a.py": "x\n"}))])

    assert not omission.any


def test_what_did_not_fit_outside_app_code_does_not_count_as_app_code_cut():
    files = {"r/src/a.py": "x = 1\n"} | {f"r/docs/d-{i}.md": "문서\n" * 3000 for i in range(5)}

    _selected, omission = select_source_files_with_omission([(1, "저장소", _zip(files))], max_bytes=20_000)

    assert omission.any
    assert not omission.app_code_cut


def test_low_priority_files_can_be_excluded_outright(monkeypatch):
    """대장 결정 대기(#986) — 맨 뒤 차례를 아예 빼는 선택지가 스위치 하나다."""

    monkeypatch.setattr(source_selection, "EXCLUDE_LOW_PRIORITY", True)
    files = {"r/src/a.py": "x\n", "r/tests/test_a.py": "x\n", "r/docs/a.md": "x\n", "r/README.md": "x\n"}

    assert _selected_paths(_zip(files)) == {"r/src/a.py", "r/README.md"}


@pytest.mark.parametrize(
    ("model", "window"),
    [("gpt-4o-mini", 128_000), ("gpt-4.1", 1_047_576), ("claude-haiku-5-5", 1_000_000), ("모르는-모델", 128_000)],
)
def test_the_source_budget_follows_the_model_context(model, window):
    assert context_window_tokens(model) == window
    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 128_000
    budget = source_budget_bytes(model, instruction_bytes=10_000)
    assert source_budget_bytes(model, instruction_bytes=0) - budget == 10_000
    # 응답 몫을 남기고도 컨텍스트 안에 든다(바이트/토큰 3 기준).
    assert budget // 3 < window


def test_the_default_model_budget_is_close_to_the_old_fixed_budget():
    """gpt-4o-mini 기준 예산은 옛 300KB 와 크게 다르지 않다 — 보류 기준이 갑자기 느슨해지거나 조이지 않는다."""

    assert 250_000 < source_budget_bytes("gpt-4o-mini", instruction_bytes=8_000) < 360_000
