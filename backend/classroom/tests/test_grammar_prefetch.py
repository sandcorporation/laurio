"""문법 받기(#1205) — 언어 목록이 어긋나지 않고, 받기가 끊기면 다시 시도하고, 이미지 층이 소스 복사 앞에 있다."""

import ast
from pathlib import Path

import pytest

from classroom import grammar_prefetch
from classroom.syntax_check import TREE_SITTER_LANGUAGE_BY_EXTENSION

REPO = Path(__file__).resolve().parents[3]


def test_받을_문법은_문법_검사가_쓰는_언어와_같다():
    assert set(grammar_prefetch.TREE_SITTER_LANGUAGES) == set(TREE_SITTER_LANGUAGE_BY_EXTENSION.values())
    assert list(grammar_prefetch.TREE_SITTER_LANGUAGES) == sorted(grammar_prefetch.TREE_SITTER_LANGUAGES)


def test_받기가_끊기면_간격을_늘려_다시_시도한다():
    calls: list[str] = []
    waits: list[float] = []

    def flaky(language: str) -> None:
        calls.append(language)
        if len(calls) < 3:
            raise RuntimeError("timeout")

    grammar_prefetch._fetch_with_retry("go", flaky, attempts=3, backoff=2.0, sleep=waits.append)
    assert calls == ["go", "go", "go"]
    assert waits == [2.0, 4.0]


def test_세_번_다_끊기면_마지막_오류를_던진다():
    def broken(language: str) -> None:
        raise RuntimeError("timeout")

    waits: list[float] = []
    with pytest.raises(RuntimeError, match="timeout"):
        grammar_prefetch._fetch_with_retry("go", broken, attempts=3, backoff=1.0, sleep=waits.append)
    assert len(waits) == 2


def test_받기_파일은_장고와_다른_앱을_가져오지_않는다():
    # 이미지 층이 이 파일 하나만 복사해 돌린다 — 다른 가져오기가 생기면 층에서 깨진다.
    tree = ast.parse(Path(grammar_prefetch.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= {"__future__", "sys", "time", "collections", "tree_sitter_language_pack"}


def test_이미지는_문법을_backend_소스_복사_앞_층에서_받는다():
    lines = (REPO / "docker" / "backend.Dockerfile").read_text(encoding="utf-8").splitlines()
    run_prefetch = next(i for i, line in enumerate(lines) if "grammar_prefetch.py" in line and line.startswith("RUN"))
    copy_source = next(i for i, line in enumerate(lines) if line.strip() == "COPY backend/ ./")
    assert run_prefetch < copy_source
