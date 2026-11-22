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


def _staged_item(n: int, *, rule: bool) -> em.Item:
    base = _item(n, met=rule)
    first = em.ChecklistEntry(
        REQ, "main.py 가 있다", "required", False, 1, machine_rule={"kind": "path_exists", "path": "main.py"} if rule else None
    )
    return em.Item(**{**base.__dict__, "checklist": (first, base.checklist[1])})


STAGED = "classroom_staged:gpt-4.1-mini"


@pytest.mark.django_db
def test_classroom_staged_runs_beside_classroom_call_and_splits_machine_from_model(home, money, monkeypatch):
    from classroom import scoring as classroom_scoring

    modes = []

    def adapter(**kwargs):
        modes.append(kwargs["mode"])
        return FakeClassroomScoringAdapter()

    monkeypatch.setattr(classroom_scoring, "_scoring_adapter", adapter)
    monkeypatch.setattr(classroom_material, "_scoring_adapter", adapter)
    path = _material(home, [_staged_item(1, rule=True), _staged_item(2, rule=False)])

    out = _call("compare_scoring_methods", "--material", str(path), "--rows", f"{CLASSROOM},{STAGED}", "--repeat", "1")
    assert STAGED in out and CLASSROOM in out and "--confirm 이 없어 모델을 부르지 않았다." in out and not modes

    _call("compare_scoring_methods", "--material", str(path), "--rows", f"{CLASSROOM},{STAGED}", "--repeat", "1", "--name", "s", "--confirm")

    staged = {r.material_id: r for r in ScoringExperimentRun.objects.filter(row=STAGED)}
    assert len(ScoringExperimentRun.objects.filter(row=CLASSROOM)) == 2 and len(staged) == 2
    for run in staged.values():
        assert len(run.verdicts) == 2  # 기계 확정 + 모델 = 항목 수
    sources = lambda n: [v["source"] for v in staged[em.pseudonym("t1262", n)].verdicts]  # noqa: E731
    assert sources(1) == ["machine", "model"] and sources(2) == ["model", "model"]
    assert staged[em.pseudonym("t1262", 1)].verdicts[0]["met"] is True

    md = _call("experiment_report", "s")
    assert "| 기계 확정 항목 수 | 모델에 간 항목 수 |" in md.replace("---", "").replace("  ", " ") or "기계 확정 항목 수" in md
    row = next(line for line in md.splitlines() if line.startswith(f"| {STAGED} |"))
    assert row.endswith("| 0.5 | 1.5 |")
    assert next(line for line in md.splitlines() if line.startswith(f"| {CLASSROOM} |")).endswith("| — | — |")


@pytest.mark.django_db
def test_classroom_staged_derives_per_cell_and_adds_the_derivation_cost(monkeypatch):
    from classroom import rule_derivation

    asked = []

    def derive(head, model, *, mode=None):
        asked.append((model, mode, [c.id for c in head.checklist_items]))
        for c in head.checklist_items:  # 사본에 도출이 없어 칸마다 이 항목들에 얹는다
            if c.id == OPT:
                c.derived_rule = {"kind": "path_exists", "path": "main.py"}
                c.derived_kind = rule_derivation.KIND_STATIC
                c.derived_text_hash = rule_derivation.label_hash(c.label)
        return rule_derivation.Derivation(results=(), total_tokens=300, input_tokens=200, output_tokens=100, model="gpt-4.1-nano")

    monkeypatch.setattr(classroom_material, "_derive_rules", derive)
    result = classroom_material.experiment_staged_call(_staged_item(1, rule=True), model="gpt-4.1-mini", api_key=None)

    assert asked == [("gpt-4.1-mini", "fake", [REQ, OPT])]
    assert ("gpt-4.1-nano", 200, 100) in result.extra_usage
    assert set(result.machine_ids) == {REQ, OPT}  # 도출 규칙이 선택 항목도 기계가 정하게 했다
    assert [v.checklist_item_id for v in result.verdicts] == [REQ, OPT]


def test_classroom_staged_needs_material():
    with pytest.raises(ex.ExperimentError, match="사본 재료"):
        ex.parse_rows(STAGED)


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


# ── 항목별 정답(#1288) ───────────────────────────────────────────────────────────────────────────────────


def _truth_csv(tmp_path: Path, rows: list[tuple[str, int, str]], *, header: str = "material_id,item_id,is_met") -> Path:
    path = tmp_path / "truth.csv"
    path.write_text("\n".join([header, *(f"{m},{i},{v}" for m, i, v in rows)]) + "\n", encoding="utf-8")
    return path


def _full_truth(m1: str, m2: str) -> list[tuple[str, int, str]]:
    return [(m1, REQ, "충족"), (m1, OPT, "미충족"), (m2, REQ, "미충족"), (m2, OPT, "미충족")]


def _cells_of(md: str, row: str) -> dict[str, str]:
    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    line = next(ln for ln in lines[2:] if ln.startswith(f"| {row} |"))
    return dict(zip(header, [c.strip() for c in line.strip("|").split("|")], strict=True))


@pytest.mark.django_db
def test_fill_truth_writes_the_answers_into_the_material_and_calls_no_model(home, tmp_path):
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    m1, m2 = items[0].material_id, items[1].material_id

    out = _call("compare_scoring_methods", "--material", str(path), "--fill-truth", str(_truth_csv(tmp_path, _full_truth(m1, m2))))

    assert "기준 판정을 채웠다 — 제출 2건" in out and "모델은 부르지 않았다" in out
    loaded = em.load(path, repo_root=Path("/nonexistent-repo-root"))
    by_id = {i.material_id: i for i in loaded.items}
    assert by_id[m1].truth == (em.TruthVerdict(REQ, True), em.TruthVerdict(OPT, False))
    assert by_id[m2].truth == (em.TruthVerdict(REQ, False), em.TruthVerdict(OPT, False))
    assert by_id[m1].source == items[0].source and stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.django_db
@pytest.mark.parametrize(
    "rows_of, reason",
    [
        (lambda m1, m2: [(m1, REQ, "충족")], "기준 판정이 빠졌다"),
        (lambda m1, m2: [(m1, REQ, "충족"), (m1, OPT, "충족"), ("0" * 12, REQ, "충족")], "재료에 없는 제출 id"),
        (lambda m1, m2: [(m1, REQ, "충족"), (m1, 999, "충족")], "체크리스트에 없는 항목 id"),
        (lambda m1, m2: [(m1, REQ, "충족"), (m1, OPT, "글쎄")], "충족 값을 읽을 수 없다"),
        (lambda m1, m2: [(m1, REQ, "충족"), (m1, REQ, "충족")], "같은 칸이 두 번"),
    ],
)
def test_a_bad_truth_csv_is_refused_and_leaves_the_material_alone(home, tmp_path, rows_of, reason):
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    before = path.read_bytes()

    with pytest.raises(CommandError, match=reason):
        _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
              str(_truth_csv(tmp_path, rows_of(items[0].material_id, items[1].material_id))))

    assert path.read_bytes() == before


def _six_column_csv(tmp_path: Path, rows: list[tuple[str, int, str, str]]) -> Path:
    path = tmp_path / "six.csv"
    lines = ["material_id,item_id,is_met,evidence,confidence,note"]
    lines += [f"{m},{i},{v},main.py:1 학생 원문,{c},메모 글" for m, i, v, c in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.django_db
def test_truth_csv_with_other_leading_columns_is_refused(home, tmp_path):
    path = _material(home, [_item(1, met=True)])
    csv_path = _truth_csv(tmp_path, [], header="student_name,material_id,item_id,is_met")

    with pytest.raises(CommandError, match="앞 열은 material_id,item_id,is_met"):
        _call("compare_scoring_methods", "--material", str(path), "--fill-truth", str(csv_path))


@pytest.mark.django_db
def test_six_column_table_is_accepted_and_only_confidence_reaches_the_material(home, tmp_path):
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    m1, m2 = items[0].material_id, items[1].material_id
    csv_path = _six_column_csv(tmp_path, [(m1, REQ, "1", "high"), (m1, OPT, "0", "low"), (m2, REQ, "0", ""), (m2, OPT, "0", "Medium")])

    _call("compare_scoring_methods", "--material", str(path), "--fill-truth", str(csv_path))

    by_id = {i.material_id: i for i in em.load(path, repo_root=Path("/nonexistent-repo-root")).items}
    assert by_id[m1].truth == (em.TruthVerdict(REQ, True, "high"), em.TruthVerdict(OPT, False, "low"))
    assert by_id[m2].truth == (em.TruthVerdict(REQ, False, ""), em.TruthVerdict(OPT, False, "medium"))
    raw = b"".join(p.read_bytes() for p in [path])
    import tarfile

    with tarfile.open(path) as tar:
        text = b"".join(tar.extractfile(m).read() for m in tar.getmembers() if m.isfile() and m.name.endswith(".json"))
    assert "학생 원문".encode() not in text and "메모 글".encode() not in text and raw


@pytest.mark.django_db
def test_unknown_confidence_is_refused(home, tmp_path):
    items = [_item(1, met=True)]
    path = _material(home, items)
    m1 = items[0].material_id
    with pytest.raises(CommandError, match="확신 값을 읽을 수 없다"):
        _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
              str(_six_column_csv(tmp_path, [(m1, REQ, "1", "sure"), (m1, OPT, "0", "high")])))


@pytest.mark.django_db
def test_a_submission_with_every_row_blank_is_skipped_and_a_partly_blank_one_is_refused(home, tmp_path):
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    m1, m2 = items[0].material_id, items[1].material_id

    out = _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
                str(_six_column_csv(tmp_path, [(m1, REQ, "1", "high"), (m1, OPT, "0", "high"), (m2, REQ, "", ""), (m2, OPT, "", "")])))
    assert "제출 1건" in out
    by_id = {i.material_id: i for i in em.load(path, repo_root=Path("/nonexistent-repo-root")).items}
    assert by_id[m2].truth == ()

    with pytest.raises(CommandError, match=f"제출 {m2} 의 항목 \\[{OPT}\\] 충족 값이 비었다"):
        _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
              str(_six_column_csv(tmp_path, [(m1, REQ, "1", "high"), (m1, OPT, "0", "high"), (m2, REQ, "0", ""), (m2, OPT, "", "")])))


@pytest.mark.django_db
def test_report_adds_the_same_three_for_high_confidence_cells_only(home, money, monkeypatch, tmp_path):
    _fake_single(monkeypatch)  # 항목 REQ 를 늘 미충족으로 판정한다
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    m1, m2 = items[0].material_id, items[1].material_id
    # 제출1 REQ(충족, 이 줄이 틀린다)를 medium 으로 달면 low 와 같이 빠진다 — high 만의 일치는 맞는 칸들뿐이다.
    csv_path = _six_column_csv(tmp_path, [(m1, REQ, "1", "medium"), (m1, OPT, "0", "high"), (m2, REQ, "0", "high"), (m2, OPT, "0", "low")])
    _call("compare_scoring_methods", "--material", str(path), "--fill-truth", str(csv_path))
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "c", "--confirm")

    single = _cells_of(_call("experiment_report", "c"), SINGLE)

    assert single["기준 판정과의 일치"] == "50.0%" and single["기준 대비 오탐률"] == "100.0%"
    assert single["high 만 기준 판정과의 일치"] == "100.0%"
    assert single["high 만 기준 미충족 재현율"] == "100.0%"
    assert single["high 만 기준 대비 오탐률"] == "—"  # 충족 기준 칸이 medium 하나뿐이라 남지 않았다


@pytest.mark.django_db
def test_report_ends_with_a_per_item_mismatch_table_and_none_without_truth(home, money, monkeypatch, tmp_path):
    _fake_single(monkeypatch)  # 항목 REQ 를 늘 미충족으로 판정한다 — 제출1 REQ(충족)만 어긋난다
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    m1, m2 = items[0].material_id, items[1].material_id
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "n", "--confirm")
    assert "항목별 불일치" not in _call("experiment_report", "n")

    _call("compare_scoring_methods", "--material", str(path), "--fill-truth", str(_truth_csv(tmp_path, _full_truth(m1, m2))))
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "w", "--confirm")
    md = _call("experiment_report", "w")

    table = md.split("## 항목별 불일치 칸 수(제출 × 회차)")[1].strip().splitlines()
    assert table[0].startswith("| 항목 id | 기준 판정 칸 수 | single_call:gpt-4.1-mini")
    assert table[2].startswith(f"| {REQ} | 2 | 1")  # 불일치가 몰린 항목이 첫 행
    assert table[3].startswith(f"| {OPT} | 2 | 0")
    assert "add_two_numbers" not in "\n".join(table)  # 항목 글은 넣지 않는다


@pytest.mark.django_db
def test_three_column_table_still_works_and_has_no_confidence_columns_filled(home, money, monkeypatch, tmp_path):
    _fake_single(monkeypatch)
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
          str(_truth_csv(tmp_path, _full_truth(items[0].material_id, items[1].material_id))))
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "d", "--confirm")

    single = _cells_of(_call("experiment_report", "d"), SINGLE)

    assert single["기준 판정과의 일치"] == "50.0%"
    assert (single["high 만 기준 판정과의 일치"], single["high 만 기준 미충족 재현율"], single["high 만 기준 대비 오탐률"]) == ("—", "—", "—")


@pytest.mark.django_db
def test_fill_truth_needs_material():
    with pytest.raises(CommandError, match="--material 과 함께"):
        _call("compare_scoring_methods", "--contest", "1", "--fill-truth", "x.csv")


@pytest.mark.django_db
def test_report_fills_accuracy_recall_and_false_positive_rate_when_the_material_has_truth(home, money, monkeypatch, tmp_path):
    _fake_single(monkeypatch)  # 이 줄은 항목 REQ 를 늘 미충족으로 판정한다
    items = [_item(1, met=True), _item(2, met=False)]
    path = _material(home, items)
    _call("compare_scoring_methods", "--material", str(path), "--fill-truth",
          str(_truth_csv(tmp_path, _full_truth(items[0].material_id, items[1].material_id))))
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "t", "--confirm")

    md = _call("experiment_report", "t")

    # 줄: 제출1 REQ(정답 충족)을 미충족으로 → 오답·오탐, 제출2 REQ(정답 미충족)은 미충족으로 → 정답·재현.
    single = _cells_of(md, SINGLE)
    assert (single["기준 판정과의 일치"], single["기준 미충족 재현율"], single["기준 대비 오탐률"]) == ("50.0%", "100.0%", "100.0%")
    # 운영 판정은 정답과 네 칸 모두 같다.
    production = _cells_of(md, "운영:gpt-4.1-mini-2025-04-14")
    assert (production["기준 판정과의 일치"], production["기준 미충족 재현율"], production["기준 대비 오탐률"]) == ("100.0%", "100.0%", "0.0%")
    assert "정답:사람" not in md and "기준 판정(알려진 미충족)이 없는 재료" not in md
    assert "항목별 기준 판정과 견준 값" in md


@pytest.mark.django_db
def test_report_without_truth_keeps_the_dash_cells_and_the_note(home, money, monkeypatch):
    _fake_single(monkeypatch)
    path = _material(home, [_item(1, met=True), _item(2, met=False)])
    _call("compare_scoring_methods", "--material", str(path), "--rows", SINGLE, "--repeat", "1", "--name", "n", "--confirm")

    md = _call("experiment_report", "n")

    single = _cells_of(md, SINGLE)
    assert (single["기준 판정과의 일치"], single["기준 미충족 재현율"], single["기준 대비 오탐률"]) == ("—", "—", "—")
    assert "기준 판정(알려진 미충족)이 없는 재료" in md


def test_classroom_staged_confirms_only_met_and_sends_the_machine_note_like_production():
    """#1294 — 규칙이 미충족으로 본 항목은 확정하지 않고 「기계 확인: …」 메모를 달아 모델에게 넘긴다(운영과 같은 프롬프트)."""

    base = _item(1, met=True)
    missing = em.ChecklistEntry(
        REQ, "nope.py 가 있다", "required", False, 1, machine_rule={"kind": "path_exists", "path": "nope.py"}
    )
    item = em.Item(**{**base.__dict__, "checklist": (missing, base.checklist[1])})

    result = classroom_material.experiment_staged_call(item, model="gpt-4.1-mini", api_key=None)

    assert REQ not in result.machine_ids  # 미충족은 기계가 확정하지 않는다
    assert "기계 확인:" in result.prompt
    assert REQ in [v.checklist_item_id for v in result.verdicts]
