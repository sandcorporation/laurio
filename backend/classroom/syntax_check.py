"""문법 검사 — 파서가 실행 없이 확인하는 필수 기본 항목 (#407/#408, CONTEXT.md 「문법 검사」).

모든 문제의 체크리스트 맨 앞에는 강사가 문구를 바꿀 수 없는 기본 항목
「소스에 문법 오류가 없다」가 있다(`classroom.models.Problem.syntax_check_enabled`).
이 모듈은 그 항목을 판정한다.

**제출된 코드는 절대 실행하지 않는다.** 파이썬은 파이썬 표준 파서
(`ast.parse`)로 구문 트리만 만든다 — `exec`·`eval`을 부르지 않는다.

**파싱은 격리된 서브프로세스에서, 시간 제한을 걸고 돈다.** 깊게 중첩된
입력이 CPython 파서 자체를 오래 붙들거나(극단적으로는 재귀 한도·C 스택을
건드릴 수 있다) 멈추더라도, 죽는 것은 그 자식 프로세스뿐이다 — 채점을 도는
Celery 워커 프로세스는 영향을 받지 않는다. `multiprocessing.Process`가 아니라
`subprocess.run`을 쓰는 이유는 Celery의 prefork 워커 프로세스 자신이 이미
`multiprocessing`의 데몬 자식이라, 그 안에서 또 `multiprocessing.Process`를
만들면 "daemonic processes are not allowed to have children"로 즉시 죽기
때문이다 — 평범한 `subprocess`는 이 제약 밖이다.

**파일마다 크기 상한도 있다.** `MAX_SYNTAX_CHECK_FILE_BYTES`를 넘는 파일은
아예 읽어 들이지 않고(zip 멤버를 그 바이트 수만큼만 스트리밍으로 읽는다 —
`core.source_selection`의 zip bomb 방어와 같은 원칙) 판정하지 않는다.

**대상 파일 선별은 `core.source_selection`과 같은 제외 디렉터리 규칙
(`node_modules`·`.git`·`dist` 등)을 따른다** — 참가자가 쓰지 않은 파일의
오류로 떨어지지 않게 하기 위해서다.

**이 티켓(#408)은 파이썬만 판정한다.** 크기·시간 제한에 걸렸거나 파이썬이
아닌 파일은 `unresolved`로 남을 뿐 이 모듈의 판정(`findings`)에는 영향을 주지
않는다 — 다음 티켓(#409)이 tree-sitter와 AI 판정으로 그 파일들을 마저 본다.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass

from core.source_selection import EXCLUDED_DIR_FRAGMENTS

#: 판정 기록에서 강사가 만든 체크리스트 항목(`ChecklistItem.id`, 항상 양의
#: autoincrement 값이다)과 절대 겹치지 않는 고정 식별자 — 화면·API가 이
#: 값으로 "이건 플랫폼 기본 항목이다"를 구별한다.
SYNTAX_CHECK_ITEM_ID = -1

#: 파일 하나의 크기 상한(#408 AC "크기·시간 제한에 걸린 파일이 워커를 멈추지
#: 않는다"). 이 값을 넘으면 파서가 판정하지 않는다 — 다음 티켓이 AI로 넘긴다.
MAX_SYNTAX_CHECK_FILE_BYTES = 500_000

#: 파일 하나를 파싱하는 서브프로세스에 주는 시간 상한(초). 넘기면 그 자리에서
#: 프로세스를 종료시키고 "판정 못함"으로 넘어간다 — 오류로 단정하지 않는다.
SYNTAX_CHECK_TIMEOUT_SECONDS = 5.0

#: 제출 하나에서 검사하는 파일 수 상한 — 파일 개수 자체로 워커를 오래
#: 붙드는 것을 막는 안전판이다(파일 하나하나는 이미 크기·시간 상한이 있다).
MAX_SYNTAX_CHECK_FILES = 200

PYTHON_EXTENSIONS = frozenset({".py"})


@dataclass(frozen=True)
class SyntaxCheckFinding:
    """파서가 실제로 찾은 구문 오류 하나 — 근거로 그대로 나간다."""

    path: str
    line: int | None
    message: str


@dataclass(frozen=True)
class SyntaxCheckFile:
    """파서가 판정하지 못한 파일 하나(#409가 AI에게 넘긴다) — 원문을 그대로
    들고 있는다."""

    path: str
    content: str


@dataclass(frozen=True)
class ParserSyntaxCheckOutcome:
    findings: list[SyntaxCheckFinding]
    unresolved: list[SyntaxCheckFile]

    @property
    def has_error(self) -> bool:
        return bool(self.findings)


def _is_code_path(path: str, extensions: frozenset[str]) -> bool:
    lower = path.lower()
    if any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS):
        return False
    return any(lower.endswith(ext) for ext in extensions)


def _iter_archive_files(raw: bytes, *, extensions: frozenset[str]) -> list[tuple[str, bytes | None]]:
    """`raw`(제출 아카이브)에서 대상 확장자 파일들을 골라 `(경로, 바이트|None)`
    쌍으로 돌려준다 — `None`은 크기 상한을 넘겨 통째로 읽지 않았다는 뜻이다.

    zip이 아니면 검사 대상이 없는 것으로 본다 — "아카이브의 코드 파일 전부"를
    전제하는 선별 규칙(#407)과 같은 가정이다. 참가자가 소스를 단일 파일로
    올려도(확장자를 알 수 없다) 이 함수는 후보를 내지 않는다 — 언어를 모르는
    채로 파이썬 파서를 들이대면 다른 언어 소스를 잘못 떨어뜨릴 수 있다."""

    if not raw:
        return []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return []

    results: list[tuple[str, bytes | None]] = []
    with archive:
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            if info.is_dir() or not _is_code_path(info.filename, extensions):
                continue
            # zip bomb 방어 — `core.source_selection._zip_candidates`와 같은
            # 원칙으로, 압축 해제 자체를 상한만큼만 스트리밍한다.
            with archive.open(info) as member:
                data = member.read(MAX_SYNTAX_CHECK_FILE_BYTES + 1)
            if len(data) > MAX_SYNTAX_CHECK_FILE_BYTES:
                results.append((info.filename, None))
            else:
                results.append((info.filename, data))
            if len(results) >= MAX_SYNTAX_CHECK_FILES:
                break
    return results


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


#: 자식 프로세스가 stdin으로 받은 소스를 파싱만 하고 종료한다 — `ast.parse`는
#: 구문 트리를 만들 뿐 실행하지 않는다(`exec`·`eval`을 부르지 않는다).
_PYTHON_PARSE_SCRIPT = (
    "import ast, json, sys\n"
    "src = sys.stdin.read()\n"
    "try:\n"
    "    ast.parse(src)\n"
    "except SyntaxError as exc:\n"
    "    print(json.dumps({'error': True, 'line': exc.lineno, 'message': str(exc.msg)}))\n"
    "except (ValueError, RecursionError, MemoryError) as exc:\n"
    "    print(json.dumps({'error': True, 'line': None, 'message': str(exc) or type(exc).__name__}))\n"
    "else:\n"
    "    print(json.dumps({'error': False}))\n"
)


def _parse_python_isolated(text: str, *, timeout: float) -> dict | None:
    """파이썬 표준 파서로 구문 트리만 만든다 — 코드를 실행하지 않는다.
    격리된 서브프로세스에서, 시간 제한을 걸고 돈다(모듈 docstring). 타임아웃·
    비정상 종료·응답을 못 읽은 경우 전부 `None`("판정 못함")으로 돌려준다 —
    "오류가 있다"로 단정하지 않는다."""

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _PYTHON_PARSE_SCRIPT],
            input=text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def check_python_syntax(raw: bytes) -> ParserSyntaxCheckOutcome:
    """제출 아카이브 안의 파이썬 파일 전부를 파이썬 표준 파서로 확인한다(#408) —
    코드는 실행하지 않는다. 크기·시간 제한에 걸린 파일은 `unresolved`로 남아
    이 함수의 판정(`findings`)에는 영향을 주지 않는다(#409가 AI로 넘긴다)."""

    findings: list[SyntaxCheckFinding] = []
    unresolved: list[SyntaxCheckFile] = []

    for path, data in _iter_archive_files(raw, extensions=PYTHON_EXTENSIONS):
        if data is None:
            unresolved.append(SyntaxCheckFile(path=path, content=""))
            continue
        text = _decode_utf8(data)
        if text is None:
            # 텍스트로 디코딩되지 않는 .py 파일 — 코드로 볼 수 없어 건너뛴다.
            continue
        result = _parse_python_isolated(text, timeout=SYNTAX_CHECK_TIMEOUT_SECONDS)
        if result is None:
            unresolved.append(SyntaxCheckFile(path=path, content=text))
        elif result.get("error"):
            findings.append(
                SyntaxCheckFinding(
                    path=path, line=result.get("line"), message=result.get("message") or "구문 오류"
                )
            )

    return ParserSyntaxCheckOutcome(findings=findings, unresolved=unresolved)


def build_verdict(outcome: ParserSyntaxCheckOutcome) -> dict:
    """`ClassroomScore.syntax_check_result`에 저장할 값을 만든다(#408) — 판정
    주체는 언제나 `"parser"`다(#409가 `"ai"`를 더한다). 오류가 여럿이면 첫
    오류를 근거 문장에 담고, 나머지는 개수만 덧붙인다(#407 「근거는 첫
    오류(들)의 파일 경로·줄 번호·파서 메시지」) — `findings`에는 전부 남는다."""

    if outcome.has_error:
        first = outcome.findings[0]
        location = f"{first.path}:{first.line}" if first.line is not None else first.path
        reasoning = f"{location}에서 구문 오류가 발견되었습니다 — {first.message}"
        if len(outcome.findings) > 1:
            reasoning += f" (그 외 {len(outcome.findings) - 1}개 파일에서도 오류가 발견되었습니다)"
        return {
            "is_met": False,
            "reasoning": reasoning,
            "judged_by": "parser",
            "findings": [
                {"path": f.path, "line": f.line, "message": f.message} for f in outcome.findings
            ],
        }
    return {
        "is_met": True,
        "reasoning": "파이썬 표준 파서로 구문 오류가 발견되지 않았습니다.",
        "judged_by": "parser",
        "findings": [],
    }
