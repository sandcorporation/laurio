"""채점에 쓸 수 있는 OpenAI 모델 — 이름 규칙·추론 모델 판정·컨텍스트 크기
(#285, #401, #402, CONTEXT.md 「채점 모델」·「추론 강도」).

**규칙에 맞는 이름만 보여준다.** `gpt-<버전>`·`-mini`·`-nano` 모양(버전은
`4o`·`4.1`·`5`·`5.4` 같은 형태)만 남기고, 날짜 스냅샷·`-chat-latest`·`-pro`·
`-codex`·`-search`·오디오/실시간/전사/TTS·이미지·임베딩·검열·별칭형 이름은
`_ID_PATTERN`에 걸리지 않아 저절로 숨는다 — 벤더가 새 이름을 낼 때마다 이
목록을 손으로 늘릴 필요가 없다(#401 Further Notes).

**GPT-5 이후 세대를 추론 모델로 본다** — 4o·4.1은 아니다. 추론 모델은 채점
호출에 `temperature` 대신 `reasoning_effort`(낮음·보통·높음)를 받는다
(`core.llm_scoring.OpenAIScoringAdapter`, #402).

`scoring` 앱(공모전 가족)의 `OpenAIScoringAdapter`가 쓰는 모델 이름과 겹치는
것은 우연이 아니라 벤더가 같기 때문이다 — 다만 강의실은 그 앱을 임포트할 수
없으므로(ADR-0037) 이 카탈로그를 따로 든다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ScoringModelChoice:
    id: str
    label: str
    #: 토큰 단위 컨텍스트 윈도 — 모르는 모델은 `None`이다(#401 AC "크기
    #: 미확인"). 소스를 고를 때는 모른다는 것을 알 수 있다는 뜻으로 착각하지
    #: 않도록 128K 기준으로 보수적으로 자른다(`core.source_selection`).
    context_window: int | None
    is_reasoning_model: bool


#: `gpt-<버전>(-mini|-nano)?` 모양만 남긴다. 버전은 `4o`(글자 o, 리터럴)이거나
#: 숫자(점 하나로 소수 하나까지, `4.1`·`5`·`5.4`·`6`)다. 날짜 스냅샷
#: (`gpt-5.4-2026-03-05`)·별칭형(`gpt-5.6-luna`)·`-chat-latest`·`-pro`·
#: `-codex`·`-search`·오디오/이미지 계열(`gpt-audio`·`gpt-image-2`)은 끝에
#: `$`로 앵커링된 이 패턴에 걸리지 않아 저절로 숨는다. `o3`·`o4-mini`·
#: `text-embedding-3-large`처럼 `gpt-`로 시작하지 않는 이름도 마찬가지다.
_ID_PATTERN = re.compile(r"^gpt-(4o|[0-9]+(?:\.[0-9]+)?)(-mini|-nano)?$")

_SIZE_LABEL = {None: "", "-mini": " mini", "-nano": " nano"}
#: 정렬용 — 같은 버전 안에서 본모델 → mini → nano 순으로 보여준다.
_SIZE_ORDER = {None: 0, "-mini": 1, "-nano": 2}

#: 아는 모델의 컨텍스트 윈도(#285가 이미 확인한 네 값 + GPT-5 계열).
#: GPT-5 계열의 400,000은 OpenAI 문서가 밝힌 값이나 실제 벤더 호출로 재확인
#: 하지 않았다 — staging 키로 `/v1/models`를 조회해도 컨텍스트 크기는 내려오지
#: 않는다(#401 Problem Statement). 표에 없는 모델은 `context_window=None`으로
#: 내려 「크기 미확인」이 뜨고, 소스 선별은 128K 기준으로 보수적으로 자른다.
_KNOWN_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "gpt-5": 400_000,
    "gpt-5.1": 400_000,
    "gpt-5.2": 400_000,
    "gpt-5.4": 400_000,
    "gpt-5.5": 400_000,
    "gpt-5-mini": 400_000,
    "gpt-5-nano": 400_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.4-nano": 400_000,
}


def _version_sort_key(version: str) -> float:
    if version == "4o":
        return 4.05  # "4.1" 바로 아래, "4" 위 — 정확한 값이 뜻있지 않아 순서만 잡는다.
    try:
        return float(version)
    except ValueError:
        return 0.0


def is_reasoning_version(version: str) -> bool:
    if version == "4o":
        return False
    try:
        return float(version) >= 5
    except ValueError:
        return False


def matches_naming_rule(model_id: str) -> bool:
    """규칙형 이름인가 — 목록에 보여줄지·저장 시점 최소 검증에 쓴다(#401)."""

    return _ID_PATTERN.match(model_id) is not None


def is_reasoning_model_id(model_id: str) -> bool:
    """GPT-5 이후 세대인가(#402) — 규칙에 맞지 않는 id는 거짓이다."""

    match = _ID_PATTERN.match(model_id)
    if match is None:
        return False
    return is_reasoning_version(match.group(1))


def parse_model_choice(model_id: str) -> ScoringModelChoice | None:
    """`model_id`가 규칙에 맞으면 `ScoringModelChoice`를, 아니면 `None`을
    돌려준다 — 벤더 목록을 거르는 자리(`build_catalog`)와 저장된 값 하나를
    보여주는 자리(폴백 목록 조립) 양쪽에서 쓴다."""

    match = _ID_PATTERN.match(model_id)
    if match is None:
        return None
    version, size = match.group(1), match.group(2)
    label = f"GPT-{version}{_SIZE_LABEL[size]}"
    return ScoringModelChoice(
        id=model_id,
        label=label,
        context_window=_KNOWN_CONTEXT_WINDOWS.get(model_id),
        is_reasoning_model=is_reasoning_version(version),
    )


def build_catalog(vendor_model_ids: Iterable[str]) -> list[ScoringModelChoice]:
    """벤더의 `/v1/models` 응답에서 규칙에 맞는 것만 걸러 화면에 보여줄 순서로
    정렬한다(#401 AC "규칙에 맞는 이름만 남기고 ... 숨긴다"). 같은 id가
    중복되면 처음 것만 남긴다."""

    choices: dict[str, ScoringModelChoice] = {}
    for model_id in vendor_model_ids:
        if model_id in choices:
            continue
        choice = parse_model_choice(model_id)
        if choice is not None:
            choices[model_id] = choice

    def sort_key(choice: ScoringModelChoice) -> tuple:
        match = _ID_PATTERN.match(choice.id)
        assert match is not None
        version, size = match.group(1), match.group(2)
        return (-_version_sort_key(version), _SIZE_ORDER[size])

    return sorted(choices.values(), key=sort_key)


#: 조회가 불가할 때(키 없음·거부·조회 실패) 쓰는 작은 목록(#401 Implementation
#: Decisions) — 기존 네 모델과, 확인된 GPT-5 계열 하나(gpt-5-mini)를 더한다.
FALLBACK_SCORING_MODEL_CHOICES: tuple[ScoringModelChoice, ...] = tuple(
    build_catalog(
        [
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-4.1-mini",
            "gpt-4.1",
            "gpt-5-mini",
        ]
    )
)
_FALLBACK_MODEL_IDS = {choice.id for choice in FALLBACK_SCORING_MODEL_CHOICES}

#: 새 클래스의 기본 채점 모델(#401 AC) — 가장 오래된 모델이 아니라 빠르고
#: 검증된 모델에서 시작한다. 기존 클래스의 저장된 값은 마이그레이션이 건드리지
#: 않는다.
DEFAULT_SCORING_MODEL = "gpt-4.1-mini"


def is_fallback_model(model_id: str) -> bool:
    return model_id in _FALLBACK_MODEL_IDS


#: 추론 강도 세 단계(#402, CONTEXT.md 「추론 강도」) — Class 기본값·Problem
#: 마다 바꾸는 값이 채점 모델과 같은 모양이다.
REASONING_EFFORT_CHOICES: tuple[tuple[str, str], ...] = (
    ("low", "낮음"),
    ("medium", "보통"),
    ("high", "높음"),
)
DEFAULT_REASONING_EFFORT = "low"
_REASONING_EFFORT_VALUES = {value for value, _label in REASONING_EFFORT_CHOICES}


def is_valid_reasoning_effort(value: str) -> bool:
    return value in _REASONING_EFFORT_VALUES
