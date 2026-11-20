"""에이전트 실행 하나를 받아들이거나 보류한다(#1000) — 공모전 채점(#1000)·완성도 리뷰(#1001)와 강의실 채점·
완성도 검사(#1036)가 같이 쓴다. 두 제품이 함께 쓰므로 공유층(`core`)에 있다(ADR-0037, #1036 에서 `scoring` 에서 옮겼다).

`run_agent_job` 이 하는 일:
  1. 박제본(채점 커밋의 zip) 확보 — 부르는 쪽이 이미 쥔 것(`provided_snapshot`)이 있으면 그것, 없으면 부르는 쪽이
     준 `AgentJob.load_snapshot`(공모전: `scoring.agent_snapshot.contest_snapshot`).
  2. 실행 토큰 발급(`core.agent_run_tokens.issue_run_token`, 예산 $1) → `agent-grader` 실행(`request_run`).
  3. 스트림 해석(Claude stream-json·Codex `--json`) → **받아들이는 조건**:
     - Claude: init 도구에 Read·Grep·Glob 이 다 있고, 인증 출처가 `ANTHROPIC_API_KEY`(= 실행 토큰)다.
       Read ≥ 1, Grep·Glob ≥ 1. Codex: 명령 실행 ≥ 1.
     - 종료코드 0·시간 안·오류 결과 아님, 구조화 출력이 스키마에 맞고, 항목 id 가 `expected_ids` 와 정확히 같다.
     - `evidence_required` 인 항목마다 근거(`경로:줄`·`경로:줄-줄`, 최대 5개)가 있고 박제본에 실재한다.
  4. 어긋나면 한 번 더 돌린다. 그래도 어긋나면 `AgentRunHeld` — 부르는 쪽이 보류한다(0% 로 굳히지 않는다).

`AgentGraderBusy`·`RunTokenRefused`·`AgentGraderError`(닿지 못함)는 그대로 위로 던진다 — 재시도·보류는 부르는
쪽의 기존 흐름이 정한다. 벤더가 **계정 쪽**(사용 한도·빈도 제한·크레딧)으로 거절한 시도는 받아들이는 조건 어긋남이
아니다 — 다시 돌리지 않고 `AgentVendorRefused` 로 던진다(#1052). 부르는 쪽은 실행기 바쁨처럼 미룬다: 보류·실패로
세지 않고, 그 스캔의 나머지 제출은 벤더를 부르지 않는다(`note_scan_refusal`·`scan_refusal`). 어떤 문구를 계정
거절로 보는지는 `ACCOUNT_REFUSAL_MARKERS` 한 곳이다. 참가자 코드는 실행하지 않는다 — 박제본은 텍스트로 줄 수만 센다.

강의실(#1036)도 같은 길을 탄다 — `AgentJob.class_key` 를 주면 벤더·모델은 그 클래스의 채점 연결과 문제의 모델을
따르고, 실행 토큰의 키 출처가 그 클래스가 된다(프록시가 그 클래스 키를 붙인다). 기록의 `key_source` 는
"platform"·"class" 만 남긴다 — 키는 어디에도 남지 않는다.

계약은 이슈 #1000 의 댓글(2026-11-20)이다. `AgentJob`·`AgentJobOutcome`·`AgentRunHeld`·`run_agent_job` 의
서명을 바꾸려면 #1001 과 먼저 맞춘다.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal, TypedDict

# 실행기(`agent-grader`)의 계약은 `scoring.agent_runner` 가 `core.agent_ports` 에 등록한다(#1085) — 그 파일은 이미지가 홀로
# COPY 하는 표준 라이브러리 모듈이다(agent-grader.Dockerfile·deploy.sh 가 경로를 안다).
from core.agent_ports import RunResult, RunSpec, Vendor, agent_grader
from core.agent_refusal_alert import report_account_refusal
from core.agent_run_tokens import issue_run_token, run_usage
from core.runtime_settings_port import VENDOR_ANTHROPIC, scoring_vendor, setting_value

if TYPE_CHECKING:
    from submissions.models import Submission

#: JSON 값 — 구조화 출력·스키마는 모양을 정적으로 모른다(쓰기 전에 좁힌다).
JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None

RUN_BUDGET_USD = Decimal("1")
MAX_ATTEMPTS = 2  # 최초 + 1회 재실행
#: 시도 하나의 CLI 시간 상한(초, #1686). 실행기 상한(`agent_runner.RUN_TIMEOUT_SECONDS` 600)보다 짧게 넘긴다 —
#: Haiku+엄격 규칙 실측 최장 175초(공모전 3, 7건)의 1.7배. 이것과 부르는 쪽 HTTP 여유가 스캔 한도를 정한다.
ATTEMPT_TIMEOUT_SECONDS = 300
#: 실행기 HTTP 를 기다리는 시간 — CLI 상한 + 박제본 풀기·결과 전송 여유.
ATTEMPT_HTTP_TIMEOUT_SECONDS = ATTEMPT_TIMEOUT_SECONDS + 60


def request_run(spec: RunSpec, repo_zip: bytes, *, timeout: float) -> RunResult:
    """실행기에 실행 하나를 맡긴다 — 등록된 `scoring.agent_runner.request_run`(#1085). 시험이 이 이름을 바꿔 끼운다."""

    return agent_grader().request_run(spec, repo_zip, timeout=timeout)
#: 에이전트 한 건(재시도 포함)의 최장 — 이 일을 부르는 스캔의 워커 한도가 이보다 커야 한다.
AGENT_JOB_MAX_SECONDS = MAX_ATTEMPTS * ATTEMPT_HTTP_TIMEOUT_SECONDS
MAX_EVIDENCE = 5
STDOUT_TAIL_CHARS = 4000  # 기록(AgentRun.attempts)에 남기는 CLI stdout 꼬리
#: 근거 「경로:줄」·「경로:줄-줄」, 또는 줄 없이 「경로」(파일 전체 — 마이그레이션 SQL·작은 설정 파일). 지침은 줄을
#: 달라고 하지만 파일만 댄 근거 하나로 리뷰 전체를 보류하지 않는다(#1699). 그 파일이 박제본에 있는지는 그대로 본다.
EVIDENCE_PATTERN = r"^[^:\n]+(:[1-9][0-9]*(-[1-9][0-9]*)?)?$"
_EVIDENCE_RE = re.compile(r"^(?P<path>[^:\n]+)(?::(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?)?$")
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"  # `core.llm_scoring._OPENAI_DEFAULT_MODEL` 과 같은 값
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"  # `core.llm_scoring_anthropic.PLATFORM_DEFAULT_MODEL`
_READ_TOOLS = ("Read",)
_SEARCH_TOOLS = ("Grep", "Glob")


@dataclass(frozen=True)
class ClassKey:
    """강의실 클래스 키로 도는 실행(#1036) — 벤더는 그 클래스의 채점 연결, 모델은 문제의 채점 모델이다."""

    class_id: int
    vendor: Vendor
    model: str


@dataclass(frozen=True)
class AgentJob:
    submission: Submission  # 공모전·강의실 제출 모두(자산은 바탕 `Submission` 에 붙는다)
    purpose: Literal["scoring", "quality"]  # issue_run_token 의 purpose 로 간다
    build_prompt: Callable[[str], str]  # 모델 → 지침 전문(호출자가 준다). 모델을 정한 뒤에 부른다(#1048)
    output_schema: dict  # JSON 스키마(호출자가 만든다) — 계약 서명 그대로(#1000 댓글)
    expected_ids: frozenset[int]  # 응답 items 의 id 가 정확히 이 집합이어야 한다
    items_key: str  # 응답에서 항목 배열의 키 (채점 "verdicts", 리뷰 "items" 등)
    id_key: str  # 항목의 id 키 ("requirement_id" 등)
    evidence_required: Callable[[dict], bool]  # 이 항목에 근거 `경로:줄` 이 있어야 하나
    class_key: ClassKey | None = None  # 비면 플랫폼 키(운영 설정의 벤더·모델), 있으면 그 클래스 키(#1036)
    load_snapshot: Callable[[], Snapshot] | None = None  # 박제본을 받는 길(`provided_snapshot` 이 없을 때)


@dataclass(frozen=True)
class AgentJobOutcome:
    structured_output: dict  # 받아들인 응답
    model_version: str  # f"agent:{vendor}:{model}" — 리뷰·Score 기록에 그대로 쓴다
    record: dict  # 시도 기록 원본
    prompt: str  # CLI 에 넘긴 지침 전문 — 기록(`Score.prompt` 등)에 이것을 남긴다(#1048)


class AgentVendorRefused(Exception):
    """벤더가 계정 쪽으로 거절했다(#1052) — 제출 탓이 아니다. 다시 돌려도 같은 거절이라 재실행하지 않았다.
    부르는 쪽은 실행기 바쁨(`AgentGraderBusy`)과 같이 미룬다 — 보류도 실패 횟수도 늘리지 않는다."""

    def __init__(self, reason: str, record: dict) -> None:
        super().__init__(reason)
        self.reason = reason
        self.record = record


#: 계정 쪽 거절로 보는 문구(#1052) — 소문자로 견준다. 벤더 문구가 바뀌면 여기만 고친다. 견주는 곳은 CLI 결과의
#: 오류 본문(`ParsedRun.error_detail`)뿐이다 — 받아들인 실행·도구 실패의 stderr 는 보지 않는다.
ACCOUNT_REFUSAL_KINDS: dict[str, tuple[str, ...]] = {
    # 종류(경보 지문·태그·운영자 화면에 쓰는 이름) → 그 종류로 보는 문구
    "usage_limit": ("usage limit",),  # Anthropic 400 「You have reached your specified workspace API usage limits」(11-19 운영)
    "credit": ("credit balance is too low", "insufficient_quota"),  # Anthropic·OpenAI 크레딧 부족
    "rate_limit": ("rate_limit", "api_error_status=429"),  # Anthropic `rate_limit_error`·OpenAI `rate_limit_exceeded`
}
ACCOUNT_REFUSAL_MARKERS = tuple(marker for markers in ACCOUNT_REFUSAL_KINDS.values() for marker in markers)


def account_refusal_kind(error_detail: str) -> str | None:
    """오류 본문이 계정 쪽 거절이면 그 종류 이름(`ACCOUNT_REFUSAL_KINDS` 의 키)을, 아니면 None."""

    lowered = error_detail.lower()
    for kind, markers in ACCOUNT_REFUSAL_KINDS.items():
        if any(marker in lowered for marker in markers):
            return kind
    return None


def account_refusal(error_detail: str) -> str | None:
    """오류 본문이 계정 쪽 거절이면 그 본문을, 아니면 None. 스키마 어긋남 같은 다른 400 은 None 이다."""

    return error_detail.strip() if account_refusal_kind(error_detail) is not None else None


#: 스캔 한 번(`core.scans` 의 ctx)에 계정 거절을 받았다는 표시 — 그 스캔의 남은 행은 벤더를 부르지 않는다.
_SCAN_REFUSAL_KEY = "agent_vendor_refused"


def note_scan_refusal(ctx: dict, exc: AgentVendorRefused) -> None:
    ctx[_SCAN_REFUSAL_KEY] = exc.reason


def scan_refusal(ctx: dict) -> str | None:
    """이번 스캔이 이미 계정 거절을 받았으면 그 사유."""

    reason = ctx.get(_SCAN_REFUSAL_KEY)
    return reason if isinstance(reason, str) else None


class AgentRunHeld(Exception):
    """두 번(최초 + 1회 재실행) 다 어긋났다 — 호출자가 보류한다. 0% 로 굳히지 않는다."""

    def __init__(self, reasons: list[str], record: dict) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.record = record


# ── 박제본 ──────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Snapshot:
    """에이전트가 읽을 저장소 zip 한 벌과 그 출처."""

    zip_bytes: bytes
    commit_sha: str | None
    asset_id: int


_provided: ContextVar[tuple[int, Snapshot] | None] = ContextVar("agent_scoring_snapshot", default=None)


@contextmanager
def provided_snapshot(submission_id: int, snapshot: Snapshot) -> Iterator[None]:
    """부르는 쪽이 이미 받은 박제본을 넘긴다 — 같은 zip 을 GitHub 에서 두 번 받지 않는다(채점 경로)."""

    token = _provided.set((submission_id, snapshot))
    try:
        yield
    finally:
        _provided.reset(token)


class SnapshotUnavailable(Exception):
    """에이전트에게 줄 박제본이 없다 — 저장소 자산도 zip 소스 자료도 없다."""


class _LineIndex:
    """박제본 안 파일의 줄 수 — 근거 `경로:줄` 이 실재하는지 본다. 파일은 물을 때만 센다."""

    def __init__(self, zip_bytes: bytes) -> None:
        self._zip = zipfile.ZipFile(io.BytesIO(zip_bytes))
        self._names = {
            str(PurePosixPath(info.filename.removeprefix("./"))): info
            for info in self._zip.infolist()
            if not info.is_dir()
        }
        self._counts: dict[str, int] = {}

    def line_count(self, prefix: str, path: str) -> int | None:
        rel = PurePosixPath(path.strip().lstrip("/").removeprefix("./"))
        if any(part in ("..", "") for part in rel.parts):
            return None
        name = str(PurePosixPath(prefix, rel)) if prefix else str(rel)
        info = self._names.get(name)
        if info is None:
            return None
        if name not in self._counts:
            data = self._zip.read(info)
            self._counts[name] = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
        return self._counts[name]


def _acquire_snapshot(job: AgentJob) -> Snapshot:
    provided = _provided.get()
    if provided is not None and provided[0] == job.submission.id:
        return provided[1]
    if job.load_snapshot is None:
        raise SnapshotUnavailable("박제본을 받을 길이 없다")
    return job.load_snapshot()


# ── 스트림 해석 ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class ParsedRun:
    init_tools: list[str] | None = None
    api_key_source: str | None = None
    tool_calls: dict[str, int] = field(default_factory=dict)
    commands: int = 0
    failed_commands: int = 0
    turns: int | None = None
    is_error: bool = False
    error_detail: str = ""
    structured_output: JSON = None
    output_parse_error: str = ""
    usage: dict[str, JSON] = field(default_factory=dict)
    cost_usd: float | None = None


def _events(stdout: str) -> Iterator[dict[str, JSON]]:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def parse_claude_stream(stdout: str) -> ParsedRun:
    parsed = ParsedRun()
    result: dict[str, JSON] | None = None
    for event in _events(stdout):
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            tools = event.get("tools")
            parsed.init_tools = [str(t) for t in tools] if isinstance(tools, list) else []
            source = event.get("apiKeySource")
            parsed.api_key_source = str(source) if source is not None else None
        elif kind == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name"))
                    parsed.tool_calls[name] = parsed.tool_calls.get(name, 0) + 1
        elif kind == "result":
            result = event
    if result is None:
        parsed.is_error = True
        parsed.error_detail = "result 이벤트 없음"
        return parsed
    parsed.is_error = bool(result.get("is_error"))
    if parsed.is_error:
        # subtype 만으로는 「success 인데 오류」(API 호출 실패를 Claude Code 가 결과로 감싼 꼴, #1666)를 가를 수 없다 —
        # 벤더 상태와 결과 본문 머리를 붙인다.
        detail = [str(result.get("subtype") or "")]
        if result.get("api_error_status") is not None:
            detail.append(f"api_error_status={result.get('api_error_status')}")
        if isinstance(result.get("result"), str) and result["result"].strip():
            detail.append(result["result"].strip()[:300])
        parsed.error_detail = " ".join(d for d in detail if d)
    turns = result.get("num_turns")
    parsed.turns = turns if isinstance(turns, int) else None
    usage = result.get("usage")
    parsed.usage = usage if isinstance(usage, dict) else {}
    cost = result.get("total_cost_usd")
    parsed.cost_usd = float(cost) if isinstance(cost, int | float) else None
    parsed.structured_output = result.get("structured_output")
    return parsed


def parse_codex_stream(stdout: str) -> ParsedRun:
    parsed = ParsedRun(turns=0)
    last_message: str | None = None
    totals: dict[str, int] = {}
    for event in _events(stdout):
        kind = event.get("type")
        item = event.get("item")
        if kind == "item.completed" and isinstance(item, dict):
            if item.get("type") == "command_execution":
                parsed.commands += 1
                if item.get("exit_code") != 0:
                    parsed.failed_commands += 1
            elif item.get("type") == "agent_message":
                last_message = str(item.get("text") or "")
        elif kind == "turn.completed":
            parsed.turns = (parsed.turns or 0) + 1
            usage = event.get("usage")
            for key, value in (usage.items() if isinstance(usage, dict) else ()):
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
        elif kind in ("turn.failed", "error"):
            parsed.is_error = True
            parsed.error_detail = str(event.get("message") or event.get("error") or kind)[:300]
    parsed.tool_calls = {"command_execution": parsed.commands}
    parsed.usage = dict(totals)
    if last_message is None:
        parsed.output_parse_error = "agent_message 없음"
        return parsed
    try:
        parsed.structured_output = json.loads(last_message)
    except ValueError as exc:
        parsed.output_parse_error = f"최종 메시지가 JSON 이 아니다: {exc}"
    return parsed


# ── 스키마 검사(쓰는 부분만: object·array·string·integer·boolean·number, required·additionalProperties·
#    properties·items·maxItems·minItems·pattern·minimum·maximum·enum) ─────────────────────────────────────────


def schema_errors(value: JSON, schema: Mapping[str, object], where: str = "$") -> list[str]:
    errors: list[str] = []
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{where}: object 아님"]
        props = schema.get("properties")
        props = props if isinstance(props, dict) else {}
        required = schema.get("required")
        for key in required if isinstance(required, list) else []:
            if key not in value:
                errors.append(f"{where}.{key}: 없음")
        if schema.get("additionalProperties") is False:
            errors += [f"{where}.{key}: 스키마에 없는 키" for key in value if key not in props]
        for key, sub in props.items():
            if key in value and isinstance(sub, dict):
                errors += schema_errors(value[key], sub, f"{where}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            return [f"{where}: array 아님"]
        max_items, min_items = schema.get("maxItems"), schema.get("minItems")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{where}: {len(value)}개 > {max_items}")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{where}: {len(value)}개 < {min_items}")
        items = schema.get("items")
        if isinstance(items, dict):
            for i, sub_value in enumerate(value):
                errors += schema_errors(sub_value, items, f"{where}[{i}]")
    elif kind == "string":
        if not isinstance(value, str):
            return [f"{where}: string 아님"]
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and not re.search(pattern, value):
            errors.append(f"{where}: 형식 어긋남 {value[:80]!r}")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return [f"{where}: integer 아님"]
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            return [f"{where}: number 아님"]
    elif kind == "boolean":
        if not isinstance(value, bool):
            return [f"{where}: boolean 아님"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{where}: 허용값 아님")
    if kind in ("integer", "number") and isinstance(value, int | float) and not isinstance(value, bool):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        if isinstance(lo, int | float) and value < lo:
            errors.append(f"{where}: {value} < {lo}")
        if isinstance(hi, int | float) and value > hi:
            errors.append(f"{where}: {value} > {hi}")
    return errors


# ── 받아들이는 조건 ─────────────────────────────────────────────────────────────────────────────────────


class EvidenceCheck(TypedDict):
    checked: int
    bad: list[str]
    missing_for: list[int]


def _check_evidence(
    items: list[dict[str, JSON]], job: AgentJob, index: _LineIndex, prefix: str
) -> EvidenceCheck:
    report = EvidenceCheck(checked=0, bad=[], missing_for=[])
    for item in items:
        if not job.evidence_required(item):
            continue
        evidence = item.get("evidence")
        refs = [e for e in evidence if isinstance(e, str)] if isinstance(evidence, list) else []
        item_id = item.get(job.id_key)
        if not refs:
            report["missing_for"].append(item_id if isinstance(item_id, int) else -1)
            continue
        for ref in refs[:MAX_EVIDENCE]:
            report["checked"] += 1
            match = _EVIDENCE_RE.match(ref.strip())
            if match is None:
                report["bad"].append(f"{item_id}:{ref[:120]}(형식)")
                continue
            lines = index.line_count(prefix, match["path"])
            if lines is None:
                report["bad"].append(f"{item_id}:{match['path'][:120]}(없음)")
                continue
            if match["start"] is None:
                continue  # 파일 전체
            start = int(match["start"])
            end = int(match["end"] or start)
            if not (start <= end <= lines):
                report["bad"].append(f"{item_id}:{ref[:120]}(>{lines})")
    return report


def acceptance_problems(
    *, vendor: Vendor, result: RunResult, parsed: ParsedRun, job: AgentJob, index: _LineIndex
) -> tuple[list[str], EvidenceCheck | None]:
    """받아들이지 못할 이유들. 빈 목록이면 받아들인다."""

    problems: list[str] = []
    if vendor == VENDOR_ANTHROPIC:
        tools = parsed.init_tools or []
        if not set(agent_grader().CLAUDE_TOOLS) <= set(tools):
            problems.append(f"도구 빠짐: init 도구 {tools}")
        if parsed.api_key_source != "ANTHROPIC_API_KEY":
            problems.append(f"인증 출처가 실행 토큰이 아님: {parsed.api_key_source}")
        if not any(parsed.tool_calls.get(t) for t in _READ_TOOLS):
            problems.append("Read 0")
        if not any(parsed.tool_calls.get(t) for t in _SEARCH_TOOLS):
            problems.append("Grep·Glob 0")
    elif parsed.commands < 1:
        problems.append("명령 실행 0")
    if result["timed_out"]:
        problems.append("시간 초과")
    if result["exit_code"] != 0:
        problems.append(f"종료코드 {result['exit_code']}")
    if parsed.is_error:
        problems.append(f"오류 결과 {parsed.error_detail}".strip())
    if parsed.output_parse_error:
        problems.append(parsed.output_parse_error)
    output = parsed.structured_output
    if not isinstance(output, dict):
        problems.append("구조화 출력 없음")
        return problems, None
    errors = schema_errors(output, job.output_schema)
    if errors:
        problems.append(f"스키마 어긋남 {len(errors)}: {errors[:3]}")
    raw_items = output.get(job.items_key)
    items = [i for i in raw_items if isinstance(i, dict)] if isinstance(raw_items, list) else []
    ids = [i.get(job.id_key) for i in items]
    int_ids = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
    if len(int_ids) != len(ids) or len(set(int_ids)) != len(int_ids) or set(int_ids) != job.expected_ids:
        missing = sorted(job.expected_ids - set(int_ids))
        extra = sorted(set(int_ids) - job.expected_ids)
        problems.append(f"id 어긋남: 빠짐 {missing} 남음 {extra} 받은 {len(ids)}")
    evidence = _check_evidence(items, job, index, result["repo_root_prefix"])
    if evidence["missing_for"]:
        problems.append(f"근거 없음: {evidence['missing_for']}")
    if evidence["bad"]:
        problems.append(f"근거 실재 안 함 {len(evidence['bad'])}: {evidence['bad'][:5]}")
    return problems, evidence


# ── 실행 ────────────────────────────────────────────────────────────────────────────────────────────────


def agent_model(vendor: Vendor) -> str:
    """채점 모델 설정 그대로(#994) — 에이전트도 단일 호출과 같은 모델을 쓴다."""

    if vendor == VENDOR_ANTHROPIC:
        return setting_value("LLM_ANTHROPIC_MODEL") or _ANTHROPIC_DEFAULT_MODEL
    return setting_value("LLM_OPENAI_MODEL") or _OPENAI_DEFAULT_MODEL


def _attempt(job: AgentJob, *, vendor: Vendor, model: str, prompt: str, snapshot: Snapshot, index: _LineIndex) -> tuple[list[str], dict[str, JSON], JSON]:
    issued = issue_run_token(
        submission_id=job.submission.id,
        purpose=job.purpose,
        vendor=vendor,
        model=model,
        budget_usd=RUN_BUDGET_USD,
        key_class_id=job.class_key.class_id if job.class_key is not None else None,
    )
    spec = RunSpec(
        vendor=vendor,
        model=model,
        prompt=prompt,
        output_schema=job.output_schema,
        run_token=issued.token,
        max_budget_usd=float(RUN_BUDGET_USD),
        timeout_seconds=ATTEMPT_TIMEOUT_SECONDS,
    )
    result = request_run(spec, snapshot.zip_bytes, timeout=ATTEMPT_HTTP_TIMEOUT_SECONDS)
    parsed = parse_claude_stream(result["stdout"]) if vendor == VENDOR_ANTHROPIC else parse_codex_stream(result["stdout"])
    problems, evidence = acceptance_problems(vendor=vendor, result=result, parsed=parsed, job=job, index=index)
    usage = run_usage(issued.record_id)
    record: dict[str, JSON] = {
        "run_id": result["run_id"],
        "cli_version": result["cli_version"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "duration_seconds": result["duration_seconds"],
        "stdout_truncated": result["stdout_truncated"],
        "stderr_tail": result["stderr_tail"][-2000:],
        # CLI 는 오류도 stdout(stream-json)에 낸다 — stderr 가 빈 채 실패하면 이것만이 단서다(#1666).
        "stdout_tail": result["stdout"][-STDOUT_TAIL_CHARS:],
        "init_tools": list(parsed.init_tools) if parsed.init_tools is not None else None,
        "api_key_source": parsed.api_key_source,
        "tool_calls": dict(parsed.tool_calls),
        "failed_commands": parsed.failed_commands,
        "turns": parsed.turns,
        "cli_usage": parsed.usage,
        "cli_cost_usd": parsed.cost_usd,
        "proxy_usage": {
            "request_count": usage.request_count,
            "input_tokens": usage.usage.input_tokens,
            "output_tokens": usage.usage.output_tokens,
            "cache_read_tokens": usage.usage.cache_read_tokens,
            "cache_write_tokens": usage.usage.cache_write_tokens,
            "spent_usd": str(usage.spent_usd),
        },
        "evidence_check": dict(evidence) if evidence is not None else None,
        "structured_output": parsed.structured_output,
        "problems": list(problems),
        # 계정 쪽 거절이면 그 본문(#1052) — `run_agent_job` 이 재실행하지 않고 미룸으로 던진다.
        "account_refusal": account_refusal(parsed.error_detail) if problems and parsed.error_detail else None,
    }
    return problems, record, parsed.structured_output


def _budget_spent(attempt: JSON) -> bool:
    """프록시가 센 이 시도의 비용이 실행 예산에 닿았는가."""

    usage = attempt.get("proxy_usage") if isinstance(attempt, dict) else None
    spent = usage.get("spent_usd") if isinstance(usage, dict) else None
    try:
        return spent is not None and Decimal(str(spent)) >= RUN_BUDGET_USD
    except ArithmeticError:
        return False


def run_agent_job(job: AgentJob) -> AgentJobOutcome:
    if job.class_key is not None:
        vendor, model = job.class_key.vendor, job.class_key.model
    else:
        vendor = scoring_vendor()
        model = agent_model(vendor)
    prompt = job.build_prompt(model)
    record: dict[str, JSON] = {
        "purpose": job.purpose,
        "vendor": vendor,
        "model": model,
        "key_source": "class" if job.class_key is not None else "platform",
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "attempts": [],
    }
    try:
        snapshot = _acquire_snapshot(job)
    except SnapshotUnavailable as exc:
        raise AgentRunHeld([f"박제본 없음: {exc}"], record) from exc
    record["commit_sha"] = snapshot.commit_sha
    record["asset_id"] = snapshot.asset_id
    index = _LineIndex(snapshot.zip_bytes)
    attempts: list[JSON] = []
    record["attempts"] = attempts
    problems: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        try:
            problems, attempt, output = _attempt(job, vendor=vendor, model=model, prompt=prompt, snapshot=snapshot, index=index)
        except agent_grader().RunRejected as exc:
            # 실행 전에 거절됐다(박제본이 너무 크다 등) — 다시 보내도 같다.
            attempts.append({"rejected": exc.reason})
            raise AgentRunHeld([f"실행 거절: {exc.reason}"], record) from exc
        attempts.append(attempt)
        refusal = attempt.get("account_refusal")
        if isinstance(refusal, str):
            # 벤더 계정 쪽 거절(#1052) — 제출 탓이 아니고 다시 돌려도 같다. 받아들이는 조건 어긋남으로 세지 않는다.
            record["accepted"] = False
            report_account_refusal(vendor, account_refusal_kind(refusal) or "unknown")
            raise AgentVendorRefused(refusal, record)
        if not problems and isinstance(output, dict):
            record["accepted"] = True
            return AgentJobOutcome(
                structured_output=output, model_version=f"agent:{vendor}:{model}", record=record, prompt=prompt
            )
        if _budget_spent(attempt):
            # 실행 예산을 다 쓰고 끊긴 시도는 다시 돌려도 같은 길을 헤맨다 — 재실행하면 예산을 한 번 더 쓴다(#1681).
            problems = [*problems, "실행 예산 소진 — 재실행하지 않는다"]
            break
    record["accepted"] = False
    raise AgentRunHeld(problems, record)
