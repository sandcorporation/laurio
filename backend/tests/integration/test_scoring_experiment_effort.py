"""채점 방식 실험의 줄별 추론 강도(#1350) — `방식:모델@강도`.

실제 벤더를 부르지 않는다: `requests.post` 를 몽키패치해 Anthropic Messages API 의 응답 모양을 돌려주고, 나간 요청 본문의
`output_config.effort` 와 요청 한도를 본다(`core/tests/test_anthropic_scoring_adapter.py` 와 같은 자리).
"""

from __future__ import annotations

import io
import json
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import requests
from django.core.management import call_command

from core import experiment_material as em
from core.agent_run_tokens import Usage, usage_cost_usd
from core.clock import Clock
from core.llm_scoring import RequirementInput, ScoringInput
from core.llm_scoring_anthropic import SCORING_MAX_TOKENS
from policies.runtime_settings import AGENT_EXPERIMENT_DAILY_LIMIT_USD
from scoring import experiment as ex
from scoring.models import ScoringExperimentRun
from scoring.services import CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS
from tests.classroom_scenarios import zip_bytes

HAIKU = "claude-haiku-5-5"
REQ, OPT = 11, 12


class _Response:
    status_code = 200

    def __init__(self, body: dict[str, object]) -> None:
        self._body = body

    def json(self) -> dict[str, object]:
        return self._body


def _messages(verdicts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "msg_01", "type": "message", "role": "assistant", "model": HAIKU,
        "content": [{"type": "text", "text": json.dumps({"verdicts": verdicts}, ensure_ascii=False)}],
        "stop_reason": "end_turn", "usage": {"input_tokens": 1200, "output_tokens": 340},
    }


@pytest.fixture
def vendor(monkeypatch) -> list[dict[str, object]]:
    """가짜 Anthropic — 요청마다 (본문, 한도)를 남기고 받은 요구사항을 모두 충족으로 판정한다."""

    calls: list[dict[str, object]] = []

    def post(url: str, **kwargs: object) -> _Response:
        calls.append(kwargs)
        return _Response(_messages([{"requirement_id": rid, "is_met": True, "reasoning": "있다."} for rid in (REQ, OPT)]))

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-experiment-key")
    monkeypatch.setenv(AGENT_EXPERIMENT_DAILY_LIMIT_USD, "5")
    return calls


def _efforts(calls: list[dict[str, object]]) -> list[tuple[str | None, object]]:
    out = []
    for call in calls:
        body = call["json"]
        assert isinstance(body, dict)
        out.append((body["output_config"].get("effort"), call["timeout"]))
    return out


# ── 줄 문법 ──────────────────────────────────────────────────────────────────────────────────────────────


def test_suffix_picks_the_effort_and_a_bare_row_keeps_its_old_name():
    bare, medium, high = ex.parse_rows(
        f"classroom_call:{HAIKU},classroom_call:{HAIKU}@medium,single_call:{HAIKU}@high", material=True
    )

    assert (bare.effort, bare.name) == (None, f"classroom_call:{HAIKU}")  # 어제 기록과 이름이 겹친다
    assert (medium.effort, medium.name) == ("medium", f"classroom_call:{HAIKU}@medium")
    assert (high.method, high.model, high.vendor, high.effort) == ("single_call", HAIKU, "anthropic", "high")


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (f"single_call:{HAIKU}@max", "추론 강도는 low, medium, high 중 하나다"),
        (f"single_call:{HAIKU}@", "추론 강도는 low, medium, high 중 하나다"),
        ("single_call:gpt-4.1-mini@high", "Anthropic(claude-) 줄에만 붙는다"),
        ("classroom_call:gpt-5-mini@medium", "Anthropic(claude-) 줄에만 붙는다"),
        (f"agent:{HAIKU}@high", "Anthropic(claude-) 줄에만 붙는다"),
        (f"self_loop:{HAIKU}@low", "Anthropic(claude-) 줄에만 붙는다"),
        (f"classroom_staged:{HAIKU}@high", "Anthropic(claude-) 줄에만 붙는다"),
    ],
)
def test_a_bad_or_misplaced_suffix_is_refused_with_its_reason(row, reason):
    with pytest.raises(ex.ExperimentError, match=re.escape(reason)) as caught:
        ex.parse_rows(row, material=True)
    assert row in str(caught.value) and "\n" not in str(caught.value)


# ── 비용 어림 ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["single_call", "classroom_call"])
def test_raised_effort_budgets_up_to_the_output_ceiling(method):
    bare, low, medium, high = ex.parse_rows(
        f"{method}:{HAIKU},{method}:{HAIKU}@low,{method}:{HAIKU}@medium,{method}:{HAIKU}@high", material=True
    )
    hi_in = ex._TOKEN_ESTIMATE[method][1][0]
    ceiling = usage_cost_usd("anthropic", HAIKU, Usage(input_tokens=hi_in, output_tokens=SCORING_MAX_TOKENS))

    assert ex.per_cell_max(low) == ex.per_cell_max(bare) < ex.per_cell_max(medium)
    assert ex.per_cell_max(medium) == ex.per_cell_max(high) == ceiling.quantize(Decimal("0.0001"))
    assert ex.cost_range(high)[0] == ex.cost_range(bare)[0]  # 낮은 쪽은 그대로
    assert ex.cost_range(high, [Decimal("0.5")]) == (Decimal("0.5"), Decimal("0.5"))  # 실측이 있으면 실측


# ── 어댑터까지 ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("row", "effort", "timeout"),
    [
        (f"single_call:{HAIKU}", "low", CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS),
        (f"single_call:{HAIKU}@low", "low", CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS),
        (f"single_call:{HAIKU}@medium", "medium", ex.EFFORT_VENDOR_TIMEOUT_SECONDS),
        (f"single_call:{HAIKU}@high", "high", ex.EFFORT_VENDOR_TIMEOUT_SECONDS),
    ],
)
def test_single_call_sends_the_row_effort_and_its_timeout(vendor, row, effort, timeout):
    [parsed] = ex.parse_rows(row)
    with ex.real_vendor():
        adapter = ex._single_call_adapter(parsed)
    adapter.score(
        ScoringInput(
            submission_id=1, contest_id=1, prompt="채점", source_files=[],
            requirements=[RequirementInput(requirement_id=REQ, text="README", grade="required", self_reported_met=False)],
        )
    )

    assert _efforts(vendor) == [(effort, timeout)]


def _item(n: int, *, met: bool) -> em.Item:
    return em.Item(
        material_id=em.pseudonym("t1350", n),
        asset_kind="source",
        source=zip_bytes({"main.py": "def add_two_numbers(a, b):\n    return a + b\n"}),
        problem=em.ProblemText(
            title="두 수 더하기", description="두 수를 더하는 함수를 만든다.", grading_strictness="normal",
            grading_guideline_text="", syntax_check_enabled=False, reasoning_effort="low", marked_reasoning=False,
        ),
        checklist=(
            em.ChecklistEntry(REQ, "add_two_numbers", "required", False, 1),
            em.ChecklistEntry(OPT, "곱하기 함수", "optional", True, 1),
        ),
        verdicts=(em.ProductionVerdict(REQ, met, "지어낸 근거"), em.ProductionVerdict(OPT, False, "지어낸 근거")),
        model_version=HAIKU,
    )


@pytest.fixture
def material(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(em, "TEMP_ROOTS", ())
    monkeypatch.setattr(em, "DEFAULT_ROOT", tmp_path / "experiment-material")
    folder = tmp_path / "experiment-material" / "t1350"
    folder.mkdir(parents=True)
    path = folder / "t1350.tar.gz"
    em.write(path, name="t1350", exported_at=Clock.now() - timedelta(days=0), items=[_item(1, met=True), _item(2, met=False)])
    return path


def _call(*args: str) -> str:
    out = io.StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_classroom_call_rows_of_different_effort_run_side_by_side_and_report_apart(vendor, material):
    bare, high = f"classroom_call:{HAIKU}", f"classroom_call:{HAIKU}@high"

    preview = _call("compare_scoring_methods", "--material", str(material), "--rows", f"{bare},{high}", "--repeat", "1")
    assert f"\n{bare} | 2 | 0 |" in preview and f"\n{high} | 2 | 0 |" in preview

    out = _call(
        "compare_scoring_methods", "--material", str(material), "--rows", f"{bare},{high}", "--repeat", "1",
        "--name", "e", "--confirm",
    )

    assert "칸 4개를 돌렸다" in out
    # 붙이지 않은 줄은 사본의 문제 강도(low)·강의실 운영 한도, @high 는 high·실험 한도로 나간다.
    assert sorted(_efforts(vendor), key=str) == sorted(
        [("low", 180), ("low", 180), ("high", ex.EFFORT_VENDOR_TIMEOUT_SECONDS), ("high", ex.EFFORT_VENDOR_TIMEOUT_SECONDS)],
        key=str,
    )
    rows = set(ScoringExperimentRun.objects.exclude(row__startswith="운영:").values_list("row", flat=True))
    assert sorted(rows) == [bare, high]
    assert ScoringExperimentRun.objects.filter(row__in=rows, status="scored").count() == 4

    report = _call("experiment_report", "e")
    for name in (bare, high):  # 강도별 줄이 보고표(줄마다 칸 2·판정 2)에 따로 선다
        assert f"\n| {name} | 2 | 2 | 2 |" in report

    bill = _call("experiment_report", "e", "--bill")
    assert f"{HAIKU}@" not in bill and HAIKU in bill  # 청구 대조는 모델 이름으로 묶는다
