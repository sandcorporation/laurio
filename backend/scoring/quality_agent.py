"""공모전 완성도 — 에이전트 판(#1001). `CONTEST_SCORING_METHOD=agent` 일 때 `scoring.quality` 가 부른다.

한 번 호출 판은 `Score.prompt` 의 「## Requirements」 이하(선택기가 고른 잘린 입력)를 다시 읽는다. 에이전트
판은 채점과 같은 박제본(마감 커밋 zip)을 같은 격리·같은 프록시로 읽고 항목마다 0~5 와 근거 `경로:줄` 을 낸다.

- **실행·받아들이는 조건**: `core.agent_scoring.run_agent_job`(#1000)이 채점과 같은 검사를 한다 — 도구 호출,
  종료코드, 스키마, id 집합, 근거 `경로:줄` 의 실재. 어긋나면 한 번 더 돌리고 그래도면 `AgentRunHeld` 다.
- **채점과 묶지 않는다**: 지침이 다르고(충족/미충족이 아니라 0~5), 이미 있는 Score 를 다시 매기지 않는다.
- **응답**: `core.quality_review.response_schema()` 에 항목마다 `evidence`(`경로:줄`·`경로:줄-줄`, 최대 5개)를
  더한 것. 파싱은 `parse_content` 그대로다 — 근거는 reasoning 끝에 붙여 저장 모양(`QualityItemRecord`)을 바꾸지
  않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from contests.models import ContestSubmission
from core.quality_review import QualityItemInput, QualityItemScore, parse_content
from core.quality_review_agent import (
    EVIDENCE_MAX,
    ID_KEY,
    ITEMS_KEY,
    agent_response_schema,
    build_agent_prompt,
    needs_evidence,
    with_evidence,
)

class QualityReviewHeld(Exception):
    """에이전트 실행이 두 번 다 받아들이는 조건을 어겼다(`AgentRunHeld`) — 리뷰를 보류한다. 0~5 를 지어내지 않는다.
    메시지에는 거절 사유만 담는다(응답 본문·지침을 싣지 않는다)."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons) or "받아들이는 조건 불일치")


@dataclass(frozen=True)
class AgentReview:
    prompt: str
    scores: list[QualityItemScore]
    model_version: str


def review_with_agent(submission: ContestSubmission, items: Sequence[QualityItemInput]) -> AgentReview:
    """박제본을 에이전트로 읽어 완성도를 매긴다. `AgentRunHeld` 는 `QualityReviewHeld` 로 바꿔 던지고,
    `AgentGraderBusy`·`RunTokenRefused` 는 그대로 위로 간다(보류·재시도는 `scoring.quality` 가 정한다).
    응답이 모양을 어기면 `QualityResponseError`."""

    # 기본값(single_call)에서는 실행기 쪽 모듈을 import 조차 하지 않는다.
    from core import agent_scoring

    from .agent_snapshot import contest_snapshot

    prompt = build_agent_prompt(title=submission.contest.title, items=items)
    try:
        outcome = agent_scoring.run_agent_job(
            agent_scoring.AgentJob(
                submission=submission,
                purpose="quality",
                prompt=prompt,
                output_schema=agent_response_schema(),
                expected_ids=frozenset(i.item_id for i in items),
                items_key=ITEMS_KEY,
                id_key=ID_KEY,
                evidence_required=needs_evidence,
                load_snapshot=lambda: contest_snapshot(submission),
            )
        )
    except agent_scoring.AgentRunHeld as exc:
        raise QualityReviewHeld(exc.reasons) from exc
    scores = parse_content(with_evidence(outcome.structured_output), items=items, submission_id=submission.id)
    return AgentReview(prompt=prompt, scores=scores, model_version=outcome.model_version)


__all__ = [
    "EVIDENCE_MAX",
    "ID_KEY",
    "ITEMS_KEY",
    "AgentReview",
    "with_evidence",
    "QualityReviewHeld",
    "agent_response_schema",
    "build_agent_prompt",
    "needs_evidence",
    "review_with_agent",
]
