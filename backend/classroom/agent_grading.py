"""강의실 채점·완성도 검사의 에이전트 방식(#1036, CONTEXT.md 「채점 방식」).

클래스가 「에이전트」를 고르면 판정 채점(`classroom.scoring`)과 완성도 검사(`classroom.quality`)가 한 번 호출
대신 공모전과 같은 길을 탄다: `core.agent_scoring.run_agent_job` → `agent-grader` → `llm-proxy`.

- **벤더·모델**: 벤더는 클래스의 채점 연결(OpenAI 키 → Codex, Claude 키 → Claude Code), 모델은 문제의 채점 모델
  (`Problem.effective_model`). 호환 서버 연결과 아직 확인되지 않은 벤더(지금은 OpenAI — `AGENT_VERIFIED_VENDORS`,
  #1681)는 에이전트를 고를 수 없다(`unavailable_reason`).
- **키**: 실행 토큰의 키 출처가 이 클래스다(`ClassKey`) — 프록시가 이 클래스의 키를 풀어 벤더에만 붙인다
  (`scoring_connection.agent_vendor_key`). 실행기·CLI·기록·로그에는 실행 토큰만 간다.
- **상한**: 실행당 예산은 공모전과 같다($1). 플랫폼 하루 상한에는 세지 않는다(`core.agent_run_tokens`).
- **기록**: 받아들였든 보류했든 `ClassroomAgentRun`(공모전 `AgentRun` 과 같은 꼴, 강의실 몫의 표)에 남는다. 보류는 공모전과 같은 규칙 — 두 번 다
  받아들이는 조건을 어기면 0% 로 굳히지 않고, 채점 대기에서 빼고 실패 상한에 세지 않는다
  (`AGENT_SCORING_HOLD_ERROR_PREFIX`).

박제본은 채점 준비가 이미 읽은 소스 바이트(저장소 clone zip·zip 소스)다 — zip 이 아니면 보류한다.
실행 하나가 몇 분이 걸리고 DB(실행 토큰)를 쓰므로 grader 는 이것을 자기 스레드에서 돌린다(`run_in_own_thread`).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, ParamSpec, TypeVar

from asgiref.sync import sync_to_async
from django.db import connection

from core.agent_run_tokens import RunTokenRefused
from core.llm_scoring import (
    LLMAdapterError,
    LLMAdapterPermanentError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    RequirementInput,
    RequirementVerdict,
)
from core.quality_review import QualityItemInput, QualityItemScore, parse_content

from core import agent_scoring
from core.agent_prompt import ID_KEY, ITEMS_KEY, SCORING_OUTPUT_SCHEMA, build_scoring_prompt, scoring_reasoning
from core.agent_ports import agent_grader
from core.agent_scoring import (
    AGENT_JOB_MAX_SECONDS,
    AgentVendorRefused,
    Snapshot,
    SnapshotUnavailable,
)
from core.quality_review_agent import ID_KEY as QUALITY_ID_KEY
from core.quality_review_agent import ITEMS_KEY as QUALITY_ITEMS_KEY
from core.quality_review_agent import agent_response_schema, build_agent_prompt, needs_evidence, with_evidence

from .models import Class, ClassroomAgentRun, ClassroomSubmission
from .pending_scoring import AGENT_SCORING_HOLD_ERROR_PREFIX
from .scoring_connection import agent_vendor_of

#: 에이전트를 고를 수 없는 까닭 코드 — 화면이 이 값으로 선택지를 끈다. 호환 서버는 에이전트 CLI 가 부를 수 없고,
#: `agent_vendor_unverified` 는 연결 벤더가 아직 에이전트로 확인되지 않았다(`AGENT_VERIFIED_VENDORS` 밖).
UnavailableReason = Literal["compatible_server", "agent_vendor_unverified"]

#: 에이전트 방식을 고를 수 있는 벤더 — 막는 자리는 여기 한 곳이다. Codex(OpenAI)는 운영 실측(#1681)에서 낱말 검색
#: 106건·요청 173건을 헤매다 실행당 예산에 끊겨 구조화 출력을 내지 못했고 대표가 멈췄다. 확인되면 여기에 더해 연다.
AGENT_VERIFIED_VENDORS: frozenset[str] = frozenset({"anthropic"})

Purpose = Literal["scoring", "quality"]

#: 에이전트 실행 동안의 임대 — 한 건(재시도 포함)의 최장 `AGENT_JOB_MAX_SECONDS` 에 박제본·기록 여유 2분.
#: 한 번 호출의 임대(`classroom.scoring.SCORING_LEASE`, 4분)로는 실행 중에 다른 grader 가 같은 시도를 다시
#: 집어 실행이 둘이 된다.
AGENT_LEASE = timedelta(seconds=AGENT_JOB_MAX_SECONDS + 120)


def unavailable_reason(class_obj: Class) -> UnavailableReason | None:
    """이 클래스가 「에이전트」를 고를 수 없는 까닭 — 고를 수 있으면 `None`."""

    vendor = agent_vendor_of(class_obj)
    if vendor is None:
        return "compatible_server"
    if vendor not in AGENT_VERIFIED_VENDORS:
        return "agent_vendor_unverified"
    return None


def uses_agent(class_obj: Class, purpose: Purpose) -> bool:
    """이번 채점(또는 완성도 검사)이 에이전트로 도는가 — 고른 값이 「에이전트」이고 지금 연결이 받을 때만.
    고른 뒤 연결을 호환 서버(또는 확인되지 않은 벤더)로 바꿨으면 한 번 호출로 돈다(저장된 값은 그대로 두어 화면이
    사유를 보인다)."""

    chosen = class_obj.scoring_method if purpose == "scoring" else class_obj.quality_method
    return chosen == Class.GradingMethod.AGENT and unavailable_reason(class_obj) is None


@dataclass(frozen=True)
class AgentAccepted:
    structured_output: dict
    model_version: str
    record: dict
    used_tokens: int


@dataclass(frozen=True)
class AgentHeld:
    reasons: list[str]
    record: dict


AgentResult = AgentAccepted | AgentHeld


def _class_key(class_obj: Class, model: str) -> agent_scoring.ClassKey:
    vendor = agent_vendor_of(class_obj)
    if vendor is None:  # pragma: no cover - `uses_agent` 가 먼저 거른다.
        raise LLMAdapterPermanentError("호환 서버 연결은 에이전트 방식을 쓸 수 없다.")
    return agent_scoring.ClassKey(class_id=class_obj.pk, vendor=vendor, model=model)


def snapshot_of(raw: bytes | None, asset_id: int) -> Snapshot | None:
    """채점 준비가 읽은 소스 바이트를 박제본으로 — zip(저장소 clone·zip 소스)일 때만."""

    if raw is None or not zipfile.is_zipfile(io.BytesIO(raw)):
        return None
    return Snapshot(zip_bytes=raw, commit_sha=None, asset_id=asset_id)


def _loader(snapshot: Snapshot | None) -> Callable[[], Snapshot]:
    def load() -> Snapshot:
        if snapshot is None:
            raise SnapshotUnavailable("zip 으로 읽을 수 있는 저장소·소스가 아니다")
        return snapshot

    return load


def _proxy_tokens(record: dict) -> int:
    """프록시가 센 토큰 합(입력+출력) — 클래스 사용량(`token_usage_total`)에 더한다. 시도 둘이면 둘 다."""

    total = 0
    for attempt in record.get("attempts") or []:
        usage = attempt.get("proxy_usage") if isinstance(attempt, dict) else None
        if isinstance(usage, dict):
            total += int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    return total


def _run(job: agent_scoring.AgentJob) -> AgentResult:
    """`run_agent_job` 을 돌려 받아들임/보류로 돌려준다. 실행기·토큰 쪽 실패는 강의실 어댑터 오류로 옮긴다 —
    다음 걸음(`_apply_vendor_outcome` 등)이 한 번 호출과 같은 규율로 기록한다."""

    grader = agent_grader()  # 실행기 오류 클래스는 scoring 이 등록한 실행 틀의 것이다(#1085)
    try:
        outcome = agent_scoring.run_agent_job(job)
    except agent_scoring.AgentRunHeld as held:
        return AgentHeld(reasons=list(held.reasons), record=held.record)
    except AgentVendorRefused as exc:
        # 클래스 키의 계정 쪽 거절(#1052, 사용 한도·빈도 제한·크레딧) — 참여자 탓이 아니다. 크레딧 소진(#586)과 같은
        # 자리로 보낸다: 시도 기록 없이 그 클래스의 채점을 멈추고, 다시 확인 간격마다 한 건만 다시 쳐 본다.
        raise LLMAdapterQuotaExhaustedError(f"벤더가 이 클래스 키를 계정 쪽으로 거절했다: {exc.reason}") from exc
    except grader.AgentGraderBusy as exc:
        # 실행기가 꽉 찼다 — 제출 탓이 아니다. 빈도 제한과 같은 자리(몇 번은 세지 않는다).
        raise LLMAdapterRateLimitedError(f"에이전트 실행기가 바쁘다: {exc}") from exc
    except RunTokenRefused as exc:
        # 단가를 모르는 모델 등 — 다시 해도 같다.
        raise LLMAdapterPermanentError(f"에이전트 실행 토큰을 받지 못했다: {exc}") from exc
    except grader.AgentGraderError as exc:
        raise LLMAdapterError(f"에이전트 실행기에 닿지 못했다: {exc}") from exc
    return AgentAccepted(
        structured_output=outcome.structured_output,
        model_version=outcome.model_version,
        record=outcome.record,
        used_tokens=_proxy_tokens(outcome.record),
    )


def run_scoring(
    submission: ClassroomSubmission,
    class_obj: Class,
    *,
    model: str,
    requirements: Sequence[RequirementInput],
    snapshot: Snapshot | None,
) -> AgentResult:
    return _run(
        agent_scoring.AgentJob(
            submission=submission,
            purpose="scoring",
            build_prompt=lambda m: build_scoring_prompt(list(requirements), model=m),
            output_schema=SCORING_OUTPUT_SCHEMA,
            expected_ids=frozenset(r.requirement_id for r in requirements),
            items_key=ITEMS_KEY,
            id_key=ID_KEY,
            evidence_required=lambda item: item.get("met") is True,
            class_key=_class_key(class_obj, model),
            load_snapshot=_loader(snapshot),
        )
    )


def scoring_verdicts(accepted: AgentAccepted, requirements: Sequence[RequirementInput]) -> list[RequirementVerdict]:
    """받아들인 응답 → 판정. id 집합은 `run_agent_job` 이 이미 맞춰 봤다."""

    by_id = {item[ID_KEY]: item for item in accepted.structured_output[ITEMS_KEY]}
    verdicts = []
    for r in requirements:
        item = by_id[r.requirement_id]
        met = item["met"] is True
        verdicts.append(
            RequirementVerdict(
                requirement_id=r.requirement_id,
                is_met=met,
                reasoning=scoring_reasoning(str(item["reason"]), is_met=met, evidence=[str(e) for e in item["evidence"]]),
            )
        )
    return verdicts


def run_quality(
    submission: ClassroomSubmission,
    class_obj: Class,
    *,
    model: str,
    title: str,
    items: Sequence[QualityItemInput],
    snapshot: Snapshot | None,
) -> AgentResult:
    return _run(
        agent_scoring.AgentJob(
            submission=submission,
            purpose="quality",
            build_prompt=lambda m: build_agent_prompt(title=title, items=items, model=m),
            output_schema=agent_response_schema(),
            expected_ids=frozenset(i.item_id for i in items),
            items_key=QUALITY_ITEMS_KEY,
            id_key=QUALITY_ID_KEY,
            evidence_required=needs_evidence,
            class_key=_class_key(class_obj, model),
            load_snapshot=_loader(snapshot),
        )
    )


def quality_scores(accepted: AgentAccepted, items: Sequence[QualityItemInput], *, submission_id: int) -> list[QualityItemScore]:
    return parse_content(with_evidence(accepted.structured_output), items=items, submission_id=submission_id)


def record_run(submission_id: int, purpose: Purpose, result: AgentResult, *, review: str = "") -> ClassroomAgentRun:
    """실행 기록을 남긴다 — 공모전 `AgentRun` 과 같은 꼴."""

    if isinstance(result, AgentHeld):
        return ClassroomAgentRun.objects.create(
            submission_id=submission_id,
            purpose=purpose,
            outcome=ClassroomAgentRun.Outcome.HELD,
            model_version=f"agent:{result.record.get('vendor')}:{result.record.get('model')}",
            reasons=result.reasons,
            record=result.record,
        )
    return ClassroomAgentRun.objects.create(
        submission_id=submission_id,
        purpose=purpose,
        outcome=ClassroomAgentRun.Outcome.ACCEPTED,
        model_version=result.model_version,
        review=review,
        record=result.record,
    )


def held_message(held: AgentHeld) -> str:
    return (
        f"{AGENT_SCORING_HOLD_ERROR_PREFIX} 에이전트 채점의 받아들이는 조건이 두 번 다 어긋나 보류한다: "
        + "; ".join(held.reasons)
    )


P = ParamSpec("P")
R = TypeVar("R")


async def run_in_own_thread(fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """grader 의 이벤트 루프를 막지 않도록 제 스레드에서 돌린다 — 실행 토큰을 쓰므로 그 스레드의 DB 연결은
    끝나면 닫는다(grader 의 DB 스레드 연결을 빌리지 않는다)."""

    def _call() -> R:
        try:
            return fn(*args, **kwargs)
        finally:
            connection.close()

    return await sync_to_async(_call, thread_sensitive=False)()
