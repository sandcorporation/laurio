"""자동 0% `Score`가 참가자와 운영자에게 서로 다른 얼굴로 보이게 하는 파생 로직
(#246, ADR-0006/0030/0031).

**여기 있는 이유 — `appeals`는 `scoring`을 import하지 않는다.** `submissions.
scored_assets`가 같은 이유로 이미 여기 있다(그 모듈의 독스트링 참고) —
재채점을 실행할 수 있는 코드 경로 자체가 없어야 한다는 것이 ADR-0006의 정적
불변식이고, `tests/test_appeals.py::test_no_rescoring_code_path_exists_in_
appeals_app`가 AST를 파싱해 그것을 고정한다. 이 모듈이 다루는 두 sentinel
문자열(`NO_SCORING_INPUT_MODEL_VERSION`·`PLATFORM_FAILURE_MODEL_VERSION`)의
원본이 `scoring.services`가 아니라 여기 사는 이유도 같다 — `scoring.services`가
이미 `submissions.models`를 그렇게 쓰고 있으므로(`scoring` → `submissions`
방향 하나만 존재한다), `scoring.services`가 이 모듈에서 값을 가져다 그대로
재노출하면 `appeals`도 `submissions`만 알면 된다.

`submissions.schemas.OwnScoreOut`(Developer용)·`appeals.schemas.
ScoreSnapshotOut`(Operator용)·`contests.schemas.AssignmentSubmissionScoreOut`
(과제 출제자용 — 과제에는 이의제기 자체가 없어 원문을 지킬 심판자가 없다)이 이
모듈을 함께 쓴다.

**청중을 구조로 가른다 — 저장된 문자열을 소독하지 않는다.** #244가 알림
발송 실패 사유에 대해 세운 것과 같은 모양이다(`notifications.api.
_recipient_facing_reason`). `Score`는 append-only라(ADR-0006) 이미 만들어진
행의 `reasoning`(ADR 번호·내부 임계값이 그대로 박힌 문구,
`scoring.services._NO_SCORING_INPUT_REASONING`·`_PLATFORM_FAILURE_REASONING`)을
고칠 방법이 없다. 그래서 참가자용 문장은 저장된 문자열을 고치는 대신
직렬화 시점에 여기서 새로 만든다.

**운영자가 보는 `ScoreSnapshotOut`은 `participant_facing_reasoning`을 거치지
않는다** — `Score.reasoning` 원문을 그대로 낸다. ADR-0030(참가자 귀책)과
ADR-0031(플랫폼 귀책)을 정확히 구별해야 하는 이의 심판에서 그 원문이 감사
기록이기 때문이다. **둘은 다른 사실을 말하는 게 아니다** — 어느 쪽이든 "AI가
판정하지 않았다"와 "누가 책임인가"라는 같은 사실이다. 참가자 쪽은 그 사실을
문서 참조 없이 한 문장으로, 운영자 쪽은 감사에 필요한 원문 그대로
Requirement별로 반복해 말한다는 표현만 다르다 — 그래서 이 파일을 나누는
것은 사실의 축소가 아니라 청중에 맞춘 번역이다.
"""

from __future__ import annotations

from enum import Enum

#: ADR-0030(#218)의 자동 미달 Score가 `Score.model_version`에 남기는 값 —
#: 참가자가 통제하는 상태(소스 없음 + 저장소가 마감 시점에 도달 불가) 때문에
#: 채점할 입력이 없었다는 뜻이다. `scoring.services`가 이 값을 가져다 그대로
#: 재노출한다 — `scoring.services.NO_SCORING_INPUT_MODEL_VERSION`으로도 여전히
#: 접근할 수 있다.
NO_SCORING_INPUT_MODEL_VERSION = "platform-auto (채점 입력 없음)"

#: ADR-0031(#222)의 자동 미달 Score가 `Score.model_version`에 남기는 값 —
#: 채점이 반복 실패해 상한(5회, 마감 후 6시간)에 도달했다는 뜻이다. 책임
#: 주체가 위 값과 정반대다(참가자가 아니라 플랫폼).
PLATFORM_FAILURE_MODEL_VERSION = "platform-auto (채점 실패 상한)"


class ScoringBasis(str, Enum):
    """참가자 응답이 채점의 성격을 기계가 읽을 수 있는 값으로 말한다(#246 AC).

    `Score.model_version`의 세 가지 뜻(AI가 실제로 판정했다 / 참가자 귀책으로
    못했다 / 플랫폼 귀책으로 못했다)을 프론트가 `model_version` 문자열을 다시
    파싱해 추측하지 않도록 닫힌 값 하나로 묶는다. 값이 하나 늘면(자동 미달
    경로가 하나 더 생기면) 여기도 같이 늘고, 생성된 TS 타입도 함께 늘어
    `tsc --noEmit`이 프론트의 누락된 분기를 잡는다.
    """

    #: AI가 실제로 판정했다 — Requirement별 근거가 갈린다.
    AI_JUDGED = "ai_judged"
    #: 참가자 귀책(ADR-0030) — 채점할 입력이 없었다.
    NO_SCORING_INPUT = "no_scoring_input"
    #: 플랫폼 귀책(ADR-0031) — 채점이 반복 실패해 상한에 도달했다.
    PLATFORM_FAILURE = "platform_failure"


def scoring_basis_for(model_version: str) -> ScoringBasis:
    """`Score.model_version` 하나에서 채점의 성격을 파생한다 — 새 컬럼도 기존
    행에 대한 마이그레이션도 없다(#246 AC, ADR-0006의 append-only를 우회하지
    않는다)."""

    if model_version == NO_SCORING_INPUT_MODEL_VERSION:
        return ScoringBasis.NO_SCORING_INPUT
    if model_version == PLATFORM_FAILURE_MODEL_VERSION:
        return ScoringBasis.PLATFORM_FAILURE
    return ScoringBasis.AI_JUDGED


#: 참가자 화면에 낼 자동 0% 사유(#246 AC) — 내부 문서 참조(ADR 번호)와 내부
#: 임계값(5회, 마감 후 6시간)이 없다. 대신 무슨 일이 있었고 자기가 무엇을 할 수
#: 있는지를 말한다 — 플랫폼 귀책이면 이의를 낼 수 있다는 것까지.
_PARTICIPANT_FACING_REASONING: dict[ScoringBasis, str] = {
    ScoringBasis.NO_SCORING_INPUT: (
        "채점할 수 있는 자료가 없어 필수 요건 전체가 미달로 처리되었습니다. "
        "소스 자료를 제출하지 않았고, 지정한 저장소도 마감 시점에 접근할 수 "
        "없었습니다(비공개로 전환되었거나 삭제되었습니다)."
    ),
    ScoringBasis.PLATFORM_FAILURE: (
        "채점이 반복적으로 실패해 플랫폼이 자동으로 미달 처리했습니다. AI가 이 "
        "제출을 심사하지 않았고, 참가자의 책임이 아닙니다. 이 결과에 이의를 "
        "제기할 수 있습니다."
    ),
}


def participant_facing_reasoning(*, model_version: str, reasoning: list[dict]) -> list[dict]:
    """`OwnScoreOut.reasoning`(및 `AssignmentSubmissionScoreOut.reasoning`)이 낼 값.

    AI가 실제로 판정했으면 저장된 `reasoning`(Requirement별 근거)을 그대로
    낸다 — 감출 내부 정보가 없다. 자동 0% 둘만 새 문장으로 바꿔 **한 번만**
    담는다(#246 AC — "같은 문장이 Requirement 개수만큼 반복되지 않는다", 자동
    0%는 판정이 Requirement별로 갈리지 않기 때문이다). 반환 모양은 그대로
    `list[dict]`라 호출부 스키마의 `reasoning` 타입을 바꾸지 않는다.
    """

    basis = scoring_basis_for(model_version)
    text = _PARTICIPANT_FACING_REASONING.get(basis)
    if text is None:
        return reasoning
    return [{"requirement_id": None, "is_met": False, "reasoning": text}]
