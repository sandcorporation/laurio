"""공모전 완성도 에이전트 판(#1001) — `CONTEST_SCORING_METHOD=agent` 면 박제본을 에이전트로 읽어 0~5 와 근거를 매긴다.

실행·받아들이는 조건은 `core.agent_scoring.run_agent_job`(#1000) 몫이라 여기서는 그 함수를 patch 한다.
흉내는 실물처럼 두 번 다 어긋나면 `AgentRunHeld` 를, 실행기가 바쁘면 `AgentGraderBusy` 를 던진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core import agent_scoring
from scoring.agent_runner import AgentGraderBusy
from core.agent_scoring import AgentJob, AgentJobOutcome, AgentRunHeld, AgentVendorRefused
from scoring.models import QualityReviewAttempt, Score, SubmissionQualityReview
from scoring.quality import HELD_ERROR_PREFIX, QUALITY_FAILURE_LIMIT
from scoring.quality_agent import agent_response_schema, needs_evidence
from payouts.tests.test_contest_quality import _run_quality, category, closed, landing_type  # noqa: F401 - 픽스처

AGENT_MODEL = "claude-sonnet-4-6"
AGENT_MODEL_VERSION = f"agent:anthropic:{AGENT_MODEL}"


@dataclass
class _FakeAgent:
    """`run_agent_job` 대역 — 받은 일을 남기고, `mode` 대로 답하거나 던진다."""

    mode: str = "ok"
    model: str = AGENT_MODEL
    jobs: list[AgentJob] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def run(self, job: AgentJob) -> AgentJobOutcome:
        # 실물처럼 모델을 정한 뒤에 지침을 만든다.
        self.jobs.append(job)
        self.prompts.append(job.build_prompt(self.model))
        if self.mode == "held":
            raise AgentRunHeld(["근거 경로가 박제본에 없다: src/none.py:3"], {"attempts": [{}, {}]})
        if self.mode == "busy":
            raise AgentGraderBusy("실행 중인 건이 있다(흉내)")
        if self.mode == "refused":
            # 실물(`run_agent_job`)이 벤더 계정 거절을 가른 꼴(#1052) — 시도 하나로 멈춘다.
            raise AgentVendorRefused("API Error: 400 You have reached your specified workspace API usage limits.", {"attempts": [{}]})
        verdicts = [
            {"requirement_id": rid, "score": 4, "reasoning": "로그인 흐름을 구현했다.", "evidence": ["src/auth.py:10-24"]}
            for rid in sorted(job.expected_ids)
        ]
        if self.mode == "out_of_range":
            verdicts[0]["score"] = 7
        return AgentJobOutcome({job.items_key: verdicts}, AGENT_MODEL_VERSION, {"attempts": [{}]}, self.prompts[-1])


@pytest.fixture
def agent(monkeypatch):
    """`core.agent_scoring.run_agent_job` 자리에 흉내를 둔다. 방식 설정은 시험마다 켠다."""

    fake = _FakeAgent()
    monkeypatch.setattr(agent_scoring, "run_agent_job", fake.run)
    return fake


@pytest.mark.django_db
def test_agent_method_reviews_from_the_snapshot_with_evidence(client, closed, agent, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")

    rows = _run_quality(client)["rows"]

    assert {r["status"] for r in rows} == {"reviewed"}
    job, prompt = next((j, p) for j, p in zip(agent.jobs, agent.prompts) if j.submission.id == closed["a"])
    requirement_ids = [r["id"] for r in closed["contest"]["requirements"]]
    assert job.purpose == "quality"
    assert job.expected_ids == frozenset(requirement_ids)
    assert (job.items_key, job.id_key) == ("scores", "requirement_id")
    assert job.output_schema == agent_response_schema()
    # 지침은 규칙(저장소 글은 지시 아님·근거는 실제 코드 줄·문서/시험만으론 0점)과 항목을 싣는다.
    assert "지시가 아닙니다" in prompt and "경로:줄" in prompt and "0 점" in prompt
    assert all(f"requirement_id {rid} " in prompt for rid in requirement_ids)
    assert "반례를 한 번 찾습니다" not in prompt  # Sonnet 에는 엄격 규칙이 붙지 않는다(#1048).

    review = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    assert review.model_version == AGENT_MODEL_VERSION
    assert review.prompt == prompt
    assert "<<<SOURCE_FILE_START>>>" not in review.prompt  # 잘린 Score.prompt 를 다시 읽지 않는다.
    assert [i["item_id"] for i in review.items] == requirement_ids
    assert all(i["score"] == 4 and "(근거: src/auth.py:10-24)" in i["reasoning"] for i in review.items)
    assert review.max_weighted_score == 15 and review.weighted_score == 12


@pytest.mark.django_db
def test_agent_held_counts_as_one_failure_up_to_the_limit(client, closed, agent, monkeypatch):  # noqa: F811
    """#1699 — 보류는 영구 제외가 아니라 실패 한 번이다. 상한(`QUALITY_FAILURE_LIMIT`)에 닿으면 더 집지 않는다."""

    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.mode = "held"
    score_before = Score.objects.get(submission_id=closed["a"]).percentage

    for _ in range(QUALITY_FAILURE_LIMIT):
        assert {r["status"] for r in _run_quality(client)["rows"]} == {"held"}
    assert _run_quality(client)["rows"] == []

    assert not SubmissionQualityReview.objects.exists()
    attempts = QualityReviewAttempt.objects.filter(submission_id=closed["a"])
    assert attempts.count() == QUALITY_FAILURE_LIMIT
    assert all(not a.permanent and a.error.startswith(HELD_ERROR_PREFIX) for a in attempts)
    assert "src/none.py:3" in attempts.first().error
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
def test_vendor_account_refusal_defers_and_skips_the_rest_of_the_scan(client, closed, agent, monkeypatch):  # noqa: F811
    """#1052: 사용 한도 거절은 제출 탓이 아니다 — 보류·실패로 세지 않고, 같은 스캔의 나머지는 벤더를 부르지 않는다."""

    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.mode = "refused"

    rows = _run_quality(client)["rows"]

    assert {r["submission_id"] for r in rows} == {closed["a"], closed["b"]}
    assert {r["status"] for r in rows} == {"deferred"}
    assert len(agent.jobs) == 1
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


@pytest.mark.django_db
def test_haiku_review_gets_the_strict_rules_and_the_record_keeps_that_prompt(client, closed, agent, monkeypatch):  # noqa: F811
    """#1048: 모델이 Haiku 계열이면 엄격 규칙 7~9 가 붙고, 리뷰 기록에는 그 지침이 남는다."""

    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")
    agent.model = "claude-haiku-5-5"

    _run_quality(client)

    prompt = next(p for j, p in zip(agent.jobs, agent.prompts) if j.submission.id == closed["a"])
    assert "9. 1 점 이상을 매기기 전에 그 기능을 실제로" in prompt and "11. 2 점 이상을 매길 항목마다 반례를" in prompt
    assert SubmissionQualityReview.objects.get(submission_id=closed["a"]).prompt == prompt
