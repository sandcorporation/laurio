"""#1048: 에이전트 지침의 엄격 규칙은 모델이 Haiku 계열일 때만 붙는다.

운영은 먼저 Sonnet 이다 — Sonnet(과 Haiku 가 아닌 모든 모델) 지침은 #1043 이 엄격 규칙을 뗀 뒤의 글자 그대로여야
한다. 그 글자를 sha256 으로 못 박는다. 지침을 일부러 고친 것이면 이 값을 바꾸고, 운영에서 재 본 조합인지 따로 본다.
"""

from __future__ import annotations

import hashlib

import pytest

from classroom import agent_grading
from core import agent_scoring
from core.agent_prompt import build_scoring_prompt, wants_strict_rules
from core.llm_scoring import RequirementInput
from core.quality_review import QualityItemInput
from core.quality_review_agent import build_agent_prompt

HAIKU = "claude-haiku-5-5"
NOT_HAIKU = ("claude-sonnet-5-5", "claude-sonnet-4-6", "claude-opus-4-1", "gpt-5", "gpt-4o-mini")

REQUIREMENTS = [
    RequirementInput(requirement_id=11, text="로그인할 수 있다", grade="required", self_reported_met=True),
    RequirementInput(requirement_id=12, text="글을 쓸 수 있다", grade="optional", self_reported_met=False),
]
ITEMS = [
    QualityItemInput(item_id=21, label="로그인", required=True),
    QualityItemInput(item_id=22, label="글쓰기", required=False),
]

# #1043 뒤(엄격 규칙 없음)의 지침 글자 — 위 입력으로 만든 전문의 sha256.
SCORING_SHA256 = "e384c4acf4aa90025e2063f3ac57688723a38040fc532298674fb3e0c2d5bbad"
QUALITY_SHA256 = "0f5fc859a0813151f2999d20516e18cf15175073dd033c661500e2509d5a1fb7"

SCORING_STRICT = ("8. 충족으로 판정하기 전에", "9. 기능을 수행하는 코드를 찾지 못했으면 미충족", "10. 충족으로 볼 항목마다 반례를")
QUALITY_STRICT = ("7. 1 점 이상을 매기기 전에", "8. 기능을 수행하는 코드를 찾지 못했으면 0 점", "9. 2 점 이상을 매길 항목마다 반례를")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("model", NOT_HAIKU)
def test_non_haiku_prompts_are_the_current_text_to_the_letter(model):
    assert _sha(build_scoring_prompt(REQUIREMENTS, model=model)) == SCORING_SHA256
    assert _sha(build_agent_prompt(title="게시판 만들기", items=ITEMS, model=model)) == QUALITY_SHA256


def test_haiku_prompts_get_the_strict_rules_after_the_base_rules():
    scoring = build_scoring_prompt(REQUIREMENTS, model=HAIKU)
    quality = build_agent_prompt(title="게시판 만들기", items=ITEMS, model=HAIKU)

    assert all(rule in scoring for rule in SCORING_STRICT)
    assert all(rule in quality for rule in QUALITY_STRICT)
    # 규칙은 기존 규칙 바로 뒤, 요구사항 목록 앞에 온다.
    assert scoring.index("7. 2개 requirement_id") < scoring.index(SCORING_STRICT[0]) < scoring.index("요구사항:")
    assert quality.index("6. 2개 requirement_id") < quality.index(QUALITY_STRICT[0]) < quality.index("요구사항:")
    # 엄격 규칙을 빼면 지금 글자와 같다 — 덧붙이기만 한다.
    base_scoring = build_scoring_prompt(REQUIREMENTS, model="claude-sonnet-5-5")
    assert scoring.replace(scoring[scoring.index("\n" + SCORING_STRICT[0]) : scoring.index("\n\n요구사항:")], "") == base_scoring


def test_only_the_haiku_family_is_strict():
    assert wants_strict_rules("claude-haiku-5-5") and wants_strict_rules("claude-haiku-4-5-20251001")
    assert not any(wants_strict_rules(m) for m in NOT_HAIKU)


@pytest.mark.parametrize(("model", "strict"), [(HAIKU, True), ("claude-sonnet-5-5", False)])
def test_classroom_quality_builds_the_prompt_for_the_class_model(monkeypatch, model, strict):
    """강의실 완성도 길(`agent_grading.run_quality`)도 문제의 채점 모델로 지침을 만든다. 채점 길은
    `test_classroom_agent_method` 가 실제 실행으로 본다."""

    jobs: list[agent_scoring.AgentJob] = []

    def capture(job: agent_scoring.AgentJob) -> agent_scoring.AgentJobOutcome:
        jobs.append(job)
        raise agent_scoring.AgentRunHeld(["흉내"], {})

    monkeypatch.setattr(agent_scoring, "run_agent_job", capture)
    monkeypatch.setattr(
        agent_grading, "_class_key", lambda class_obj, m: agent_scoring.ClassKey(class_id=1, vendor="anthropic", model=m)
    )

    result = agent_grading.run_quality(
        None,  # type: ignore[arg-type]  # 실행은 흉내라 제출을 읽지 않는다.
        None,  # type: ignore[arg-type]  # `_class_key` 를 바꿔 두어 클래스를 읽지 않는다.
        model=model,
        title="게시판 만들기",
        items=ITEMS,
        snapshot=None,
    )

    assert isinstance(result, agent_grading.AgentHeld)
    (job,) = jobs
    assert job.class_key is not None and job.class_key.model == model
    prompt = job.build_prompt(job.class_key.model)
    assert all(rule in prompt for rule in QUALITY_STRICT) is strict
