"""에이전트 실행 하나를 받아들이거나 보류한다(#1000) — 공모전 채점(#1000)과 완성도 리뷰(#1001)가 같이 쓴다.

`run_agent_job` 이 하는 일:
  1. 박제본(채점 커밋의 zip) 확보 — 부르는 쪽이 이미 쥔 것(`provided_snapshot`)이 있으면 그것, 없으면 저장소
     자산의 마지막 `RepositorySnapshot` 커밋(없으면 고정 커밋)을 받는다. 저장소가 없으면 zip 소스 자료.
  2. 실행 토큰 발급(`core.agent_run_tokens.issue_run_token`, 예산 $1) → `agent-grader` 실행(`request_run`).
  3. 스트림 해석(Claude stream-json·Codex `--json`) → **받아들이는 조건**:
     - Claude: init 도구에 Read·Grep·Glob 이 다 있고, 인증 출처가 `ANTHROPIC_API_KEY`(= 실행 토큰)다.
       Read ≥ 1, Grep·Glob ≥ 1. Codex: 명령 실행 ≥ 1.
     - 종료코드 0·시간 안·오류 결과 아님, 구조화 출력이 스키마에 맞고, 항목 id 가 `expected_ids` 와 정확히 같다.
     - `evidence_required` 인 항목마다 근거(`경로:줄`·`경로:줄-줄`, 최대 5개)가 있고 박제본에 실재한다.
  4. 어긋나면 한 번 더 돌린다. 그래도 어긋나면 `AgentRunHeld` — 부르는 쪽이 보류한다(0% 로 굳히지 않는다).

`AgentGraderBusy`·`RunTokenRefused`·`AgentGraderError`(닿지 못함)는 그대로 위로 던진다 — 재시도·보류는 부르는
쪽의 기존 흐름이 정한다. 참가자 코드는 실행하지 않는다 — 박제본은 텍스트로 줄 수만 센다.

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
from typing import Literal, TypedDict

from contests.models import ContestSubmission
from core.agent_run_tokens import issue_run_token, run_usage
from core.repository_adapters import get_github_adapter
from policies.runtime_settings import VENDOR_ANTHROPIC, scoring_vendor, setting_value
from repositories.models import RepositorySnapshot
from scoring.agent_runner import CLAUDE_TOOLS, RunRejected, RunResult, RunSpec, Vendor, request_run
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset
from submissions.repository_pins import clone_repository_asset

#: JSON 값 — 구조화 출력·스키마는 모양을 정적으로 모른다(쓰기 전에 좁힌다).
JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None

RUN_BUDGET_USD = Decimal("1")
MAX_ATTEMPTS = 2  # 최초 + 1회 재실행
MAX_EVIDENCE = 5
STDOUT_TAIL_CHARS = 4000  # 기록(AgentRun.attempts)에 남기는 CLI stdout 꼬리
EVIDENCE_PATTERN = r"^[^:\n]+:[1-9][0-9]*(-[1-9][0-9]*)?$"
_EVIDENCE_RE = re.compile(r"^(?P<path>[^:\n]+):(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?$")
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"  # `core.llm_scoring._OPENAI_DEFAULT_MODEL` 과 같은 값
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-5-5"  # `core.llm_scoring_anthropic.PLATFORM_DEFAULT_MODEL`
_READ_TOOLS = ("Read",)
_SEARCH_TOOLS = ("Grep", "Glob")


@dataclass(frozen=True)
class AgentJob:
    submission: ContestSubmission
    purpose: Literal["scoring", "quality"]  # issue_run_token 의 purpose 로 간다
    prompt: str  # 지침 전문(호출자가 만든다)
    output_schema: dict  # JSON 스키마(호출자가 만든다) — 계약 서명 그대로(#1000 댓글)
    expected_ids: frozenset[int]  # 응답 items 의 id 가 정확히 이 집합이어야 한다
    items_key: str  # 응답에서 항목 배열의 키 (채점 "verdicts", 리뷰 "items" 등)
    id_key: str  # 항목의 id 키 ("requirement_id" 등)
    evidence_required: Callable[[dict], bool]  # 이 항목에 근거 `경로:줄` 이 있어야 하나


@dataclass(frozen=True)
class AgentJobOutcome:
    structured_output: dict  # 받아들인 응답
    model_version: str  # f"agent:{vendor}:{model}" — 리뷰·Score 기록에 그대로 쓴다
    record: dict  # 시도 기록 원본


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


def _acquire_snapshot(submission: ContestSubmission) -> Snapshot:
    provided = _provided.get()
    if provided is not None and provided[0] == submission.id:
        return provided[1]
    repo_assets = list(
        submission.assets.filter(kind=SubmissionAsset.Kind.REPOSITORY).order_by("order", "id")
    )
    for asset in repo_assets:
        github = get_github_adapter()
        snap = RepositorySnapshot.objects.filter(asset=asset).order_by("-cloned_at").first()
        cloned = (
            github.clone(asset.value, commit_sha=snap.commit_sha)
            if snap is not None
            else clone_repository_asset(asset, github)
        )
        return Snapshot(zip_bytes=cloned.zip_bytes, commit_sha=cloned.commit_sha, asset_id=asset.id)
    storage = get_storage_adapter()
    for asset in submission.assets.filter(kind=SubmissionAsset.Kind.SOURCE).order_by("order", "id"):
        raw = storage.read_object(asset.value)
        if raw is not None and zipfile.is_zipfile(io.BytesIO(raw)):
            return Snapshot(zip_bytes=raw, commit_sha=None, asset_id=asset.id)
    raise SnapshotUnavailable("저장소 자산도 zip 소스 자료도 없다")


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
            start = int(match["start"])
            end = int(match["end"] or start)
            if lines is None:
                report["bad"].append(f"{item_id}:{match['path'][:120]}(없음)")
            elif not (start <= end <= lines):
                report["bad"].append(f"{item_id}:{ref[:120]}(>{lines})")
    return report


def acceptance_problems(
    *, vendor: Vendor, result: RunResult, parsed: ParsedRun, job: AgentJob, index: _LineIndex
) -> tuple[list[str], EvidenceCheck | None]:
    """받아들이지 못할 이유들. 빈 목록이면 받아들인다."""

    problems: list[str] = []
    if vendor == VENDOR_ANTHROPIC:
        tools = parsed.init_tools or []
        if not set(CLAUDE_TOOLS) <= set(tools):
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


def _attempt(job: AgentJob, *, vendor: Vendor, model: str, snapshot: Snapshot, index: _LineIndex) -> tuple[list[str], dict[str, JSON], JSON]:
    issued = issue_run_token(
        submission_id=job.submission.id, purpose=job.purpose, vendor=vendor, model=model, budget_usd=RUN_BUDGET_USD
    )
    spec = RunSpec(
        vendor=vendor,
        model=model,
        prompt=job.prompt,
        output_schema=job.output_schema,
        run_token=issued.token,
        max_budget_usd=float(RUN_BUDGET_USD),
    )
    result = request_run(spec, snapshot.zip_bytes)
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
    }
    return problems, record, parsed.structured_output


def run_agent_job(job: AgentJob) -> AgentJobOutcome:
    vendor: Vendor = scoring_vendor()
    model = agent_model(vendor)
    record: dict[str, JSON] = {
        "purpose": job.purpose,
        "vendor": vendor,
        "model": model,
        "prompt_sha256": hashlib.sha256(job.prompt.encode("utf-8")).hexdigest(),
        "attempts": [],
    }
    try:
        snapshot = _acquire_snapshot(job.submission)
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
            problems, attempt, output = _attempt(job, vendor=vendor, model=model, snapshot=snapshot, index=index)
        except RunRejected as exc:
            # 실행 전에 거절됐다(박제본이 너무 크다 등) — 다시 보내도 같다.
            attempts.append({"rejected": exc.reason})
            raise AgentRunHeld([f"실행 거절: {exc.reason}"], record) from exc
        attempts.append(attempt)
        if not problems and isinstance(output, dict):
            record["accepted"] = True
            return AgentJobOutcome(structured_output=output, model_version=f"agent:{vendor}:{model}", record=record)
    record["accepted"] = False
    raise AgentRunHeld(problems, record)
