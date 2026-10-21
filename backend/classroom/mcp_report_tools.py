"""연결된 앱의 참여자 리포트와 제출 소스 열기 (#518, 부모 #511, ADR-0052·ADR-0040,
CONTEXT.md 「참여자 리포트」).

**참여자 리포트**(`get_participant_report`)는 명단 격자와 문제별 제출 목록을 한 번에
접은 것이다 — 참여자마다 문제별로 통과 이력·시도 수·마지막 제출 시각·최신 시도의 판정
(체크리스트 항목별 충족과 근거)을 담는다. **숫자를 따로 세지 않는다**: 칸의 상태는 격자와
같은 `classroom.api._cell_status`, 달성률은 `_problem_pass_stats`, 통과는
`Problem.is_score_passed`, 미채점 사유는 `_pending_reason` — 화면이 쓰는 그 함수들이다.
참여자 범위도 격자와 같다(강사(소유자·공동 강사) 자리·내보낸 참여자도 표시와 함께 나온다). 소스는 담지
않고, 대신 (참여자, 문제)의 최신 제출 번호를 줘서 아래 도구로 하나씩 열게 한다.

**제출 소스 열기**(`open_submission_source`)는 제출 하나를 연다. 그 강사의 클래스에 달린
제출만 열리고, 남의 것은 「찾을 수 없다」다(번호가 있는지도 알려주지 않는다).

- **소스(zip)**: 텍스트 파일만 내용을 싣는다 — 파일당 `FILE_MAX_BYTES`, 전체
  `TOTAL_MAX_BYTES` 안에서. 넘으면 그 파일의 앞부분만(또는 내용 없이) 싣고 `truncated` 로
  잘렸다고 말한다. 바이너리(NUL 이 있거나 UTF-8 로 읽히지 않는 것)는 경로와 크기만 목록에
  남긴다. 의존성·빌드 폴더와 잠금 파일(`core.source_selection.is_excluded_path`, 채점이
  거르는 것과 같은 판정)은 `skipped` 로 목록에만 남긴다 — 내용이 예산을 먹어 사람이 쓴
  파일이 잘리지 않게. 목록은 `MAX_LISTED_FILES` 개까지다. 압축 해제는 파일마다 읽을
  만큼만 스트리밍한다(zip bomb 하나가 메모리를 먹지 않게, 채점 선별과 같은 규율).
- **저장소**: 저장소 제출은 스토리지에 아무것도 남기지 않는다 — 커밋도 박제하지 않는다
  (`classroom.scoring` 은 채점할 때 GitHub 에서 그때의 기본 브랜치를 읽는다). 그래서
  「채점 때 본 내용」의 유일한 사본은 그 시도의 `ClassroomScore.prompt` 다. 그 프롬프트의
  「제출된 소스」 구획(`classroom.scoring._build_prompt` 가 쓴 꼴 — 이미 채점 예산 안에서
  선별·절단된 텍스트)을 `TOTAL_MAX_BYTES` 안에서 돌려준다. 아직 채점되지 않았거나 플랫폼이
  채점하지 못한 시도라면 그 구획이 없어 URL 만 준다. 지금의 저장소를 서버가 다시 읽어 주지
  않는다 — 그건 채점 때 본 것이 아니고, 연결된 앱이 URL 로 직접 볼 수 있다.

**호출 상한이 따로 있다**: 소스 열기는 전체 상한(`CLASSROOM_MCP_CALLS_PER_MINUTE`) 위에
도구 자신의 분당 상한(`CLASSROOM_MCP_SOURCE_CALLS_PER_MINUTE`)을 하나 더 받는다 —
`TOOL_CALLS_PER_MINUTE_SETTINGS` 가 그 이름을 `classroom.mcp` 에 알려준다.

**둘 다 아무것도 남기지 않는다**(ADR-0040) — 처리기는 질의와 스토리지 읽기만 한다.
`tests/test_classroom_mcp_report_tools.py` 가 호출 앞뒤의 모든 테이블 행 수가 같음을 고정한다.

`mcp_read_tools` 와 같은 모양이다 — 이 모듈은 `classroom.mcp` 를 import 하지 않고 처리기와
명세만 내놓는다. 등록은 `mcp.TOOLS` 끝에 덧붙이는 쪽이 한다.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass

from ninja.errors import HttpError
from ninja.responses import NinjaJSONEncoder

from core.source_selection import is_excluded_path
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset

from .api import _active_member_ids, _cell_status, _pending_reason, _problem_pass_stats
from .contest_entries import entry_marks
from .instructor_scope import class_scope, problem_scope
from .instructors import classes_taught_by, is_instructor
from .mcp_read_tools import CONTEST_ENTRY_CELL_SCHEMA
from .models import ClassroomSubmission, ConnectedApp

#: 채점 근거 한 줄의 글자 상한 — 리포트는 클래스 전체를 한 번에 담으므로 근거가 길면
#: 참여자 수 × 문제 수 × 항목 수만큼 불어난다. 다 읽으려면 제출 하나를 연다.
REASONING_MAX_CHARS = 300

#: 소스 열기 — 파일 하나에 싣는 내용의 상한(바이트).
FILE_MAX_BYTES = 20_000
#: 소스 열기 — 응답 하나에 싣는 내용 전체의 상한(바이트). 저장소의 「채점 때 본 내용」도
#: 이 상한을 받는다.
TOTAL_MAX_BYTES = 120_000
#: 소스 열기 — 목록에 올리는 파일 수의 상한.
MAX_LISTED_FILES = 500
#: 예산이 다 떨어진 뒤에도 텍스트인지 바이너리인지는 가려 말한다 — 그 판정에 읽는 앞부분.
_SNIFF_BYTES = 1024
_MAX_UTF8_TRIM = 3

#: 도구 이름 → 그 도구 자신의 분당 상한을 담은 설정 이름(`classroom.mcp` 가 읽는다).
TOOL_CALLS_PER_MINUTE_SETTINGS = {"open_submission_source": "CLASSROOM_MCP_SOURCE_CALLS_PER_MINUTE"}

#: `classroom.scoring._build_prompt` 가 소스 앞에 쓰는 줄 — 저장소 제출의 「채점 때 본
#: 내용」은 이 줄 다음부터다.
_SCORED_SOURCE_MARKER = "\n제출된 소스:\n"


def _as_json(value):
    return json.loads(json.dumps(value, cls=NinjaJSONEncoder))


def _int_argument(arguments: dict, name: str, label: str, *, required: bool = True) -> int | None:
    value = arguments.get(name)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise HttpError(422, f"{label} 번호({name})를 정수로 주세요.")
    return value


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


# --- 참여자 리포트 ------------------------------------------------------------------


def _latest_attempt(submission: ClassroomSubmission, class_obj, problem, checklist_items) -> dict:
    score = getattr(submission, "classroom_score", None)
    latest: dict = {
        "submission_id": submission.id,
        "attempt_number": submission.attempt_number,
        "submitted_at": submission.created_at,
        "status": "scored" if score is not None else "pending",
        "passed": problem.is_score_passed(score, checklist_items=checklist_items),
        "pending_reason": _pending_reason(score, class_obj, problem),
        "met_count": None,
        "item_count": None,
        "verdicts": [],
        "syntax_check": None,
    }
    if score is None:
        return latest
    verdicts = []
    for verdict in score.reasoning:
        reasoning, cut = _clip(str(verdict.get("reasoning", "")), REASONING_MAX_CHARS)
        verdicts.append(
            {
                "checklist_item_id": verdict["checklist_item_id"],
                "is_met": bool(verdict["is_met"]),
                "reasoning": reasoning,
                "reasoning_truncated": cut,
            }
        )
    latest["verdicts"] = verdicts
    latest["met_count"] = sum(1 for v in verdicts if v["is_met"])
    latest["item_count"] = len(verdicts)
    if score.syntax_check_result is not None:
        reasoning, cut = _clip(str(score.syntax_check_result.get("reasoning", "")), REASONING_MAX_CHARS)
        latest["syntax_check"] = {
            "is_met": bool(score.syntax_check_result.get("is_met")),
            "reasoning": reasoning,
            "reasoning_truncated": cut,
        }
    return latest


def _get_participant_report(grant: ConnectedApp, arguments: dict) -> dict:
    class_id = _int_argument(arguments, "class_id", "클래스")
    problem_id = _int_argument(arguments, "problem_id", "문제", required=False)
    if problem_id is None:
        class_obj = class_scope(class_id, grant.instructor_id, write=False, owner=False).class_obj
        problems = list(class_obj.problems.prefetch_related("checklist_items").all())
    else:
        scope = problem_scope(class_id, problem_id, grant.instructor_id, write=False, owner=False)
        class_obj = scope.class_obj
        problems = list(class_obj.problems.prefetch_related("checklist_items").filter(id=problem_id))

    members = list(class_obj.members.all())
    active_member_ids = _active_member_ids(class_obj)
    checklists = {problem.id: list(problem.checklist_items.all()) for problem in problems}

    marks = entry_marks(problems)
    submissions_by_key: dict[tuple[int, int], list[ClassroomSubmission]] = {}
    for submission in (
        ClassroomSubmission.objects.filter(problem__in=problems, member__in=members)
        .select_related("classroom_score")
        .order_by("-attempt_number")
    ):
        submissions_by_key.setdefault((submission.problem_id, submission.member_id), []).append(submission)

    problem_rows = []
    for problem in problems:
        passed_count, member_count = _problem_pass_stats(problem, active_member_ids)
        problem_rows.append(
            {
                "id": problem.id,
                "title": problem.title,
                "status": problem.status,
                "order": problem.order,
                "checklist_items": [
                    {"id": item.id, "label": item.label, "required": item.required}
                    for item in checklists[problem.id]
                ],
                "passed_count": passed_count,
                "member_count": member_count,
                "pass_rate": (passed_count / member_count) if member_count else None,
            }
        )

    participant_rows = []
    for member in members:
        cells = []
        for problem in problems:
            attempts = submissions_by_key.get((problem.id, member.id), [])
            cell_status = _cell_status(attempts, class_obj, problem)
            cells.append(
                {
                    "problem_id": problem.id,
                    "status": cell_status,
                    "passed": cell_status == "passed",
                    "attempt_count": len(attempts),
                    "last_submitted_at": attempts[0].created_at if attempts else None,
                    "latest_submission_id": attempts[0].id if attempts else None,
                    "contest_entry": marks.cell(a.id for a in attempts),
                    "contest_entry_submission_id": next(
                        (a.id for a in attempts if a.id in marks.current), None
                    ),
                    "latest": (
                        _latest_attempt(attempts[0], class_obj, problem, checklists[problem.id])
                        if attempts
                        else None
                    ),
                }
            )
        participant_rows.append(
            {
                "id": member.id,
                "display_name": member.display_name,
                "is_instructor": is_instructor(class_obj, member.user_id),
                "expelled": member.expelled_at is not None,
                "problems": cells,
            }
        )

    return _as_json(
        {
            "class_id": class_obj.id,
            "class_name": class_obj.name,
            "archived": class_obj.archived_at is not None,
            "problems": problem_rows,
            "participants": participant_rows,
        }
    )


# --- 제출 소스 열기 -----------------------------------------------------------------


def _decode_text(data: bytes) -> str | None:
    """텍스트면 문자열, 바이너리면 None. 끝에서 잘린 멀티바이트 문자는 떼어 낸다
    (`core.source_selection` 과 같은 판정 — NUL 이 있으면 바이너리)."""

    if b"\x00" in data:
        return None
    for trim in range(0, _MAX_UTF8_TRIM + 1):
        chunk = data[: len(data) - trim] if trim else data
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


@dataclass
class _Budget:
    remaining: int


def _file_entry(path: str, size: int, read, budget: _Budget) -> dict:
    """파일 하나의 목록 줄. `read(n)` 은 앞에서 n 바이트까지만 읽는다."""

    entry = {"path": path, "size": size, "kind": "text", "content": None, "truncated": False}
    if is_excluded_path(path):
        entry["kind"] = "skipped"
        return entry
    allowance = min(FILE_MAX_BYTES, budget.remaining)
    try:
        data = read(max(allowance, _SNIFF_BYTES) + 1)
    except (RuntimeError, zipfile.BadZipFile, NotImplementedError, OSError):
        # 암호가 걸렸거나 지원하지 않는 압축 방식 — 내용을 읽을 수 없다.
        entry["kind"] = "binary"
        return entry
    if _decode_text(data[:_SNIFF_BYTES]) is None or _decode_text(data[:allowance]) is None:
        entry["kind"] = "binary"
        return entry
    if allowance <= 0:
        entry["truncated"] = size > 0
        return entry
    taken = data[:allowance]
    text = _decode_text(taken) or ""
    entry["content"] = text
    entry["truncated"] = len(data) > allowance or size > allowance
    budget.remaining -= len(text.encode("utf-8"))
    return entry


def _source_files(raw: bytes) -> tuple[list[dict], int]:
    budget = _Budget(remaining=TOTAL_MAX_BYTES)
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        # zip 이 아니면(파일 하나로 낸 소스) 그 하나를 파일로 본다.
        return [_file_entry("source", len(raw), lambda n: raw[:n], budget)], 1
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        # 사람이 쓴 파일부터 — 의존성·빌드 폴더는 목록 뒤로 보낸다.
        infos.sort(key=lambda info: (is_excluded_path(info.filename), info.filename))
        entries = []
        for info in infos[:MAX_LISTED_FILES]:

            def _read(n: int, *, info=info) -> bytes:
                with archive.open(info) as member:
                    return member.read(n)

            entries.append(_file_entry(info.filename, info.file_size, _read, budget))
        return entries, len(infos)


def _scored_content(submission: ClassroomSubmission) -> tuple[str | None, bool]:
    score = getattr(submission, "classroom_score", None)
    if score is None or _SCORED_SOURCE_MARKER not in score.prompt:
        return None, False
    section = score.prompt.split(_SCORED_SOURCE_MARKER, 1)[1]
    encoded = section.encode("utf-8")
    if len(encoded) <= TOTAL_MAX_BYTES:
        return section, False
    return encoded[:TOTAL_MAX_BYTES].decode("utf-8", errors="ignore"), True


def _open_submission_source(grant: ConnectedApp, arguments: dict) -> dict:
    submission_id = _int_argument(arguments, "submission_id", "제출")
    submission = (
        ClassroomSubmission.objects.filter(
            id=submission_id, problem__classroom__in=classes_taught_by(grant.instructor_id)
        )
        .select_related("problem", "member", "classroom_score")
        .first()
    )
    if submission is None:
        raise HttpError(404, "제출을 찾을 수 없습니다.")
    # 화면과 같은 문으로 한 번 더 — 소유권·존재를 `instructor_scope` 가 정한다(읽기라 보관은 보지 않는다).
    scope = problem_scope(submission.problem.classroom_id, submission.problem_id, grant.instructor_id, write=False, owner=False)
    asset = submission.assets.order_by("order", "id").first()
    if asset is None:
        raise HttpError(404, "제출을 찾을 수 없습니다.")

    result: dict = {
        "submission_id": submission.id,
        "class_id": scope.class_obj.id,
        "problem_id": scope.problem.id,
        "problem_title": scope.problem.title,
        "participant": {
            "id": submission.member.id,
            "display_name": submission.member.display_name,
            "expelled": submission.member.expelled_at is not None,
            "is_instructor": is_instructor(scope.class_obj, submission.member.user_id),
        },
        "attempt_number": submission.attempt_number,
        "submitted_at": submission.created_at,
        "submission_format": asset.kind,
        "source_found": None,
        "file_count": None,
        "files": [],
        "files_listed_truncated": False,
        "truncated": False,
        "repository_url": None,
        "commit_sha": None,
        "scored_content": None,
        "scored_content_truncated": False,
        "limits": {
            "file_max_bytes": FILE_MAX_BYTES,
            "total_max_bytes": TOTAL_MAX_BYTES,
            "max_listed_files": MAX_LISTED_FILES,
        },
    }
    if asset.kind == SubmissionAsset.Kind.SOURCE:
        raw = get_storage_adapter().read_object(asset.value)
        result["source_found"] = raw is not None
        if raw is not None:
            files, file_count = _source_files(raw)
            result["files"] = files
            result["file_count"] = file_count
            result["files_listed_truncated"] = file_count > len(files)
            result["truncated"] = result["files_listed_truncated"] or any(f["truncated"] for f in files)
    else:
        content, cut = _scored_content(submission)
        result["repository_url"] = asset.submitted_url
        result["commit_sha"] = asset.repository_commit_sha or None
        result["scored_content"] = content
        result["scored_content_truncated"] = cut
        result["truncated"] = cut
    return _as_json(result)


# --- 입력·출력 모양 ----------------------------------------------------------------

_DATETIME = {"type": "string", "description": "ISO 8601 시각"}
_NULLABLE_DATETIME = {"type": ["string", "null"], "description": "ISO 8601 시각. 없으면 null"}
_COUNT = {"type": "integer", "minimum": 0}
_NULLABLE_COUNT = {"type": ["integer", "null"], "minimum": 0}
_PROBLEM_STATUS = {
    "type": "string",
    "enum": ["draft", "open", "hidden"],
    "description": "문제 상태 — draft 초안, open 열림, hidden 숨김",
}
_CELL_STATUS = {
    "type": "string",
    "enum": ["passed", "attempted_not_passed", "scoring", "needs_setup", "not_submitted"],
    "description": (
        "통과 이력(명단 격자의 칸과 같다) — passed 한 번이라도 통과, attempted_not_passed 채점됐지만 "
        "통과 없음, scoring 채점을 기다림, needs_setup 강사가 키나 채점 모델을 손봐야 채점됨, "
        "not_submitted 시도 없음"
    ),
}
_VERDICT = {
    "type": "object",
    "properties": {
        "checklist_item_id": {"type": "integer", "description": "체크리스트 항목 번호(problems[].checklist_items 의 id)"},
        "is_met": {"type": "boolean", "description": "충족했는가"},
        "reasoning": {"type": "string", "description": f"판정 근거(최대 {REASONING_MAX_CHARS}자, 넘으면 잘린다)"},
        "reasoning_truncated": {"type": "boolean"},
    },
    "required": ["checklist_item_id", "is_met", "reasoning", "reasoning_truncated"],
}

_REPORT_OUTPUT = {
    "type": "object",
    "properties": {
        "class_id": {"type": "integer"},
        "class_name": {"type": "string"},
        "archived": {"type": "boolean", "description": "보관된 클래스인가"},
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "문제 번호"},
                    "title": {"type": "string"},
                    "status": _PROBLEM_STATUS,
                    "order": {"type": "integer"},
                    "checklist_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "integer"},
                                "label": {"type": "string"},
                                "required": {"type": "boolean", "description": "필수 항목인가 — 필수를 모두 만족해야 통과"},
                            },
                            "required": ["id", "label", "required"],
                        },
                    },
                    "passed_count": {**_COUNT, "description": "한 번이라도 통과한 참여자 수(강사(소유자·공동 강사)·내보낸 참여자 제외)"},
                    "member_count": {**_COUNT, "description": "참여자 수(강사(소유자·공동 강사)·내보낸 참여자 제외)"},
                    "pass_rate": {"type": ["number", "null"], "description": "달성률. 참여자가 없으면 null"},
                },
                "required": ["id", "title", "status", "checklist_items", "passed_count", "member_count"],
            },
        },
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "참여자 번호"},
                    "display_name": {"type": "string", "description": "이 클래스에서 불릴 이름"},
                    "is_instructor": {"type": "boolean", "description": "강사(소유자·공동 강사)가 참여자로도 들어온 자리인가 — 집계에서 빠진다"},
                    "expelled": {"type": "boolean", "description": "내보낸 참여자인가 — 기록은 남는다"},
                    "problems": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "problem_id": {"type": "integer"},
                                "status": _CELL_STATUS,
                                "passed": {"type": "boolean", "description": "한 번이라도 통과했는가"},
                                "attempt_count": {**_COUNT, "description": "시도 수"},
                                "last_submitted_at": _NULLABLE_DATETIME,
                                "latest_submission_id": {
                                    "type": ["integer", "null"],
                                    "description": "최신 시도의 제출 번호 — open_submission_source 에 넣는다",
                                },
                                "contest_entry": CONTEST_ENTRY_CELL_SCHEMA,
                                "contest_entry_submission_id": {
                                    "type": ["integer", "null"],
                                    "description": "지금 그 공모전의 제출인 시도의 제출 번호. 이 칸에 없으면 null",
                                },
                                "latest": {
                                    "type": ["object", "null"],
                                    "description": "최신 시도의 판정. 시도가 없으면 null",
                                    "properties": {
                                        "submission_id": {"type": "integer"},
                                        "attempt_number": {"type": "integer"},
                                        "submitted_at": _DATETIME,
                                        "status": {"type": "string", "enum": ["scored", "pending"]},
                                        "passed": {"type": "boolean", "description": "이 시도가 통과인가"},
                                        "pending_reason": {
                                            "type": ["string", "null"],
                                            "description": "채점을 기다리는 이유 — no_api_key·model_rejected, 없으면 null",
                                        },
                                        "met_count": {**_NULLABLE_COUNT, "description": "충족한 체크리스트 항목 수(점수). 미채점이면 null"},
                                        "item_count": {**_NULLABLE_COUNT, "description": "판정된 체크리스트 항목 수. 미채점이면 null"},
                                        "verdicts": {"type": "array", "items": _VERDICT},
                                        "syntax_check": {
                                            "type": ["object", "null"],
                                            "description": "문법 검사 판정. 꺼져 있었거나 미채점이면 null",
                                        },
                                    },
                                    "required": ["submission_id", "attempt_number", "submitted_at", "status", "passed"],
                                },
                            },
                            "required": ["problem_id", "status", "passed", "attempt_count", "latest_submission_id"],
                        },
                    },
                },
                "required": ["id", "display_name", "is_instructor", "expelled", "problems"],
            },
        },
    },
    "required": ["class_id", "class_name", "problems", "participants"],
}

_SOURCE_OUTPUT = {
    "type": "object",
    "properties": {
        "submission_id": {"type": "integer"},
        "class_id": {"type": "integer"},
        "problem_id": {"type": "integer"},
        "problem_title": {"type": "string"},
        "participant": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "display_name": {"type": "string", "description": "이 클래스에서 불릴 이름"},
                "expelled": {"type": "boolean"},
                "is_instructor": {"type": "boolean"},
            },
            "required": ["id", "display_name", "expelled", "is_instructor"],
        },
        "attempt_number": {"type": "integer"},
        "submitted_at": _DATETIME,
        "submission_format": {"type": "string", "enum": ["source", "repository"]},
        "source_found": {
            "type": ["boolean", "null"],
            "description": "소스 제출일 때만 — 스토리지에 파일이 있는가(업로드가 아직 도착하지 않았으면 거짓)",
        },
        "file_count": {**_NULLABLE_COUNT, "description": "zip 안의 파일 수(폴더 제외)"},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size": {**_COUNT, "description": "압축을 푼 크기(바이트)"},
                    "kind": {
                        "type": "string",
                        "enum": ["text", "binary", "skipped"],
                        "description": "text 내용을 싣는다, binary 목록에만, skipped 의존성·빌드 폴더나 잠금 파일이라 목록에만",
                    },
                    "content": {"type": ["string", "null"], "description": "텍스트 파일의 내용(상한 안에서)"},
                    "truncated": {"type": "boolean", "description": "상한 때문에 내용이 잘렸거나 빠졌는가"},
                },
                "required": ["path", "size", "kind", "content", "truncated"],
            },
        },
        "files_listed_truncated": {"type": "boolean", "description": "파일이 많아 목록 자체가 잘렸는가"},
        "truncated": {"type": "boolean", "description": "어느 것이든 상한 때문에 잘렸는가"},
        "repository_url": {"type": ["string", "null"], "description": "저장소 제출일 때만 — 낸 GitHub 주소 그대로(저장소·/tree/<브랜치>·/commit/<sha>)"},
        "commit_sha": {"type": ["string", "null"], "description": "저장소 제출의 고정 커밋 — 커밋 URL 이면 낸 SHA, 브랜치 URL 이면 첫 채점이 박은 SHA. 저장소 URL 제출은 null"},
        "scored_content": {
            "type": ["string", "null"],
            "description": "저장소 제출일 때만 — 채점 때 채점기가 본 소스(파일마다 「# 경로」 줄로 시작한다). 아직 채점되지 않았으면 null",
        },
        "scored_content_truncated": {"type": "boolean"},
        "limits": {
            "type": "object",
            "properties": {
                "file_max_bytes": {"type": "integer"},
                "total_max_bytes": {"type": "integer"},
                "max_listed_files": {"type": "integer"},
            },
        },
    },
    "required": ["submission_id", "class_id", "problem_id", "participant", "submission_format", "files", "truncated"],
}


REPORT_TOOL_SPECS: list[dict] = [
    {
        "name": "get_participant_report",
        "title": "참여자 리포트",
        "description": (
            "클래스 하나의 참여자 × 문제 요약 — 누가 어디서 막혔는지. 참여자마다 문제별로 통과 이력(명단 격자와 "
            "같다), 시도 수, 마지막 제출 시각, 최신 시도의 제출 번호와 판정(충족한 체크리스트 항목 수와 항목별 "
            f"근거, 근거는 {REASONING_MAX_CHARS}자까지)을 담는다. 참여자는 이 클래스에서 불릴 이름으로만 나오고 "
            "강사(소유자·공동 강사) 자리·내보낸 참여자도 표시와 함께 나온다. 소스는 담지 않는다 — 제출 번호로 "
            "open_submission_source 를 불러 연다. problem_id 를 주면 그 문제 하나만 담는다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "class_id": {"type": "integer", "description": "클래스 번호(내 클래스 목록의 id)"},
                "problem_id": {"type": "integer", "description": "문제 하나로 좁힐 때만 — 문제 번호"},
            },
            "required": ["class_id"],
            "additionalProperties": False,
        },
        "output_schema": _REPORT_OUTPUT,
        "handler": _get_participant_report,
    },
    {
        "name": "open_submission_source",
        "title": "제출 소스 열기",
        "description": (
            "제출 하나의 소스를 연다(참여자 리포트의 latest_submission_id 나 제출 번호). 소스(zip)는 텍스트 "
            f"파일의 내용을 파일당 {FILE_MAX_BYTES}바이트·전체 {TOTAL_MAX_BYTES}바이트까지 싣고, 넘으면 "
            "truncated 로 잘렸다고 표시한다. 바이너리와 의존성·빌드 폴더는 경로와 크기만 목록에 남긴다. "
            "저장소 제출은 GitHub 주소와, 채점됐다면 채점 때 채점기가 본 소스를 준다. 내 클래스의 제출만 "
            "열린다. 다른 도구보다 분당 호출 상한이 낮다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"submission_id": {"type": "integer", "description": "제출 번호"}},
            "required": ["submission_id"],
            "additionalProperties": False,
        },
        "output_schema": _SOURCE_OUTPUT,
        "handler": _open_submission_source,
    },
]
