"""`core` 가 운영 설정을 등록 자리로 부르고, 공유층 안에 최상단 import 순환이 없다(#1086, spec #1079).

`core ↔ policies`·`core → submissions`·`storage → submissions` 가 공유층 넷을 한 순환으로 묶고 있었다. 등록 자리
(`core.runtime_settings_port`)와 옮기기로 풀었고, 다시 묶이면 여기서 빨갛다.
"""

from __future__ import annotations

import ast
from decimal import Decimal

import pytest

from core import runtime_settings_port as port
from policies import runtime_settings
from tests.test_app_boundaries import SHARED


def test_policies_registers_the_runtime_settings_module():
    assert port.RUNTIME_SETTINGS.get() is runtime_settings


def test_core_reads_whatever_policies_runtime_settings_answers_now(monkeypatch: pytest.MonkeyPatch):
    # 부를 때마다 모듈 속성을 읽는다 — `policies.runtime_settings` 를 바꿔 끼운 시험이 core 에도 듣는다.
    monkeypatch.setattr(runtime_settings, "setting_value", lambda key: f"값:{key}")
    monkeypatch.setattr(runtime_settings, "scoring_vendor", lambda: port.VENDOR_ANTHROPIC)
    monkeypatch.setattr(runtime_settings, "agent_scoring_daily_limit_usd", lambda: Decimal("3"))
    monkeypatch.setattr(runtime_settings, "repository_download_limit_bytes", lambda: 7)

    assert port.setting_value("LLM_OPENAI_MODEL") == "값:LLM_OPENAI_MODEL"
    assert port.scoring_vendor() == "anthropic"
    assert port.agent_scoring_daily_limit_usd() == Decimal("3")
    assert port.repository_download_limit_bytes() == 7


def test_vendor_values_have_one_source():
    assert runtime_settings.VENDOR_OPENAI is port.VENDOR_OPENAI
    assert runtime_settings.VENDOR_ANTHROPIC is port.VENDOR_ANTHROPIC


def _top_level_app_imports(tree: ast.Module) -> set[str]:
    """모듈 최상단(try·if 안 포함, `TYPE_CHECKING` 아래 제외)의 절대 import 가 가리키는 첫 이름."""

    found: set[str] = set()

    def walk(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
            elif isinstance(node, ast.If) and "TYPE_CHECKING" not in ast.unparse(node.test):
                walk(node.body)
                walk(node.orelse)
            elif isinstance(node, ast.Try):
                walk(node.body)

    walk(tree.body)
    return found


def test_the_shared_layer_has_no_top_level_import_cycle(backend_sources):
    deps: dict[str, set[str]] = {app: set() for app in SHARED}
    for source in backend_sources:
        parts = source.relative.parts
        if len(parts) < 2 or parts[0] not in SHARED or "tests" in parts or "migrations" in parts:
            continue
        deps[parts[0]] |= (_top_level_app_imports(source.tree) & SHARED) - {parts[0]}

    def reaches(start: str, goal: str) -> bool:
        seen, todo = set(), list(deps[start])
        while todo:
            app = todo.pop()
            if app == goal:
                return True
            if app not in seen:
                seen.add(app)
                todo.extend(deps[app])
        return False

    cycles = sorted(f"{a} ↔ {b}" for a in deps for b in deps[a] if reaches(b, a))
    assert cycles == [], f"공유층 최상단 import 순환: {cycles} — 등록 자리(core.registry)나 옮기기로 푼다"
