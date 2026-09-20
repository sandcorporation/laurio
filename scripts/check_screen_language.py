#!/usr/bin/env python3
"""공개 앱(`frontend/`)과 강의실 앱(`classroom/`)의 화면 문자열에 영어 도메인
용어나 내부 문서 번호가 다시 새어 들어오지 않는지 검사한다(#267, #278).

강의실도 로그인한 사람(강사·참여자)이 읽는 화면이라 같은 규율을 받는다 —
운영자 앱(`operator/`)만 대상 밖이다(아래 SCAN_DIRS 주석 참고).

#266 이 그 시점의 19곳을 치웠지만, 그것만으로는 같은 일이 다시 쌓인다 —
새 화면을 쓰는 사람도 에이전트도 `CONTEXT.md` 의 `_화면에서_` 줄을 매번
찾아보지는 않는다. 그래서 기계가 매 커밋 확인한다.

**용어 목록은 `CONTEXT.md` 에서 온다** — `**Name**:` 형태의 각 항목 머리글이
검사 대상 용어이고, 그 아래 `_화면에서_:` 줄이 있으면 그 값을 "무엇으로
바꿔야 하는지"로 실패 메시지에 그대로 보여준다. 용어집이 바뀌면 이 검사도
따라 바뀐다 — 목록을 이 파일에 다시 베끼지 않는다.

**휴리스틱**: 주석(`/* ... */`, 줄 전체가 `//` 인 줄)을 걷어낸 뒤, 한글이
있는 줄에 그 용어가 그대로 나오거나 `ADR-\\d+`/`#\\d+` 참조가 있으면 지적한다.
컴포넌트 이름·`data-testid`·타입 이름·import 경로는 한글이 없는 줄에 있으므로
이 휴리스틱이 저절로 건너뛴다.

**예외**: 정말 어쩔 수 없는 자리는 같은 줄이나 바로 앞 줄에
`SCREEN-LANGUAGE-EXCEPTION: <이유>` 주석을 남긴다 — 이유가 없으면(빈 문자열)
예외 자체가 실패한다. 표시 없는 예외는 「일부러 남긴 것」과 「그냥 걸린 것」을
구별하지 못하게 만든다.

**내부 어휘도 같은 방식으로 막는다**(#308). `CONTEXT.md`의 용어와 달리 이
목록(`INTERNAL_VOCAB`)은 도메인 명사가 아니라 설계 논의에서만 쓰는
낱말이다 — 「불변식」·「멱등」·「스냅샷」처럼 이미 한국어라 `_화면에서_` 대응이
없고, 걸리면 그 낱말 자체를 사용자 말로 풀어 쓰라고 말한다. 「전이」는 목록에
넣지 않았다 — "마감 전이라" 처럼 흔한 문법(전 + 조사 이)과 표기가 같아 그대로
넣으면 정상적인 문장을 오탐한다. 그래서 실제로 쓰이는 합성어(`상태 전이`·
`전이 그래프`)만 넣는다.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTEXT_MD = REPO_ROOT / "CONTEXT.md"

# 운영자 앱(`operator/`)은 대상이 아니다 — 그 앱에서는 이 용어들이 오히려
# 정확하다(#266). e2e(`frontend/e2e/`)도 화면이 아니라 시임 코드이므로 뺀다.
# 강의실(`classroom/`, #278)은 공개 앱과 같은 이유로 대상이다 — 강사·참여자가
# 읽는 화면이라 CONTEXT.md 어휘 규율이 그대로 적용된다. `classroom/components`는
# 아직 없다 — 생기면 여기 더한다(frontend/components처럼).
SCAN_DIRS = ["frontend/app", "frontend/components", "frontend/lib", "classroom/app", "classroom/lib"]

# 설계 문서에서만 쓰는 낱말 — 도메인 명사가 아니라서 `CONTEXT.md`에 없다
# (위 모듈 docstring의 「내부 어휘도 같은 방식으로 막는다」 참고, #308).
INTERNAL_VOCAB = ["불변식", "멱등", "스냅샷", "상태 전이", "전이 그래프", "감사 추적"]

# **문서·화면이 자기 구현을 설명하는 문장**(2026-09-21). 이용약관과
# 개인정보처리방침의 첫 판에 「유료 공모전을 여는 시점에 채우는 조항」 같은 절과
# 「그 조항은 8절에 자리만 남겨 두었고, 기능을 열 때 채웁니다」 같은 문장이
# 들어가 「다른 서비스와 달리 사족이 많고 이상하다」는 지적을 받았다. 이것은
# 저장소 문서(`docs/legal/`·주석)의 말투이지 **이용자가 읽는 화면의 말투가
# 아니다** — 화면은 지금 참인 사실만 말하고, 아직 없는 것은 **적지 않는다**.
# 오탐을 만들지 않도록 「이 자리는 나중에 채운다」는 뜻으로만 쓰이는 토막만
# 넣는다. 정말 필요하면 다른 항목과 같은 `SCREEN-LANGUAGE-EXCEPTION` 으로 연다.
META_PHRASES = [
    "자리만 남",
    "자리 표시",
    "채울 자리",
    "나중에 채우",
    "열 때 채우",
    "아직 구현",
    "미구현",
    "추후 구현",
    "TODO",
]

TERM_HEADER_RE = re.compile(r"^\*\*([A-Za-z][A-Za-z0-9]*)\*\*:\s*$")
SCREEN_NAME_RE = re.compile(r"^_화면에서_:\s*(.+)$")

BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
HANGUL_RE = re.compile(r"[가-힣]")
ADR_REF_RE = re.compile(r"(?<![A-Za-z0-9_])ADR-\d+(?![A-Za-z0-9_])")
ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9_])#\d+(?![A-Za-z0-9_])")
EXCEPTION_RE = re.compile(r"SCREEN-LANGUAGE-EXCEPTION:\s*(.*)$")
# 마커가 `{/* ... */}` 안에 한 줄로 들어오면 group(1)에 닫는 `*/`·`}` 까지
# 딸려 온다 — 이유가 진짜로 비었는지 보려면 그것부터 떼어낸다.
TRAILING_COMMENT_CLOSE_RE = re.compile(r"\s*\*/\s*\}?\s*$")
# 주석을 걷어낸 뒤 이 정도만 남으면 "그 줄 전체가 주석이었다" 로 본다 —
# `/* ... */` 를 지우고 나면 JSX 주석을 감싸던 `{`·`}` 만 남을 수 있다.
COMMENT_REMAINDER_RE = re.compile(r"^[{}]*$")


def _is_test(path: Path) -> bool:
    return path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))


def exception_reason(line: str) -> str | None:
    m = EXCEPTION_RE.search(line)
    if m is None:
        return None
    return TRAILING_COMMENT_CLOSE_RE.sub("", m.group(1)).strip()


@dataclass(frozen=True)
class Term:
    name: str
    screen_name: str | None  # CONTEXT.md 의 `_화면에서_` 값. 없으면 None.
    pattern: re.Pattern[str]
    internal_vocab: bool = False  # INTERNAL_VOCAB 에서 왔는가 — 메시지 문구가 다르다.


def _term_pattern(name: str) -> re.Pattern[str]:
    # 영문 한 글자짜리·소문자 시작 등은 애초에 TERM_HEADER_RE 가 거른다.
    # 공백을 포함한 한국어 합성어(`상태 전이`)도 그대로 이스케이프되므로
    # 안전하다.
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")


def load_terms() -> list[Term]:
    if not CONTEXT_MD.exists():
        print(f"::error::{CONTEXT_MD} 를 찾을 수 없다 — 경로가 바뀌었는가?")
        sys.exit(1)

    lines = CONTEXT_MD.read_text().split("\n")
    terms: list[Term] = []
    current_name: str | None = None
    current_screen_name: str | None = None

    def flush() -> None:
        if current_name is None:
            return
        terms.append(Term(current_name, current_screen_name, _term_pattern(current_name)))

    for line in lines:
        header = TERM_HEADER_RE.match(line)
        if header:
            flush()
            current_name = header.group(1)
            current_screen_name = None
            continue
        screen = SCREEN_NAME_RE.match(line)
        if screen and current_name is not None:
            current_screen_name = screen.group(1).strip()
    flush()

    if not terms:
        print(f"::error::{CONTEXT_MD} 에서 `**Name**:` 형태의 용어를 하나도 못 읽었다.")
        sys.exit(1)

    for word in INTERNAL_VOCAB:
        terms.append(Term(word, None, _term_pattern(word), internal_vocab=True))

    return terms


def strip_comments_preserve_lines(text: str) -> str:
    """줄 번호를 그대로 둔 채 주석만 지운다.

    블록 주석(`/* ... */`, JSX 주석 `{/* ... */}` 포함)은 내부 개행 수만큼
    빈 줄로 치환하고, 줄 전체가 `//` 로 시작하는 줄은 그 줄만 비운다 —
    코드 뒤에 붙는 한 줄 주석(`foo(); // ...`)은 다루지 않는다(이 저장소의
    주석은 거의 항상 자기 줄을 통째로 쓴다 — `frontend/e2e/contests-detail.spec.ts`
    가 같은 전제로 같은 방식을 이미 쓴다).
    """

    def repl_block(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    text = BLOCK_COMMENT_RE.sub(repl_block, text)
    return "\n".join(
        "" if line.strip().startswith("//") else line for line in text.split("\n")
    )


def find_exceptions(raw_lines: list[str], stripped_lines: list[str]) -> set[int]:
    """`SCREEN-LANGUAGE-EXCEPTION: <이유>` 가 달린 줄, 그 뒤에 이어지는 주석
    줄(들), 그리고 주석이 끝난 뒤 맨 처음 나오는 코드 줄의 1-based 줄 번호
    집합을 돌려준다 — 주석은 거의 항상 자기가 지키는 코드 줄 바로 앞에 오므로,
    여러 줄짜리 표시도 그 다음 실제 코드 한 줄만 가리키면 된다.

    "이어지는 주석 줄"인지는 `stripped_lines`(주석을 걷어낸 뒤의 텍스트)로
    판단한다 — 줄 전체가 `//` 인 줄과 여러 줄짜리 `/* ... */`(JSX 주석
    `{/* ... */}` 포함)의 중간 줄 모두, 걷어내고 나면 비거나 JSX 감싸는
    중괄호만 남는다. JSX 텍스트 자리에서는 `//` 가 아니라 `{/* ... */}` 만
    주석으로 쓸 수 있으므로 이 구분이 없으면 여러 줄짜리 JSX 주석 표시가
    가리키는 줄을 놓친다.

    이유가 비어 있으면 그 표시 자체를 오류로 보고한다(호출부에서 처리).
    """
    n = len(raw_lines)
    excepted: set[int] = set()
    for i, line in enumerate(raw_lines):
        if not EXCEPTION_RE.search(line):
            continue
        excepted.add(i + 1)
        j = i + 1
        while j < n and COMMENT_REMAINDER_RE.match(stripped_lines[j].strip()):
            excepted.add(j + 1)
            j += 1
        if j < n:
            excepted.add(j + 1)
    return excepted


def check_file(path: Path, terms: list[Term]) -> list[str]:
    raw_text = path.read_text()
    raw_lines = raw_text.split("\n")

    problems: list[str] = []
    for i, line in enumerate(raw_lines):
        reason = exception_reason(line)
        if reason is not None and not reason:
            problems.append(
                f"{path}:{i + 1}: SCREEN-LANGUAGE-EXCEPTION 에 이유가 없다 — "
                f"`SCREEN-LANGUAGE-EXCEPTION: <이유>` 형태로 적을 것."
            )

    stripped = strip_comments_preserve_lines(raw_text)
    stripped_lines = stripped.split("\n")
    excepted_lines = find_exceptions(raw_lines, stripped_lines)

    for i, line in enumerate(stripped_lines):
        lineno = i + 1
        if not HANGUL_RE.search(line):
            continue
        if lineno in excepted_lines:
            continue

        for term in terms:
            if not term.pattern.search(line):
                continue
            if term.internal_vocab:
                problems.append(
                    f"{path}:{lineno}: 설계 문서에서만 쓰는 내부 낱말 `{term.name}` 가 화면 "
                    f"문자열에 있다 — 무엇을 뜻하는지 사용자 말로 풀어 쓸 것."
                )
                continue
            fix = (
                f"`{term.screen_name}` 로 바꿀 것"
                if term.screen_name
                else f"화면 문자열에서 영어 용어 `{term.name}` 를 한국어로 옮길 것"
            )
            problems.append(
                f"{path}:{lineno}: 영어 도메인 용어 `{term.name}` 가 화면 문자열에 있다 — {fix}"
            )

        for phrase in META_PHRASES:
            if phrase in line:
                problems.append(
                    f"{path}:{lineno}: 화면이 자기 구현을 설명하는 문장이다(`{phrase}`) — "
                    f"지금 참인 사실만 남기고, 아직 없는 것은 적지 말 것."
                )

        for pattern, label in ((ADR_REF_RE, "ADR 번호"), (ISSUE_REF_RE, "이슈 번호")):
            if pattern.search(line):
                problems.append(
                    f"{path}:{lineno}: {label} 참조가 화면 문자열에 있다 — "
                    f"규칙의 내용만 남기고 출처 표기(`{pattern.search(line).group(0)}`)는 뺄 것."
                )

    return problems


def main() -> int:
    terms = load_terms()

    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            print(f"::error::{base} 가 없다 — 경로가 바뀌었는가?")
            return 1
        # 테스트 파일은 화면이 아니다 — 거기서는 규칙을 설명하려고 ADR·이슈
        # 번호를 그대로 쓰는 것이 옳다(그것이 그 테스트가 지키는 결정의 출처다).
        # 백엔드 쪽 AST 게이트가 `tests/` 를 빼는 것과 같은 이유다
        # (`backend/tests/ast_scan_support.py` 의 SKIPPED_PARTS).
        files.extend(f for f in sorted(base.rglob("*.tsx")) if not _is_test(f))
        files.extend(f for f in sorted(base.rglob("*.ts")) if not _is_test(f))

    if not files:
        print("::error::검사할 프론트엔드 파일을 하나도 못 찾았다.")
        return 1

    problems: list[str] = []
    for f in files:
        problems.extend(check_file(f.relative_to(REPO_ROOT), terms))

    for p in problems:
        print(f"::error::{p}")

    if problems:
        print(f"\n{len(files)}개 파일 중 {len(problems)}건 문제.")
        return 1

    print(
        f"공개 앱 파일 {len(files)}개 전부 화면 문자열에 영어 도메인 용어·ADR/이슈 번호·"
        "자기 구현을 설명하는 문장이 없다."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
