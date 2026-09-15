"""문법 검사 — 파서가 실행 없이 확인하는 필수 기본 항목 (#407/#408/#409,
CONTEXT.md 「문법 검사」).

모든 문제의 체크리스트 맨 앞에는 강사가 문구를 바꿀 수 없는 기본 항목
「소스에 문법 오류가 없다」가 있다(`classroom.models.Problem.syntax_check_enabled`).
이 모듈은 그 항목을 판정한다.

**제출된 코드는 절대 실행하지 않는다.** 파이썬은 파이썬 표준 파서
(`ast.parse`)로 구문 트리만, JS·TS·Java·Go·C/C++·Kotlin·Ruby는 tree-sitter로
구문 트리만 만든다 — 둘 다 `exec`·`eval`을 부르지 않는다.

**파싱은 격리된 서브프로세스에서, 시간 제한을 걸고 돈다.** 깊게 중첩된
입력이 파서 자체를 오래 붙들거나 멈추더라도, 죽는 것은 그 자식 프로세스뿐이다
— 채점을 도는 Celery 워커 프로세스는 영향을 받지 않는다. `multiprocessing.
Process`가 아니라 `subprocess.run`을 쓰는 이유는 Celery의 prefork 워커
프로세스 자신이 이미 `multiprocessing`의 데몬 자식이라, 그 안에서 또
`multiprocessing.Process`를 만들면 "daemonic processes are not allowed to
have children"로 즉시 죽기 때문이다 — 평범한 `subprocess`는 이 제약 밖이다.

**파일마다 크기 상한도 있다.** `MAX_SYNTAX_CHECK_FILE_BYTES`를 넘는 파일은
그 상한까지만 스트리밍으로 읽고(zip bomb 방어, `core.source_selection`과
같은 원칙) 파서가 판정하지 않는다 — `unresolved`로 남아 AI가 대신 본다(#409).

**대상 파일 선별은 `core.source_selection`과 같은 확장자 목록·제외 디렉터리
규칙(`node_modules`·`.git`·`dist` 등)을 따른다**(#407 「검사」 "소스 선택이
이미 쓰는 제외 규칙과 코드 확장자 목록을 따른다") — 참가자가 쓰지 않은
파일의 오류로 떨어지지 않고, 소스 선별이 코드로 보는 것과 이 검사가 보는
것이 어긋나지 않는다.

**파서가 없는 언어(위 여덟 개 밖의 코드 확장자)와 크기·시간 제한에 걸린
파일은 AI가 판정한다**(#409) — 파서가 이미 오류를 찾았으면 AI에게 묻지
않는다(`classroom.scoring`이 이 모듈의 `has_error`를 먼저 본다). AI 판정은
기존 강의실 채점 요청 안에서 이뤄지고 추가 벤더 호출을 만들지 않는다 —
이 모듈은 그 요청에 실을 재료(대상 파일 목록·프롬프트 문구)만 만든다,
실제로 요청에 싣는 것은 `classroom.scoring._build_prompt`다.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from dataclasses import dataclass

from core.source_selection import ALLOWED_EXTENSIONS, EXCLUDED_DIR_FRAGMENTS

#: 판정 기록에서 강사가 만든 체크리스트 항목(`ChecklistItem.id`, 항상 양의
#: autoincrement 값이다)과 절대 겹치지 않는 고정 식별자 — 화면·API·채점
#: 요청이 이 값으로 "이건 플랫폼 기본 항목이다"를 구별한다.
SYNTAX_CHECK_ITEM_ID = -1

#: 파일 하나의 크기 상한(#408 AC "크기·시간 제한에 걸린 파일이 워커를 멈추지
#: 않는다"). 이 값을 넘으면 파서가 판정하지 않는다 — AI가 대신 본다(#409).
MAX_SYNTAX_CHECK_FILE_BYTES = 500_000

#: 파일 하나를 파싱하는 서브프로세스에 주는 시간 상한(초). 넘기면 그 자리에서
#: 프로세스를 종료시키고 "판정 못함"으로 넘어간다 — 오류로 단정하지 않는다.
SYNTAX_CHECK_TIMEOUT_SECONDS = 5.0

#: 제출 하나에서 검사하는 파일 수 상한 — 파일 개수 자체로 워커를 오래
#: 붙드는 것을 막는 안전판이다(파일 하나하나는 이미 크기·시간 상한이 있다).
MAX_SYNTAX_CHECK_FILES = 200

#: 파서가 판정하는 코드 확장자 전부 — 소스 선택과 같은 목록
#: (`core.source_selection.ALLOWED_EXTENSIONS`)이다. 이 중 파이썬은 표준
#: 파서로, `TREE_SITTER_LANGUAGE_BY_EXTENSION`에 있는 여덟 언어는
#: tree-sitter로 확인하고, 나머지(#409 AC가 「파서가 없는 언어」라 부르는
#: .php·.rs·.swift·.cs·.m·.html·.css·.scss·.vue·.svelte·.json·.yaml·.yml·
#: .md·.sql·.sh)는 `unresolved`로 남아 AI가 본다.
ALL_SYNTAX_CHECK_EXTENSIONS = frozenset(ALLOWED_EXTENSIONS)

PYTHON_EXTENSIONS = frozenset({".py"})

#: tree-sitter-language-pack이 아는 이름으로 매핑한다(#409, #407 parent
#: "JS·TS·Java·Go·C/C++·Kotlin·Ruby 등 주요 언어"). tree-sitter-language-pack이
#: PHP·Rust 등 더 많은 문법을 지원해도, 이 티켓이 명시한 여덟 언어 밖은
#: 일부러 파서 목록에 넣지 않는다 — 범위를 스펙 그대로 못박는다.
TREE_SITTER_LANGUAGE_BY_EXTENSION: dict[str, str] = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".rb": "ruby",
}


@dataclass(frozen=True)
class SyntaxCheckFinding:
    """파서가 실제로 찾은 구문 오류 하나 — 근거로 그대로 나간다."""

    path: str
    line: int | None
    message: str


@dataclass(frozen=True)
class SyntaxCheckFile:
    """파서가 판정하지 못한 파일 하나(#409가 AI에게 넘긴다) — 원문을(크기
    상한에 걸렸으면 그 상한까지만) 그대로 들고 있는다."""

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


def _tree_sitter_language_for(lower_path: str) -> str | None:
    for ext, language in TREE_SITTER_LANGUAGE_BY_EXTENSION.items():
        if lower_path.endswith(ext):
            return language
    return None


def _iter_archive_files(
    raw: bytes, *, extensions: frozenset[str]
) -> list[tuple[str, bytes, bool]]:
    """`raw`(제출 아카이브)에서 대상 확장자 파일들을 골라 `(경로, 바이트,
    크기_초과)` 셋으로 돌려준다 — 크기 상한을 넘긴 파일도 그 상한까지 읽은
    내용을 그대로 담아 돌려준다(AI가 최소한의 내용은 볼 수 있게, #409).

    zip이 아니면 검사 대상이 없는 것으로 본다 — "아카이브의 코드 파일 전부"를
    전제하는 선별 규칙(#407)과 같은 가정이다. 참가자가 소스를 단일 파일로
    올려도(확장자를 알 수 없다) 이 함수는 후보를 내지 않는다 — 언어를 모르는
    채로 파서를 들이대면 다른 언어 소스를 잘못 떨어뜨릴 수 있다."""

    if not raw:
        return []
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return []

    results: list[tuple[str, bytes, bool]] = []
    with archive:
        for info in sorted(archive.infolist(), key=lambda i: i.filename):
            if info.is_dir() or not _is_code_path(info.filename, extensions):
                continue
            # zip bomb 방어 — `core.source_selection._zip_candidates`와 같은
            # 원칙으로, 압축 해제 자체를 상한만큼만 스트리밍한다.
            with archive.open(info) as member:
                data = member.read(MAX_SYNTAX_CHECK_FILE_BYTES + 1)
            size_exceeded = len(data) > MAX_SYNTAX_CHECK_FILE_BYTES
            content = data[:MAX_SYNTAX_CHECK_FILE_BYTES] if size_exceeded else data
            results.append((info.filename, content, size_exceeded))
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


#: tree-sitter는 오류·누락 노드를 트리에 그대로 남긴 채 계속 파싱한다(에디터용
#: 설계라 예외를 던지지 않는다) — 그래서 코드는 파일 전체가 아니라
#: `root_node.has_error`로 오류 여부를 보고, 첫 ERROR/누락 노드의 위치로 줄
#: 번호를 잡는다. 언어 이름은 인자로 받는다 — 서브프로세스 하나가 여러
#: 언어를 다 처리한다(언어마다 서브프로세스를 새로 만들 이유가 없다, 문법은
#: `tree_sitter_language_pack`이 그 자리에서 그때그때 부른다).
_TREE_SITTER_PARSE_SCRIPT = (
    "import json, sys\n"
    "from tree_sitter_language_pack import get_parser\n"
    "language = sys.argv[1]\n"
    "src = sys.stdin.buffer.read()\n"
    "parser = get_parser(language)\n"
    "tree = parser.parse(src)\n"
    "if not tree.root_node.has_error:\n"
    "    print(json.dumps({'error': False}))\n"
    "else:\n"
    "    def _find(node):\n"
    "        if node.type == 'ERROR' or node.is_missing:\n"
    "            return node\n"
    "        for child in node.children:\n"
    "            found = _find(child)\n"
    "            if found is not None:\n"
    "                return found\n"
    "        return None\n"
    "    error_node = _find(tree.root_node)\n"
    "    line = (error_node.start_point[0] + 1) if error_node is not None else None\n"
    "    print(json.dumps({'error': True, 'line': line, 'message': '구문 오류'}))\n"
)


def _parse_tree_sitter_isolated(text: str, *, language: str, timeout: float) -> dict | None:
    """tree-sitter 문법으로 구문 트리만 만든다 — 코드를 실행하지 않는다.
    `_parse_python_isolated`와 같은 격리·시간 제한 규율이다."""

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", _TREE_SITTER_PARSE_SCRIPT, language],
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


def run_parser_syntax_check(raw: bytes) -> ParserSyntaxCheckOutcome:
    """제출 아카이브 안의 코드 파일 전부를 파서로 확인한다(#408/#409) — 코드는
    실행하지 않는다. 파이썬은 표준 파서로, JS·TS·Java·Go·C/C++·Kotlin·Ruby는
    tree-sitter로 확인한다. 그 밖의 코드 확장자와 크기·시간 제한에 걸린
    파일은 `unresolved`로 남는다 — `classroom.scoring`이 그 목록을 AI 판정
    대상으로 채점 요청에 싣는다(#409)."""

    findings: list[SyntaxCheckFinding] = []
    unresolved: list[SyntaxCheckFile] = []

    for path, data, size_exceeded in _iter_archive_files(raw, extensions=ALL_SYNTAX_CHECK_EXTENSIONS):
        text = _decode_utf8(data)
        if text is None:
            # 텍스트로 디코딩되지 않는 파일 — 코드로 볼 수 없어 건너뛴다.
            continue
        if size_exceeded:
            unresolved.append(SyntaxCheckFile(path=path, content=text))
            continue

        lower = path.lower()
        if lower.endswith(".py"):
            result = _parse_python_isolated(text, timeout=SYNTAX_CHECK_TIMEOUT_SECONDS)
        else:
            language = _tree_sitter_language_for(lower)
            if language is None:
                unresolved.append(SyntaxCheckFile(path=path, content=text))
                continue
            result = _parse_tree_sitter_isolated(
                text, language=language, timeout=SYNTAX_CHECK_TIMEOUT_SECONDS
            )

        if result is None:
            unresolved.append(SyntaxCheckFile(path=path, content=text))
        elif result.get("error"):
            findings.append(
                SyntaxCheckFinding(
                    path=path, line=result.get("line"), message=result.get("message") or "구문 오류"
                )
            )

    return ParserSyntaxCheckOutcome(findings=findings, unresolved=unresolved)


def build_parser_verdict(outcome: ParserSyntaxCheckOutcome) -> dict:
    """파서만으로 끝난 판정을 `ClassroomScore.syntax_check_result`에 저장할
    값으로 만든다 — 파서가 오류를 찾았거나(`has_error`), 판정 못한 파일이
    하나도 없어 AI에게 물을 것이 없을 때만 호출한다. 오류가 여럿이면 첫
    오류를 근거 문장에 담고 나머지는 개수만 덧붙인다(#407 「근거는 첫
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
        "reasoning": "파서가 구문 오류를 발견하지 못했습니다.",
        "judged_by": "parser",
        "findings": [],
    }


#: 파이썬 표준 파서로 끝난 것과 tree-sitter로 끝난 것을 근거 문장에서 굳이
#: 가르지 않는다 — 참가자에게는 "파서가 확인했다"만 뜻이 있고, 어느 파서인지는
#: `#407` Out of Scope("강사가... 언어별로 켜고 끄는 것") 밖의 구현 세부사항이다.
build_verdict = build_parser_verdict


def build_ai_verdict(*, is_met: bool, reasoning: str) -> dict:
    """AI가 판정한 기본 항목 결과를 저장할 값으로 만든다(#409) — 파서가 없는
    언어이거나 크기·시간 제한에 걸린 파일을 AI가 봤을 때만 쓰인다. 구조화된
    `findings`는 없다 — AI의 판정 근거는 자유 문장으로만 남는다(파서 판정과
    달리 파일·줄을 구조로 뽑아낼 신뢰할 근거가 없다)."""

    return {"is_met": is_met, "reasoning": reasoning, "judged_by": "ai", "findings": []}
