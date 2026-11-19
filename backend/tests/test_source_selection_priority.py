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
        f"{root}/src/migrations/0001_initial.py": "x = 1\n",
        f"{root}/docker-compose.yml": "services: {}\n",
    }
    raw = _zip(files)

    first = [f.path for f in select_source_files([(1, "저장소", raw)])]
    second = [f.path for f in select_source_files([(1, "저장소", raw)])]

    assert first == second
    assert first == [
        f"{root}/src/app.py",
        f"{root}/README.md",
        f"{root}/docker-compose.yml",
        f"{root}/package.json",
        f"{root}/src/migrations/0001_initial.py",
    ]


def test_selection_tier_puts_app_code_then_readme_then_the_rest():
    assert selection_tier("r/src/main.py") == 0
    assert selection_tier("r/README.md") == 1
    assert selection_tier("r/Dockerfile") == 2
    assert selection_tier("r/mediamtx.yml") == 2
    assert selection_tier("r/backend/app/migrations/0001_initial.py") == 2
    assert selection_tier("r/deploy/run.sh") == 2
    assert selection_tier("r/.husky/pre-commit.sh") == 2


# 「코드 아님」 제외 규칙 표(#986 보탬 4) — 한 줄마다 하나씩. 경로는 GitHub zip 처럼 `<저장소>-<sha>/` 아래다.
@pytest.mark.parametrize(
    ("path", "kind"),
    [
        # docs
        ("r-1/docs/guide.py", "docs"),
        ("r-1/backend/docs/api.yaml", "docs"),
        ("r-1/CLAUDE.md", "docs"),
        ("r-1/backend/README.md", "docs"),
        ("r-1/notes.mdx", "docs"),
        ("r-1/index.rst", "docs"),
        # scratch·도구
        ("r-1/.scratch/a.py", "scratch"),
        ("r-1/experiments/try.py", "scratch"),
        ("r-1/scratch/b.ts", "scratch"),
        ("r-1/.claude/settings.yml", "scratch"),
        ("r-1/.agents/x.yml", "scratch"),
        ("r-1/.cursor/rules.yml", "scratch"),
        ("r-1/.github/workflows/ci.yml", "scratch"),
        ("r-1/.vscode/launch.yml", "scratch"),
        ("r-1/.idea/misc.xml", "vendor"),  # 벤더·빌드 폴더 목록에도 있어 그쪽이 먼저 걸린다
        # 생성물
        ("r-1/backend/.sqlx/query-1.json", "generated"),
        ("r-1/web/__snapshots__/a.snap", "generated"),
        ("r-1/web/logo.svg", "generated"),
        ("r-1/data/seed.csv", "generated"),
        ("r-1/Cargo.lock", "vendor"),  # 잠금 파일 이름 목록이 먼저 잡는다
        ("r-1/flake.lock", "generated"),
        ("r-1/web/app.min.js", "vendor"),
        ("r-1/web/src/generated/client.ts", "generated"),
        ("r-1/web/src/schema.d.ts", "generated"),
        # 시험
        ("r-1/test/a.py", "tests"),
        ("r-1/tests/test_a.py", "tests"),
        ("r-1/web/__tests__/App.tsx", "tests"),
        ("r-1/web/e2e/login.ts", "tests"),
        ("r-1/spec/user_spec.rb", "tests"),
        ("r-1/web/src/App.test.tsx", "tests"),
        ("r-1/web/src/App.spec.ts", "tests"),
        ("r-1/server/main_test.go", "tests"),
        ("r-1/app/views_test.py", "tests"),
        ("r-1/app/test_views.py", "tests"),
        # 데이터 json
        ("r-1/data/items.json", "data_json"),
        ("r-1/web/public/manifest.json", "data_json"),
    ],
)
def test_not_code_is_excluded(path, kind):
    assert source_selection.excluded_kind(path) == kind
    assert source_selection.is_excluded_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "r-1/README.md",  # 루트 README 는 남긴다(깊이 ≤1)
        "README.md",
        "r-1/mediamtx.yml",  # 녹화·훅 설정이 송출·녹화 요구사항의 근거다
        "r-1/docker-compose.yaml",
        "r-1/compose.yml",
        "r-1/Dockerfile",
        "r-1/pyproject.toml",
        "r-1/nginx/nginx.conf",
        "r-1/db/schema.sql",
        "r-1/backend/app/migrations/0001_initial.py",
        "r-1/backend/migrations/20260101_init.sql",
        "r-1/package.json",
        "r-1/web/tsconfig.json",
        "r-1/composer.json",
        "r-1/configs/R1.txt",  # Packet Tracer 장비 설정(ADR-0031)
        "r-1/src/latest.py",  # 「test」가 이름 중간에 있어도 시험이 아니다
        "r-1/src/contest/views.py",
    ],
)
def test_evidence_is_kept(path):
    assert source_selection.excluded_kind(path) is None


def test_mediamtx_and_migrations_reach_the_prompt():
    root = "live-1"
    files = {
        f"{root}/mediamtx.yml": "paths:\n  all:\n    record: yes\n",
        f"{root}/backend/app/migrations/0001_initial.py": "class Migration: pass\n",
        f"{root}/src/app.py": "print(1)\n",
        f"{root}/docs/a.md": "문서\n",
        f"{root}/tests/test_app.py": "def test_x(): pass\n",
    }

    assert _selected_paths(_zip(files)) == {
        f"{root}/mediamtx.yml",
        f"{root}/backend/app/migrations/0001_initial.py",
        f"{root}/src/app.py",
    }


def test_what_did_not_fit_is_reported():
    root = "big"
    files = {f"{root}/src/mod_{i:03}.py": "x = 1\n" * 1900 for i in range(40)}  # 40 × 11.4KB — 예산 경계가 파일 중간에 온다
    files[f"{root}/config/app.yml"] = "a: 1\n"

    selected, omission = select_source_files_with_omission([(1, "저장소", _zip(files))])

    assert omission.any
    assert omission.omitted_code_files > 0
    assert omission.omitted_files == 41 - len(selected)
    assert omission.truncated_files == 1
    assert omission.truncated_code_files == 1
    assert omission.omitted_bytes > 0


def test_nothing_is_reported_when_everything_fits():
    _selected, omission = select_source_files_with_omission([(1, "저장소", _zip({"r/src/a.py": "x\n"}))])

    assert not omission.any


def test_config_that_did_not_fit_is_an_omission_too():
    """보류 기준은 「무엇이든 빠졌는가」다(보탬 4) — 규칙 뒤 남은 설정도 구현 근거다."""

    files = {"r/src/a.py": "x = 1\n"} | {f"r/config/c-{i}.yml": "a: 1\n" * 3000 for i in range(5)}

    _selected, omission = select_source_files_with_omission([(1, "저장소", _zip(files))], max_bytes=20_000)

    assert omission.any
    assert omission.omitted_code_files == 0


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
