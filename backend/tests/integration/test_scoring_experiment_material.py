"""#1262: 채점 방식 실험이 사본 재료(`compare_scoring_methods --material`)로 돈다.

사본은 지어낸 소스로 만든다(`core.experiment_material.write`). 진짜 벤더는 부르지 않는다 — 한 번 호출은 줄 실행기를
바꿔 끼우고, `classroom_call` 은 강의실 흉내 어댑터로 돈다(`--confirm` 이면 실제 벤더 모드를 고르는지만 본다).
"""

from __future__ import annotations

import io
import stat
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from classroom import experiment_material as classroom_material
from classroom.scoring import FakeClassroomScoringAdapter
from core import experiment_material as em
from core.clock import Clock
from policies.runtime_settings import AGENT_EXPERIMENT_DAILY_LIMIT_USD
from scoring import experiment as ex
from scoring.models import ScoringExperiment, ScoringExperimentRun
from tests.classroom_scenarios import zip_bytes

SINGLE = "single_call:gpt-4.1-mini"
CLASSROOM = "classroom_call:gpt-4.1-mini"
REQ, OPT = 11, 12


def _item(n: int, *, met: bool, source: str = "def add_two_numbers(a, b):\n    return a + b\n") -> em.Item:
    return em.Item(
        material_id=em.pseudonym("t1262", n),
        asset_kind="source",
        source=zip_bytes({"main.py": source}),
        problem=em.ProblemText(
            title="두 수 더하기", description="두 수를 더하는 함수를 만든다.", grading_strictness="normal",
            grading_guideline_text="", syntax_check_enabled=False, reasoning_effort=None, marked_reasoning=False,
        ),
        checklist=(
            em.ChecklistEntry(REQ, "add_two_numbers", "required", False, 1),
            em.ChecklistEntry(OPT, "곱하기 함수", "optional", True, 1),
        ),
        verdicts=(em.ProductionVerdict(REQ, met, "지어낸 근거"), em.ProductionVerdict(OPT, False, "지어낸 근거")),
        model_version="gpt-4.1-mini-2025-04-14",
    )


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """사본 자리 — 저장소 밖. 시험의 임시 폴더가 /tmp 아래일 수 있어 임시 자리 규칙은 따로 시험한다."""

    monkeypatch.setattr(em, "TEMP_ROOTS", ())
    monkeypatch.setattr(em, "DEFAULT_ROOT", tmp_path / "experiment-material")
    return tmp_path / "experiment-material"


def _material(home: Path, items: list[em.Item], *, days_old: int = 0) -> Path:
    folder = home / "t1262"
    folder.mkdir(parents=True)
    path = folder / "t1262.tar.gz"
    em.write(path, name="t1262", exported_at=Clock.now() - timedelta(days=days_old), items=items)
    return path


def _call(*args: str) -> str:
    out = io.StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


@pytest.fixture
def money(monkeypatch):
    monkeypatch.setenv(AGENT_EXPERIMENT_DAILY_LIMIT_USD, "5")
    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-test-experiment-key")


def _fake_single(monkeypatch):
    monkeypatch.setattr(
        ex, "_RUNNERS",
        {**ex._RUNNERS, "single_call": lambda s, row, i: ex.CellResult(
            "scored", score=Decimal("50"), cost_usd=Decimal("0.01"), verdicts=[{"requirement_id": REQ, "met": False}])},
    )


@pytest.mark.django_db
def test_material_preview_reads_no_production_table_and_shows_pseudonyms(home, money):
    path = _material(home, [_item(1, met=True), _item(2, met=False)])

    with CaptureQueriesContext(connection) as queries:
        out = _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1")

    touched = " ".join(q["sql"] for q in queries)
    for table in ("classroom_", "contests_", "submissions_", "scoring_score"):
        assert table not in touched
    assert f"\n{em.pseudonym('t1262', 1)} | 100.00 | 0 | 1\n" in out
    assert f"\n{em.pseudonym('t1262', 2)} | 0.00 | 1 | 1\n" in out
    assert "키 없음" not in out and "--confirm 이 없어 모델을 부르지 않았다." in out
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@pytest.mark.django_db
def test_confirm_records_only_pseudonyms_and_the_production_row(home, money, monkeypatch):
    _fake_single(monkeypatch)
    path = _material(home, [_item(1, met=True), _item(2, met=False)])

    out = _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "m", "--confirm")

    assert "칸 2개를 돌렸다" in out
    experiment = ScoringExperiment.objects.get(name="m")
    assert experiment.contest is None and experiment.material == "t1262" and experiment.material_required_ids == [REQ]
    runs = list(ScoringExperimentRun.objects.filter(experiment=experiment))
    assert {r.submission_id for r in runs} == {None}
    assert {r.material_id for r in runs} == {em.pseudonym("t1262", 1), em.pseudonym("t1262", 2)}
    assert {r.row for r in runs} == {SINGLE, "운영:gpt-4.1-mini-2025-04-14"}

    md = _call("experiment_report", "m")
    assert "사본 재료 t1262(가명 id) · 기준 줄 single_call:gpt-4.1-mini" in md
    assert "| 운영:gpt-4.1-mini-2025-04-14 |" in md
    assert "## 운영 점수 구간별 평균 차(줄 − 운영:gpt-4.1-mini-2025-04-14)" in md
    assert "| single_call:gpt-4.1-mini | +50.0 (n=1) | — | — | — | -50.0 (n=1) |" in md


@pytest.mark.django_db
def test_same_expected_scores_refuse_confirm_on_material_too(home, money, monkeypatch):
    _fake_single(monkeypatch)
    path = _material(home, [_item(1, met=True), _item(2, met=True)])

    with pytest.raises(CommandError, match=r"뽑힌 제출 2건의 기준 점수가 모두 100.00 — 방식을 가를 수 없다"):
        _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--confirm")
    assert not ScoringExperiment.objects.exists()
    assert "칸 2개를 돌렸다" in _call(
        "compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--cost-only", "--confirm"
    )


@pytest.mark.django_db
def test_a_row_without_a_key_is_marked_and_refused_on_confirm(home, money, monkeypatch):
    _fake_single(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ex, "vendor_key", lambda vendor: "" if vendor == "anthropic" else "sk-test")
    path = _material(home, [_item(1, met=True), _item(2, met=False)])
    rows = f"{SINGLE},single_call:claude-haiku-5-5"

    preview = _call("compare_scoring_methods", "--material", str(path), "--rows", rows, "--repeat", "1")
    assert "\nsingle_call:claude-haiku-5-5 | 2 | 0 |" in preview and preview.count("키 없음") == 1

    with pytest.raises(CommandError, match="키 없음 줄 single_call:claude-haiku-5-5"):
        _call("compare_scoring_methods", "--material", str(path), "--rows", rows, "--repeat", "1", "--confirm")
    assert not ScoringExperimentRun.objects.exists()


@pytest.mark.django_db
def test_classroom_call_uses_the_classroom_prompt_and_goes_real_only_on_confirm(home, money, monkeypatch):
    modes = []

    def adapter(**kwargs):
        modes.append(kwargs["mode"])
        return FakeClassroomScoringAdapter()

    monkeypatch.setattr(classroom_material, "_scoring_adapter", adapter)
    item = _item(1, met=True)

    result = classroom_material.experiment_call(item, model="gpt-4.1-mini", api_key=None)
    assert result.prompt.startswith("문제 제목: 두 수 더하기\n문제 설명: 두 수를 더하는 함수를 만든다.")
    assert f"- requirement_id={REQ} (필수): add_two_numbers" in result.prompt and "제출된 소스:" in result.prompt
    assert [(v.checklist_item_id, v.is_met) for v in result.verdicts] == [(REQ, True), (OPT, False)]
    assert modes == ["fake"]

    path = _material(home, [item, _item(2, met=False, source="print('지어낸 소스')\n")])
    out = _call("compare_scoring_methods", "--material", str(path), "--rows", CLASSROOM, "--repeat", "1", "--name", "c", "--confirm")

    assert "칸 2개를 돌렸다" in out
    assert modes[1:] == [classroom_material.OPENAI_SCORING_ADAPTER] * 2  # 사본 + --confirm 만 실험 키로 나간다
    scores = dict(ScoringExperimentRun.objects.filter(row=CLASSROOM).values_list("material_id", "score"))
    assert scores == {em.pseudonym("t1262", 1): Decimal("100.00"), em.pseudonym("t1262", 2): Decimal("0.00")}


def test_classroom_call_needs_material():
    with pytest.raises(ex.ExperimentError, match="사본 재료"):
        ex.parse_rows(CLASSROOM)


@pytest.mark.django_db
def test_material_inside_the_repo_or_under_tmp_is_refused(tmp_path, monkeypatch):
    item = _item(1, met=True)
    repo = Path(__file__).resolve().parents[3]
    with pytest.raises(em.MaterialError, match="저장소 안"):
        em.check_location(repo / "backend" / "x.tar.gz", repo_root=repo)
    monkeypatch.setattr(em, "TEMP_ROOTS", (tmp_path,))
    path = tmp_path / "t.tar.gz"
    em.write(path, name="t", exported_at=Clock.now(), items=[item])
    with pytest.raises(CommandError, match="임시 자리"):
        _call("compare_scoring_methods", "--material", str(path))


@pytest.mark.django_db
def test_week_old_material_warns_in_preview_and_report(home, money, monkeypatch):
    _fake_single(monkeypatch)
    path = _material(home, [_item(1, met=True), _item(2, met=False)], days_old=8)

    out = _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "w", "--confirm")

    assert out.startswith("경고: 재료 t1262 은 가져온 지 8일 — 7일이 넘었다.")
    assert "경고: 사본 재료를 가져온 지 7일이 넘었다" in _call("experiment_report", "w")


def test_purge_removes_the_material_folder(home):
    folder = home / "t1262"
    folder.mkdir(parents=True)
    (folder / "t1262.tar.gz").write_bytes(b"x")

    assert "재료 t1262 을 지웠다." in _call("compare_scoring_methods", "--purge-material", "t1262")
    assert not folder.exists()
    assert "재료 t1262 이 없다" in _call("compare_scoring_methods", "--purge-material", "t1262")
    with pytest.raises(CommandError, match="재료 이름이 아니다"):
        _call("compare_scoring_methods", "--purge-material", "../x")
