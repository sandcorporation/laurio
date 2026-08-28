"""LLM 채점 어댑터 (#12, ADR-0006, ADR-0007, ADR-0014).

PG·스토리지와 같은 원칙(ADR-0007): 실제 LLM 벤더를 인터페이스 뒤에 두고 환경별로
갈아끼운다. dev/CI는 `LLM_ADAPTER_MODE=fake`(기본값)로 `FakeLLMScoringAdapter`에
바인딩되어 네트워크 없이 결정적으로 채점 플로우 전체를 돈다. 실제 벤더 연동은 이
티켓 범위 밖이다 — `LLMScoringAdapter` 계약만 만족시키면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

from core.adapters import resolve_adapter


@dataclass(frozen=True)
class SourceFile:
    """채점 대상으로 선별된 소스 파일 하나 (scoring.source_selection)."""

    path: str
    content: str


@dataclass(frozen=True)
class RequirementInput:
    """한 Requirement에 대해 LLM이 봐야 할 전부 — 자가 응답은 참고용일 뿐 신뢰하지 않는다."""

    requirement_id: int
    text: str
    grade: str
    self_reported_met: bool
    evidence: list[dict]  # [{"kind": str, "value": str}, ...]


@dataclass(frozen=True)
class ScoringInput:
    submission_id: int
    contest_id: int
    prompt: str
    source_files: list[SourceFile]
    requirements: list[RequirementInput]


@dataclass(frozen=True)
class RequirementVerdict:
    requirement_id: int
    is_met: bool
    reasoning: str


@dataclass(frozen=True)
class ScoringOutput:
    verdicts: list[RequirementVerdict]
    model_version: str


class LLMAdapterError(Exception):
    """LLM 호출이 실패했다(타임아웃·5xx·응답 파싱 실패 등) — 재시도 대상이다.

    scoring.services.score_submission_once가 이 예외를 잡아 ScoringAttempt로
    남기고 조용히 돌아온다. Score는 만들어지지 않으므로, 다음 스캔
    (scoring.services.run_pending_scoring)이 자동으로 다시 시도한다 — 별도의
    재시도 스케줄링 코드가 필요 없다(ADR-0003과 같은 정신: 상태가 없으면 그냥
    다시 스캔하면 된다).
    """


class LLMScoringAdapter(Protocol):
    model_version: str

    def score(self, scoring_input: ScoringInput) -> ScoringOutput: ...


class FakeLLMScoringAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 채점한다.

    실제 LLM이 "Evidence가 주장을 뒷받침하는지"와 "소스에 그 기능이 실재하는지"를
    함께 읽고 판단하는 것을, 결정적인 규칙으로 흉내낸다(ADR-0014):

    1. Evidence가 하나도 연결되지 않은 자가 응답은 무조건 미달이다.
    2. Evidence가 있으면, 그 값(소스 위치·데모 경로·타임스탬프 등)이 채점 대상으로
       선별된 소스 텍스트 안에 실제로 등장하는지 본다. 등장하지 않으면 "근거를
       찾지 못했다"로 미달 처리한다.

    자가 응답(self_reported_met)은 절대 참조하지 않는다 — 이게 이 어댑터가
    증명해야 하는 핵심이다: 자가 응답만으로는 점수가 나오지 않는다.

    `settings.LLM_FAKE_RAISING_SUBMISSION_IDS`에 submission_id가 있으면
    `LLMAdapterError`를 던져 벤더 장애를 흉내낸다 — 재시도 경로 테스트용.
    """

    model_version = "fake-llm-v1"

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        if scoring_input.submission_id in settings.LLM_FAKE_RAISING_SUBMISSION_IDS:
            raise LLMAdapterError(
                f"fake LLM adapter가 submission={scoring_input.submission_id} 채점에 "
                "실패했다(설정으로 강제된 실패 시나리오)."
            )

        haystack = "\n".join(f.content for f in scoring_input.source_files)
        verdicts: list[RequirementVerdict] = []
        for requirement in scoring_input.requirements:
            grounded = any(
                evidence.get("value", "").strip()
                and evidence["value"].strip() in haystack
                for evidence in requirement.evidence
            )
            is_met = bool(requirement.evidence) and grounded
            if not requirement.evidence:
                reasoning = "Evidence가 연결되지 않아 미달로 판정했다."
            elif not grounded:
                reasoning = "연결된 Evidence의 근거를 소스에서 찾지 못해 미달로 판정했다."
            else:
                reasoning = "Evidence가 소스에서 확인되어 충족으로 판정했다."
            verdicts.append(
                RequirementVerdict(
                    requirement_id=requirement.requirement_id,
                    is_met=is_met,
                    reasoning=reasoning,
                )
            )
        return ScoringOutput(verdicts=verdicts, model_version=self.model_version)


def get_adapter() -> LLMScoringAdapter:
    return resolve_adapter(
        mode=settings.LLM_ADAPTER_MODE,
        fake_factory=FakeLLMScoringAdapter,
        not_implemented_hint=(
            "실제 LLM 연동은 아직 구현되지 않았다 — LLMScoringAdapter 계약만 만족시키는 "
            "dotted path를 LLM_ADAPTER_MODE에 설정하면 된다 (ADR-0007)."
        ),
    )
