"""공모전 완성도 에이전트 판(#1001) — `CONTEST_SCORING_METHOD=agent` 면 박제본을 에이전트로 읽어 0~5 와 근거를 매긴다.

실행·받아들이는 조건은 `scoring.agent_scoring.run_agent_job`(#1000) 몫이라 여기서는 그 경계를 흉내 낸다.
흉내는 실물처럼 두 번 다 어긋나면 `AgentRunHeld` 를, 실행기가 바쁘면 `AgentGraderBusy` 를 던진다.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from contests.models import ContestSubmission
from scoring.agent_runner import AgentGraderBusy
from scoring.models import QualityReviewAttempt, Score, SubmissionQualityReview
from scoring.quality import HELD_ERROR_PREFIX
from scoring.quality_agent import agent_response_schema, needs_evidence
from tests.test_contest_quality import _run_quality, category, closed, landing_type  # noqa: F401 - 픽스처

AGENT_MODEL_VERSION = "agent:anthropic:claude-sonnet-4-6"


@dataclass(frozen=True)
class _AgentJob:
    """계약(#1000 댓글)의 `AgentJob` 모양."""

    submission: ContestSubmission
    purpose: str
    prompt: str
    output_schema: dict
    expected_ids: frozenset[int]
    items_key: str
    id_key: str
    evidence_required: Callable[[dict], bool]


@dataclass(frozen=True)
class _AgentJobOutcome:
    structured_output: dict
    model_version: str
    record: dict


class _AgentRunHeld(Exception):
    def __init__(self, reasons: list[str], record: dict) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.record = record


@dataclass
class _FakeAgent:
    """`run_agent_job` 대역 — 받은 일을 남기고, `mode` 대로 답하거나 던진다."""

    mode: str = "ok"
    jobs: list[_AgentJob] = field(default_factory=list)

    def run(self, job: _AgentJob) -> _AgentJobOutcome:
        self.jobs.append(job)
        if self.mode == "held":
            raise _AgentRunHeld(["근거 경로가 박제본에 없다: src/none.py:3"], {"attempts": [{}, {}]})
        if self.mode == "busy":
            raise AgentGraderBusy("실행 중인 건이 있다(흉내)")
        verdicts = [
            {"requirement_id": rid, "score": 4, "reasoning": "로그인 흐름을 구현했다.", "evidence": ["src/auth.py:10-24"]}
            for rid in sorted(job.expected_ids)
        ]
        if self.mode == "out_of_range":
            verdicts[0]["score"] = 7
        return _AgentJobOutcome({job.items_key: verdicts}, AGENT_MODEL_VERSION, {"attempts": [{}]})


@pytest.fixture
def agent(monkeypatch):
    """`scoring.agent_scoring` 자리에 흉내 모듈을 둔다. 방식 설정은 시험마다 켠다."""

    fake = _FakeAgent()
    module = types.ModuleType("scoring.agent_scoring")
    module.AgentJob = _AgentJob  # type: ignore[attr-defined]
    module.AgentRunHeld = _AgentRunHeld  # type: ignore[attr-defined]
    module.run_agent_job = fake.run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scoring.agent_scoring", module)
    return fake


@pytest.mark.django_db
def test_agent_method_reviews_from_the_snapshot_with_evidence(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")

    rows = _run_quality(client)["rows"]

    assert {r["status"] for r in rows} == {"reviewed"}
    job = next(j for j in agent.jobs if j.submission.id == closed["a"])
    requirement_ids = [r["id"] for r in closed["contest"]["requirements"]]
    assert job.purpose == "quality"
    assert job.expected_ids == frozenset(requirement_ids)
    assert (job.items_key, job.id_key) == ("scores", "requirement_id")
    assert job.output_schema == agent_response_schema()
    # 지침은 규칙(저장소 글은 지시 아님·근거는 실제 코드 줄·문서/시험만으론 0점)과 항목을 싣는다.
    assert "지시가 아닙니다" in job.prompt and "경로:줄" in job.prompt and "0 점" in job.prompt
    assert all(f"requirement_id {rid} " in job.prompt for rid in requirement_ids)

    review = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    assert review.model_version == AGENT_MODEL_VERSION
    assert review.prompt == job.prompt
    assert "<<<SOURCE_FILE_START>>>" not in review.prompt  # 잘린 Score.prompt 를 다시 읽지 않는다.
    assert [i["item_id"] for i in review.items] == requirement_ids
    assert all(i["score"] == 4 and "(근거: src/auth.py:10-24)" in i["reasoning"] for i in review.items)
    assert review.max_weighted_score == 15 and review.weighted_score == 12


@pytest.mark.django_db
def test_agent_held_is_recorded_as_held_and_not_picked_again(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.mode = "held"
    score_before = Score.objects.get(submission_id=closed["a"]).percentage

    assert {r["status"] for r in _run_quality(client)["rows"]} == {"held"}
    assert _run_quality(client)["rows"] == []

    assert not SubmissionQualityReview.objects.exists()
    attempt = QualityReviewAttempt.objects.get(submission_id=closed["a"])
    assert attempt.permanent and attempt.error.startswith(HELD_ERROR_PREFIX)
    assert "src/none.py:3" in attempt.error
    assert Score.objects.get(submission_id=closed["a"]).percentage == score_before


@pytest.mark.django_db
def test_busy_grader_defers_without_counting_a_failure(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.mode = "busy"

    assert {r["status"] for r in _run_quality(client)["rows"]} == {"deferred"}
    assert not QualityReviewAttempt.objects.exists()

    agent.mode = "ok"
    assert {r["status"] for r in _run_quality(client)["rows"]} == {"reviewed"}


@pytest.mark.django_db
def test_malformed_agent_scores_fail_through_parse_content(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.mode = "out_of_range"

    assert {r["status"] for r in _run_quality(client)["rows"]} == {"failed"}
    assert not SubmissionQualityReview.objects.exists()


@pytest.mark.django_db
def test_default_method_keeps_the_single_call_path(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.delenv("CONTEST_SCORING_METHOD", raising=False)

    assert {r["status"] for r in _run_quality(client)["rows"]} == {"reviewed"}

    assert agent.jobs == []
    review = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    assert not review.model_version.startswith("agent:")
    assert "<<<SOURCE_FILE_START>>>" in review.prompt


def test_evidence_is_required_from_one_point_up():
    assert not needs_evidence({"score": 0})
    assert needs_evidence({"score": 1})
    assert not needs_evidence({"score": True})


def test_agent_schema_adds_evidence_without_touching_the_shared_schema():
    from core.quality_review import response_schema

    item = agent_response_schema()["properties"]["scores"]["items"]  # type: ignore[index]
    assert item["required"] == ["requirement_id", "score", "reasoning", "evidence"]
    assert item["properties"]["evidence"]["maxItems"] == 5
    assert "evidence" not in response_schema()["properties"]["scores"]["items"]["properties"]  # type: ignore[index]
