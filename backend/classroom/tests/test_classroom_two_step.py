"""#1286: staged 의 큰 제출은 두 걸음 — 파일 목록으로 고르고, 고른 파일만 상한 안에서 실어 판정한다.

가짜 벤더(`requests.post` 흉내)로 HTTP 경계에서 본다: 문턱 아래는 1회, 위는 2회, 없는 경로는 버림, 빈 선택은 지금의
소스 고르기로, 상한 자르기, 끔(0)이면 크기 초과 보류가 그대로.
"""

from __future__ import annotations

import pytest

from classroom import two_step
from classroom.models import ClassroomScore, ClassroomScoringAttempt
from classroom.pending_scoring import SIZE_HOLD_ERROR_PREFIX
from classroom.tests.test_classroom_machine_check import _world, staged  # noqa: F401 - fixture
from core.llm_scoring import Citation, RequirementVerdict, ScoringOutput, SourceFile
from tests.classroom_scenarios import FakeVendorResponse, force_real_scoring_adapter, get_class, openai_verdicts_body, run_scan

pytestmark = pytest.mark.usefixtures("reset_rate_limits")

APP = "repo-1a2b/src/app.py"
TOML = "repo-1a2b/pyproject.toml"
CONFIG = "repo-1a2b/config.yaml"


def _whole(path: str) -> dict:
    return {"path": path, "start_line": 1, "end_line": 1}


def _scan(client, monkeypatch, bodies, sent: list[dict]) -> dict:
    """`bodies` 는 (진입점 항목 id, 시험 항목 id) → 그 호출의 판정 목록. 호출마다 토큰 10."""

    with force_real_scoring_adapter():
        ctx = _world(client, [("진입점이 있다", None), ("시험이 있다", None)])
        queue = [b(*ctx["item_ids"]) for b in bodies]

        def _handler(*args, **kwargs):
            sent.append(kwargs["json"])
            return FakeVendorResponse(200, openai_verdicts_body(queue.pop(0), total_tokens=10))

        monkeypatch.setattr("core.llm_scoring.requests.post", _handler)
        run_scan(client)
    return ctx


def _user_prompt(request: dict) -> str:
    return {m["role"]: m["content"] for m in request["messages"]}["user"]


def _pick(app_paths: list[str], test_paths: list[str]):
    return lambda app, test: [
        {"requirement_id": app, "is_met": False, "reasoning": "고름", "citations": [_whole(p) for p in app_paths]},
        {"requirement_id": test, "is_met": False, "reasoning": "고름", "citations": [_whole(p) for p in test_paths]},
    ]


def _judge(app, test):
    return [
        {"requirement_id": app, "is_met": True, "reasoning": "근거", "citations": [{"path": APP, "start_line": 3, "end_line": 4}]},
        {"requirement_id": test, "is_met": False, "reasoning": "근거", "citations": []},
    ]


@pytest.fixture
def low_threshold(monkeypatch):
    monkeypatch.setenv("CLASSROOM_TWO_STEP_THRESHOLD_CHARS", "100")


def test_below_the_threshold_is_one_call(client, db, monkeypatch, staged):  # noqa: F811
    sent: list[dict] = []
    _scan(client, monkeypatch, [_judge], sent)

    assert len(sent) == 1
    assert two_step.SELECTION_RULE not in _user_prompt(sent[0])


def test_above_the_threshold_picks_files_first_then_judges_only_those(client, db, monkeypatch, staged, low_threshold):  # noqa: F811
    sent: list[dict] = []
    ctx = _scan(client, monkeypatch, [_pick([APP], [TOML]), _judge], sent)

    assert len(sent) == 2
    first, second = _user_prompt(sent[0]), _user_prompt(sent[1])
    # 1차: 파일 목록(경로·바이트·줄 수)과 판단 항목만 — 소스 내용은 없다.
    assert two_step.SELECTION_RULE in first
    assert f"{APP}\t" in first and f"{CONFIG}\t" in first
    assert "import os" not in first
    # 2차: 고른 파일만, 줄 번호를 붙여서.
    assert f"# {APP}\n1\timport os" in second and f"# {TOML}\n1\t[tool.ruff]" in second
    assert "port: 8080" not in second
    assert two_step.SELECTION_RULE not in second
    # 인용 대조는 2차가 실은 파일로, 저장 프롬프트는 2차 것.
    score = ClassroomScore.objects.get()
    by_id = {r["checklist_item_id"]: r for r in score.reasoning}
    app_id, _ = ctx["item_ids"]
    assert (by_id[app_id]["verdict"], by_id[app_id]["suspect"]) == ("met", False)
    assert score.prompt == second
    # 두 호출의 토큰을 모두 센다.
    assert get_class(client, ctx["access"], ctx["class_id"])["token_usage_total"] == 20


def test_a_path_not_in_the_list_is_dropped(client, db, monkeypatch, staged, low_threshold):  # noqa: F811
    sent: list[dict] = []
    _scan(client, monkeypatch, [_pick(["repo-1a2b/src/main.py", APP], ["/etc/passwd"]), _judge], sent)

    second = _user_prompt(sent[1])
    assert f"# {APP}\n" in second
    assert "main.py" not in second and "passwd" not in second and f"# {TOML}" not in second


def test_an_empty_selection_falls_back_to_the_usual_source_choice(client, db, monkeypatch, staged, low_threshold):  # noqa: F811
    sent: list[dict] = []
    _scan(client, monkeypatch, [_pick([], ["nope.py"]), _judge], sent)

    second = _user_prompt(sent[1])
    assert f"# {APP}\n" in second and f"# {TOML}\n" in second and f"# {CONFIG}\n1\tserver:" in second


def test_the_second_step_is_cut_to_the_budget_in_item_order(client, db, monkeypatch, staged, low_threshold):  # noqa: F811
    app_chars = len(two_step.numbered_file_text(SourceFile(path=APP, content="import os\n\ndef main():\n    print('hello')\n", asset_id=0)))
    monkeypatch.setenv("CLASSROOM_TWO_STEP_BUDGET_CHARS", str(app_chars + 2 + len(f"# {TOML}\n1\t[tool.ruff]")))
    sent: list[dict] = []
    _scan(client, monkeypatch, [_pick([APP], [TOML, CONFIG]), _judge], sent)

    second = _user_prompt(sent[1])
    assert f"# {APP}\n1\timport os\n2\t\n3\tdef main():\n4\t    print('hello')" in second
    assert f"# {TOML}\n1\t[tool.ruff]" in second and "2\tline-length" not in second
    assert f"# {CONFIG}" not in second


def test_off_keeps_the_size_hold(client, db, monkeypatch, staged):  # noqa: F811
    monkeypatch.setenv("CLASSROOM_TWO_STEP_THRESHOLD_CHARS", "0")
    monkeypatch.setattr("classroom.scoring.source_budget_bytes", lambda model, *, instruction_bytes: 5)
    sent: list[dict] = []
    _scan(client, monkeypatch, [], sent)

    assert sent == []
    assert ClassroomScoringAttempt.objects.filter(error__startswith=SIZE_HOLD_ERROR_PREFIX).exists()


def test_on_goes_two_steps_instead_of_holding_what_the_model_cannot_take(client, db, monkeypatch, staged):  # noqa: F811
    monkeypatch.setattr("classroom.scoring.source_budget_bytes", lambda model, *, instruction_bytes: 5)
    sent: list[dict] = []
    _scan(client, monkeypatch, [_pick([APP], []), _judge], sent)

    assert len(sent) == 2
    assert not ClassroomScoringAttempt.objects.filter(error__startswith=SIZE_HOLD_ERROR_PREFIX).exists()
    assert ClassroomScore.objects.exists()


def _plan(files: list[SourceFile], budget: int) -> two_step.TwoStepPlan:
    return two_step.TwoStepPlan(
        files=tuple(files),
        fallback_files=(files[0],),
        item_ids=(1, 2),
        budget_chars=budget,
        selection_prompt="",
        asset_id=0,
        asset_label="",
    )


def _selection(*picks: tuple[int, list[str]]) -> ScoringOutput:
    return ScoringOutput(
        verdicts=[
            RequirementVerdict(requirement_id=i, is_met=False, reasoning="", citations=tuple(Citation(path=p, start_line=1, end_line=1) for p in paths))
            for i, paths in picks
        ],
        model_version="m",
    )


def test_selection_follows_item_order_not_answer_order_and_dedupes():
    files = [SourceFile(path=p, content="x\n", asset_id=0) for p in ("a.py", "b.py", "c.py")]
    plan = _plan(files, 10_000)

    picked = two_step.second_step_files(_selection((2, ["c.py", "./a.py"]), (1, ["b.py", "c.py"])), plan)

    assert [f.path for f in picked] == ["b.py", "c.py", "a.py"]
