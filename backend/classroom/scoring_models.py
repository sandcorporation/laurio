"""채점에 쓸 수 있는 OpenAI 모델과 각 모델의 컨텍스트 크기 (#285).

**모델마다 한 번에 받을 수 있는 소스의 양이 다르다.** 긴 문제에 작은 모델을
고르면 소스 뒷부분이 잘린 채 채점된다 — 그래서 선택지마다 컨텍스트 크기를
함께 보여준다(AC). 클래스 기본값(`Class.default_model`)과 문제별 값
(`Problem.model`) 둘 다 여기 있는 id 중 하나여야 하고, `is_valid_model`로
검증한다.

`scoring` 앱(공모전 가족)의 `OpenAIScoringAdapter`가 쓰는 모델 이름과 겹치는
것은 우연이 아니라 벤더가 같기 때문이다 — 다만 강의실은 그 앱을 임포트할 수
없으므로(ADR-0037) 이 카탈로그를 따로 든다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringModelChoice:
    id: str
    label: str
    #: 토큰 단위 컨텍스트 윈도.
    context_window: int


SCORING_MODEL_CHOICES: tuple[ScoringModelChoice, ...] = (
    ScoringModelChoice("gpt-4o-mini", "GPT-4o mini", 128_000),
    ScoringModelChoice("gpt-4o", "GPT-4o", 128_000),
    ScoringModelChoice("gpt-4.1-mini", "GPT-4.1 mini", 1_047_576),
    ScoringModelChoice("gpt-4.1", "GPT-4.1", 1_047_576),
)

DEFAULT_SCORING_MODEL = SCORING_MODEL_CHOICES[0].id

_BY_ID = {choice.id: choice for choice in SCORING_MODEL_CHOICES}


def is_valid_model(model_id: str) -> bool:
    return model_id in _BY_ID
