"""강의실 판정의 세 값 — 충족·미충족·확인 불가(#811, ADR-0067).

`ClassroomScore.reasoning` 의 항목은 `is_met`(bool)을 언제나 들고, #811 뒤에 쓴 것은 `verdict` 도 든다.
옛 기록(`verdict` 없음)은 `is_met` 에서 유도한다 — **유도 규칙은 이 모듈 한 자리에만 둔다**(REST·MCP·명단이
같은 함수를 읽는다). 통과 규칙(`Problem.is_score_passed`)은 `is_met` 만 본다: 확인 불가는 충족이 아니다.
"""

from __future__ import annotations

from core.llm_scoring import VERDICT_MET, VERDICT_UNMET, VERDICT_UNVERIFIABLE, VERDICT_VALUES, RequirementVerdict

__all__ = [
    "VERDICT_MET",
    "VERDICT_UNMET",
    "VERDICT_UNVERIFIABLE",
    "VERDICT_VALUES",
    "verdict_of",
    "reasoning_entry",
]


def verdict_of(entry: dict) -> str:
    """저장된 판정 한 항목의 세 갈래 값 — `verdict` 가 있으면 그것, 없으면(옛 기록) `is_met` 에서."""

    value = entry.get("verdict")
    if value in VERDICT_VALUES:
        return value
    return VERDICT_MET if entry.get("is_met") else VERDICT_UNMET


def reasoning_entry(checklist_item_id: int, *, verdict: str, reasoning: str) -> dict:
    """`ClassroomScore.reasoning` 에 쓰는 항목 하나 — `is_met` 은 `verdict` 에서 만든다."""

    return {
        "checklist_item_id": checklist_item_id,
        "is_met": verdict == VERDICT_MET,
        "verdict": verdict,
        "reasoning": reasoning,
    }


def entry_from_model(verdict: RequirementVerdict) -> dict:
    """어댑터의 판정 → 저장 항목. 어댑터가 세 갈래를 주지 않았으면(흉내 어댑터 등) `is_met` 에서."""

    value = verdict.verdict if verdict.verdict in VERDICT_VALUES else (VERDICT_MET if verdict.is_met else VERDICT_UNMET)
    return reasoning_entry(verdict.requirement_id, verdict=value, reasoning=verdict.reasoning)
