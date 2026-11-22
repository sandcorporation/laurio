"""#1278: 에이전트가 보는 경로 = 체크리스트·한 번 호출이 보는 경로. 세 꼴 × 세 길.

꼴: ① 최상위 폴더 하나로 싼 학생 zip(`final/…`) ② GitHub zipball(`<owner>-<repo>-<sha>/…`) ③ 최상위에 파일이 여럿인 zip.
길: CLI(가짜 `claude`·`codex`), 우리 루프(selfloop, 가짜 프록시), 한 번 호출(`select_source_files`).

박제본은 채점이 쓰는 그 함수(`scoring.services._agent_snapshot`·`classroom.agent_grading.snapshot_of`)로 만들고,
백엔드가 지은 요청을 진짜 실행기(`agent_runner.execute_run`)에 그대로 넘긴다 — 박제본의 자산 종류가 실행기까지
가지 않으면(#1278 의 원인) 학생 zip 의 `final/` 이 벗겨져 체크리스트 경로가 실행기 안에 없다.
"""

from __future__ import annotations

import io
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath

import pytest
from django.test import override_settings

from classroom.agent_grading import snapshot_of
from core import agent_scoring
from core.agent_prompt import ID_KEY, ITEMS_KEY, SCORING_OUTPUT_SCHEMA
from core.agent_scoring import AgentJob, Snapshot, run_agent_job
from core.llm_scoring import RequirementInput
from core.source_selection import select_source_files
from core.repository_adapters import ClonedRepository
from scoring import agent_runner as ar
from scoring import services
from scoring.experiment import count_real_evidence
from scoring.selfloop_scoring import run_selfloop_scoring
from submissions.models import SubmissionAsset
from tests import selfloop_fake
from tests.integration.test_scoring import category, landing_type  # noqa: F401 - fixture 등록
from tests.integration.test_scoring_transient_vendor_failure import _closed_submission
from tests.selfloop_fake import Call, FakeProxy, Say, serve

MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4.1-mini"}
SH = "echo ok\n"


@dataclass(frozen=True)
class Shape:
    name: str
    asset_kind: str
    files: dict[str, str]
    want: str  # 체크리스트가 말하는 경로
    prefix: str  # 실행기가 벗길 최상위 폴더


SHAPES = [
    Shape(
        "student-single-folder",
        SubmissionAsset.Kind.SOURCE,
        {"final/archive/pack.sh": SH, "final/logs/rotate.sh": SH, "final/scripts/run.sh": SH, "final/backup/save.sh": SH},
        want="final/archive/pack.sh",
        prefix="",
    ),
    Shape(
        "github-zipball",
        SubmissionAsset.Kind.REPOSITORY,
        {"octo-repo-abc123/src/login.py": "def login():\n    return True\n", "octo-repo-abc123/main.py": "import src\n"},
        want="src/login.py",
        prefix="octo-repo-abc123",
    ),
    Shape(
        "flat-upload",
        SubmissionAsset.Kind.SOURCE,
        {"app.py": "def login():\n    return True\n", "lib/util.py": "x = 1\n", "run.sh": SH},
        want="app.py",
        prefix="",
    ),
]
shapes = pytest.mark.parametrize("shape", SHAPES, ids=[s.name for s in SHAPES])
vendors = pytest.mark.parametrize("vendor", ["anthropic", "openai"])


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _contest_snapshot(shape: Shape) -> Snapshot:
    raw = _zip(shape.files)
    asset = SubmissionAsset(pk=1, kind=shape.asset_kind)
    if shape.asset_kind == SubmissionAsset.Kind.REPOSITORY:
        snapshot = services._agent_snapshot([], [(asset, ClonedRepository(zip_bytes=raw, commit_sha="abc123"))])
    else:
        snapshot = services._agent_snapshot([(asset, raw)], [])
    assert snapshot is not None
    return snapshot


def _seen_by_one_shot(shape: Shape) -> set[str]:
    return {f.path for f in select_source_files([(1, "src", _zip(shape.files))])}


def _as_one_shot_path(prefix: str, path: str) -> str:
    return str(PurePosixPath(prefix, path)) if prefix else path


@pytest.fixture
def anthropic_open():
    with override_settings(PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE=date(2020, 1, 1)):
        yield


# ── 박제본의 종류 ────────────────────────────────────────────────────────────────────────────────────────


@shapes
def test_contest_and_classroom_snapshots_carry_the_asset_kind(shape: Shape) -> None:
    expected = "repository" if shape.asset_kind == SubmissionAsset.Kind.REPOSITORY else "upload"
    assert _contest_snapshot(shape).kind == expected
    classroom = snapshot_of(_zip(shape.files), SubmissionAsset(pk=1, kind=shape.asset_kind))
    assert classroom is not None and classroom.kind == expected


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────────────

#: 가짜 CLI — 지침의 `WANT:<경로>` 가 실행 폴더에 있으면 충족·근거 `<경로>:1`. 판정 이유에 본 파일 목록을 싣는다.
FAKE_AGENT = """#!{python}
import json, os, sys
prompt = sys.stdin.read()
want = next(line[5:] for line in prompt.splitlines() if line.startswith("WANT:"))
rid = int(next(line[4:] for line in prompt.splitlines() if line.startswith("RID:")))
files = sorted(os.path.relpath(os.path.join(d, f), os.getcwd()) for d, _, fs in os.walk(os.getcwd()) for f in fs)
found = want in files
out = {{"verdicts": [{{"requirement_id": rid, "met": found, "evidence": [want + ":1"] if found else [],
                       "reason": "files=" + ",".join(files)}}]}}
if os.path.basename(sys.argv[0]) == "claude":
    events = [
        {{"type": "system", "subtype": "init", "tools": ["Read", "Grep", "Glob"], "apiKeySource": "ANTHROPIC_API_KEY"}},
        {{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "name": n, "input": {{}}}} for n in ("Glob", "Read", "Grep")]}}}},
        {{"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.01,
          "usage": {{"input_tokens": 10, "output_tokens": 5}}, "structured_output": out}},
    ]
else:
    events = [
        {{"type": "thread.started", "thread_id": "t"}},
        {{"type": "item.completed", "item": {{"type": "command_execution", "command": "ls", "exit_code": 0, "aggregated_output": ""}}}},
        {{"type": "item.completed", "item": {{"type": "agent_message", "text": json.dumps(out)}}}},
        {{"type": "turn.completed", "usage": {{"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5}}}},
    ]
print("\\n".join(json.dumps(e) for e in events))
"""


@pytest.mark.django_db
@shapes
@vendors
def test_cli_agent_sees_the_checklist_path_and_its_evidence_is_accepted(
    client, category, landing_type, monkeypatch, tmp_path, anthropic_open, shape: Shape, vendor: str  # noqa: F811
):
    submission_id, _ = _closed_submission(client, category, landing_type)
    submission = services.ContestSubmission.objects.get(pk=submission_id)
    rid = submission.contest.requirements.get().id
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "codex"):
        (bin_dir / name).write_text(FAKE_AGENT.format(python=sys.executable), encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    results: list[ar.RunResult] = []

    def run_in_process(spec, repo_zip: bytes, *, timeout: float):
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(repo_zip)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        config = ar.RunnerConfig(work_root=work, proxy_base_url="http://proxy.test:8002", cli_path=f"{bin_dir}:/usr/bin:/bin")
        results.append(ar.execute_run(ar.validate_spec(dict(spec)), zip_path, config))
        return results[-1]

    monkeypatch.setattr(agent_scoring, "request_run", run_in_process)
    snapshot = _contest_snapshot(shape)
    outcome = run_agent_job(
        AgentJob(
            submission=submission,
            purpose="scoring",
            build_prompt=lambda _model: f"WANT:{shape.want}\nRID:{rid}\n",
            output_schema=SCORING_OUTPUT_SCHEMA,
            expected_ids=frozenset({rid}),
            items_key=ITEMS_KEY,
            id_key=ID_KEY,
            evidence_required=lambda item: item.get("met") is True,
            load_snapshot=lambda: snapshot,
            pinned_model=(vendor, MODELS[vendor]),
            total_budget_usd=Decimal("1"),
        )
    )

    (verdict,) = outcome.structured_output["verdicts"]
    assert verdict["met"] is True, verdict["reason"]
    assert verdict["evidence"] == [f"{shape.want}:1"]
    assert outcome.record["attempts"][-1]["evidence_check"]["bad"] == []
    (result,) = results
    assert result["repo_root_prefix"] == shape.prefix
    seen = set(verdict["reason"].removeprefix("files=").split(","))
    assert {_as_one_shot_path(shape.prefix, p) for p in seen} == _seen_by_one_shot(shape)
    assert _as_one_shot_path(shape.prefix, shape.want) in _seen_by_one_shot(shape)


# ── 우리 루프(selfloop) ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@shapes
@vendors
def test_selfloop_reads_the_checklist_path_and_its_evidence_is_accepted(
    client, category, landing_type, monkeypatch, tmp_path, anthropic_open, shape: Shape, vendor: str  # noqa: F811
):
    submission_id, _ = _closed_submission(client, category, landing_type)
    submission = services.ContestSubmission.objects.get(pk=submission_id)
    rid = submission.contest.requirements.get().id
    requirements = [RequirementInput(requirement_id=rid, text=f"{shape.want} 가 있다", grade="required", self_reported_met=True)]
    good = Call("submit_verdict", {"met": True, "evidence": [f"{shape.want}:1"], "reason": "있다."})
    proxy = FakeProxy(
        vendor=vendor,
        model=MODELS[vendor],
        script={"map": [[Say("지도 생략")]], rid: [[Call("read_file", {"path": shape.want})], [good]]},
    )
    results: list[ar.RunResult] = []

    def run_in_process(spec, repo_zip: bytes, *, timeout: float):
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(repo_zip)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        monkeypatch.setattr(selfloop_fake, "TOKEN", spec["run_token"])
        results.append(
            ar.execute_run(ar.validate_spec(dict(spec)), zip_path, ar.RunnerConfig(work_root=work, proxy_base_url=proxy.url))
        )
        return results[-1]

    monkeypatch.setattr(agent_scoring, "request_run", run_in_process)
    with serve(proxy):
        outcome = run_selfloop_scoring(
            submission, requirements, _contest_snapshot(shape), vendor=vendor, model=MODELS[vendor]
        )

    assert outcome.structured_output["verdicts"] == [
        {"requirement_id": rid, "met": True, "evidence": [f"{shape.want}:1"], "reason": "있다."}
    ]
    assert proxy.rejections == []
    (result,) = results
    assert result["repo_root_prefix"] == shape.prefix


# ── 근거 대조(비교 실험) ──────────────────────────────────────────────────────────────────────────────────


@shapes
def test_experiment_evidence_check_finds_the_checklist_path(shape: Shape) -> None:
    snapshot = _contest_snapshot(shape)
    assert count_real_evidence(snapshot, [{"evidence": [f"{shape.want}:1"]}]) == (1, 1)
