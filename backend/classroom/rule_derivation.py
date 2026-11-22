"""기계 규칙 자동 도출(#1293, 스펙 #1292, CONTEXT.md 「기계 확인 완료」) — staged 채점이 체크리스트 항목 글에서
기계 확인 규칙을 스스로 도출해 둔다. 강사는 아무것도 하지 않는다.

- **언제**: staged 채점이 그 항목을 처음 만날 때, 또는 항목 글이 도출 때와 달라졌을 때(글 해시). 강사 규칙
  (`ChecklistItem.machine_rule`)이 있는 항목은 도출하지 않는다 — 강사 규칙이 먼저다. 별도 큐·작업·명령은 없다.
- **어떻게**: 도출할 항목을 모아 그 시도의 연결(강사 키)로 **한 번** 묻는다. 모델은 싼 쪽(`derivation_model`).
- **결과는 셋**: `static`(정적 꼴 규칙 — `classroom.machine_check` 의 세 꼴), `judge`(판단), `run`(빌드·시험·출력을
  봐야 함). **`run` 은 저장만 하고 판정에서는 `judge` 와 같다 — 아무것도 실행하지 않는다.**
- **꼴이 틀린 규칙은 버리고 `judge` 로 둔다**(저장 스키마 `classroom.schemas.MachineRuleIn` 으로 검증한다).
- **실패는 채점을 막지 않는다**: 벤더 오류·응답 형식 오류면 그 항목들은 이번 채점에 규칙 없이 가고, 저장하지 않으니
  다음 채점이 다시 도출한다.

벤더 호출은 채점 어댑터(`LLMScoringAdapter.score`)를 그대로 쓴다 — 항목마다 판정 하나를 받는 구조화 출력의
`reasoning` 칸에 도출 결과 JSON 을 받는다(두 걸음의 1차가 `citations` 칸으로 파일을 고르는 것과 같은 방식,
`classroom.two_step`). 그래서 OpenAI·Claude·호환 서버·흉내 어댑터·호출 지표가 채점과 같은 길을 탄다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from core.llm_scoring import RequirementInput, ScoringInput, ScoringOutput

from . import machine_check
from .schemas import MachineRuleIn, machine_rule_to_store

DerivedKind = Literal["static", "judge", "run"]
KIND_STATIC: DerivedKind = "static"
KIND_JUDGE: DerivedKind = "judge"
KIND_RUN: DerivedKind = "run"
DERIVED_KINDS: tuple[DerivedKind, ...] = (KIND_STATIC, KIND_JUDGE, KIND_RUN)

#: 도출 요청 프롬프트의 첫 줄 — 시험의 벤더 흉내가 채점 요청과 가르는 표지이기도 하다.
PROMPT_HEAD = "[기계 규칙 도출]"

#: 연결 종류별 싼 도출 모델 — 연결이 받지 않으면 그 문제의 채점 모델을 쓴다.
_CHEAP_MODELS = {
    "openai_key": "gpt-4.1-mini",
    "anthropic_key": "claude-haiku-5-5",
}

_RULE_ADAPTER: TypeAdapter[object] = TypeAdapter(MachineRuleIn)


class DerivableItem(Protocol):
    """도출이 읽는 항목의 칸 — `ChecklistItem` 이 맞는다."""

    id: int
    label: str
    machine_rule: dict | None
    derived_rule: dict | None
    derived_kind: str
    derived_text_hash: str


class _Connection(Protocol):
    kind: str

    def accepts_model_name(self, model_id: str) -> bool: ...


@dataclass(frozen=True)
class Derived:
    """항목 하나의 도출 결과 — `ChecklistItem.derived_*` 에 그대로 저장한다."""

    item_id: int
    kind: DerivedKind
    rule: machine_check.MachineRule | None
    text_hash: str
    model: str


@dataclass(frozen=True)
class Derivation:
    """한 번의 도출 호출 — 저장할 결과(실패면 빈 것)와 쓴 토큰."""

    results: tuple[Derived, ...]
    total_tokens: int = 0
    failed: bool = False
    #: 채점 방식 실험(#1295)이 비용을 단가로 셀 때 쓴다 — 도출 호출의 입력·출력 토큰과 부른 모델.
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


def label_hash(label: str) -> str:
    return hashlib.sha256(label.strip().encode("utf-8")).hexdigest()


def needs_derivation(item: DerivableItem) -> bool:
    """강사 규칙이 없고, 도출이 없거나 그 뒤 글이 바뀐 항목."""

    return not item.machine_rule and item.derived_text_hash != label_hash(item.label)


def current_rule(item: DerivableItem) -> machine_check.MachineRule | None:
    """판정에 쓸 규칙 — 강사 규칙이 먼저, 없으면 지금 글에 맞는 `static` 도출 규칙. `judge`·`run` 은 규칙 없음."""

    if item.machine_rule:
        return item.machine_rule  # type: ignore[return-value]  # 저장 스키마가 검증한 dict
    if item.derived_kind == KIND_STATIC and item.derived_rule and item.derived_text_hash == label_hash(item.label):
        return item.derived_rule  # type: ignore[return-value]  # 이 모듈이 검증해 저장한 dict
    return None


def current_derivation(item: DerivableItem) -> tuple[str, dict | None] | None:
    """강사 응답에 싣는 도출(종류, 규칙) — 도출이 없거나 그 뒤 글이 바뀌었으면 None."""

    if not item.derived_kind or item.derived_text_hash != label_hash(item.label):
        return None
    return item.derived_kind, item.derived_rule


def derivation_model(connection: _Connection, fallback: str) -> str:
    cheap = _CHEAP_MODELS.get(str(connection.kind))
    if cheap and connection.accepts_model_name(cheap):
        return cheap
    return fallback


def build_input(items: Sequence[DerivableItem], *, submission_id: int, problem_id: int) -> ScoringInput:
    lines = "\n".join(f"- id {item.id}: {item.label}" for item in items)
    prompt = f"""{PROMPT_HEAD}
아래는 코딩 과제의 체크리스트 항목이다. 소스는 주지 않는다. 항목마다 판정을 하나 내되, verdict 는 "met" 으로
두고 reasoning 에 아래 JSON 한 줄만 쓴다.

{{"kind": "static" | "judge" | "run", "rule": 규칙 또는 null}}

- static: 파일 경로·파일 안의 문자열·설정값만 보면 확인되는 항목. rule 은 다음 셋 가운데 하나다.
  {{"kind": "path_exists", "path": "<경로 glob>"}}
  {{"kind": "file_contains", "path": "<경로 glob>", "text": "<고정 문자열>"}} (text 대신 "pattern": "<정규식>" 도 된다)
  {{"kind": "config_value", "path": "<설정 파일 glob>", "key": "<점으로 이은 키>", "value": "<값>"}}
  경로 glob 의 * 는 한 조각, ** 는 여러 조각이다. 대소문자·위치가 달라도 맞도록 넓게 쓴다.
- run: 빌드·시험·실행 결과를 봐야 확인되는 항목. rule 은 null.
- judge: 코드를 읽고 판단해야 하는 항목. rule 은 null. 애매하면 judge.

항목:
{lines}
"""
    return ScoringInput(
        submission_id=submission_id,
        contest_id=problem_id,
        prompt=prompt,
        source_files=[],
        requirements=[
            RequirementInput(requirement_id=item.id, text=item.label, grade="required", self_reported_met=False)
            for item in items
        ],
    )


def parse_output(output: ScoringOutput, items: Sequence[DerivableItem], *, model: str) -> Derivation:
    """응답 → 항목별 결과. 응답에 없는 항목은 저장하지 않는다(다음 채점이 다시 묻는다). 꼴이 틀리면 `judge`."""

    by_id = {v.requirement_id: v.reasoning for v in output.verdicts}
    results = []
    for item in items:
        if item.id not in by_id:
            continue
        kind, rule = _parse_one(by_id[item.id])
        results.append(Derived(item_id=item.id, kind=kind, rule=rule, text_hash=label_hash(item.label), model=model))
    return Derivation(
        results=tuple(results),
        total_tokens=output.total_tokens,
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
        model=model,
    )


def _parse_one(text: str) -> tuple[DerivedKind, machine_check.MachineRule | None]:
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return KIND_JUDGE, None
    if not isinstance(raw, dict):
        return KIND_JUDGE, None
    kind = raw.get("kind")
    if kind == KIND_RUN:
        return KIND_RUN, None
    if kind != KIND_STATIC:
        return KIND_JUDGE, None
    try:
        validated = _RULE_ADAPTER.validate_python(raw.get("rule"))
    except ValidationError:
        return KIND_JUDGE, None
    stored = machine_rule_to_store(validated)  # type: ignore[arg-type]  # MachineRuleIn 유니언이 검증한 값
    return KIND_STATIC, stored  # type: ignore[return-value]  # 저장 dict 가 MachineRule 꼴이다
