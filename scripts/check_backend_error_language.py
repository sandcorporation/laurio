#!/usr/bin/env python3
"""백엔드가 사용자에게 던지는 오류 메시지에 영어 도메인 용어나 내부 문서
번호가 새지 않는지 검사한다(#268).

`scripts/check_screen_language.py`(#267)는 `frontend/`만 훑는다 — 그래서
공개 앱이 백엔드의 `HttpError(...)` 문구를 그대로 렌더할 때(`normalizeDetail`,
`packages/bff-client/src/result.ts`)는 그 검사가 볼 수 없다. 이 스크립트가
그 표면을 막는다. 용어 목록·예외 표시(`SCREEN-LANGUAGE-EXCEPTION: <이유>`)
·ADR/이슈 번호 검사는 `check_screen_language`의 것을 그대로 가져다 쓴다 —
용어집이 CONTEXT.md 하나에서만 온다는 규칙이 두 표면에서 갈리지 않는다.

**대상은 "한글이 있는 줄"이 아니라 `HttpError(status_code, message)`의
`message` 인자 하나다.** 로그(`logger.warning(...)`)·docstring·주석은
`HttpError(` 라는 이름 자체가 없으므로 이 검사에 애초에 걸리지 않는다 — 검사
대상을 넓히지 않고도 저절로 그렇게 된다.

**운영자 API(`/api/operator/*`, `#266`이 정한 경계)도, `InternalAuth`가 지키는
내부 전용 표면(스캔 틱·e2e 시드·채점 콜백 등, 사람이 아니라 우리 인프라가
부르는 자리)도 대상이 아니다.** `appeals/api.py`·`payouts/api.py`처럼 공개
라우터(`router`)와 운영자 라우터(`operator_router`, 관례상 이 이름을 쓰거나
`Router(..., auth=OperatorAuth())`로 선언된다)가 **한 파일에 같이 있는
경우**가 있어 파일 단위로는 가를 수 없다. 그래서 함수 단위로 가른다:

1. 각 엔드포인트 함수를 그 데코레이터로 배정한다 — `@router.get(...)` 대
   `@operator_router.get(...)`(라우터 단위 `auth=OperatorAuth()`/
   `auth=InternalAuth()`), 또는 `core/api.py`처럼 라우터는 공개인데
   엔드포인트마다 `auth=InternalAuth()`를 따로 붙이는 자리.
2. 데코레이터가 없는 도우미 함수(`_get_owned_submission` 같은)는 **같은
   파일 안에서** 그 함수를 부르는 호출 그래프를 따라, 공개 라우터 함수에서
   닿을 수 있으면 공개로, 그러지 않고 운영자·내부 전용 함수에서만 닿을 수
   있으면(예: `appeals.api._get_appeal_or_404`) 제외 대상으로 판정한다.
3. 어느 쪽에서도 닿지 않는(또는 양쪽에서 닿는) 도우미는 **공개로 본다** —
   놓치는 것보다 예외 주석을 하나 더 다는 편이 싸다.

`core/operator_auth.py`는 이 알고리즘 밖에 있다 — 그 파일에는 라우터 선언
자체가 없다(순수 인증 유틸리티). 거기 메시지는 `SESSION_AUTHENTICATED_
PREFIXES`(`/api/operator/*`, `/api/ledger/*`)에서만 나가고 공개 앱에는 닿지
않으므로 파일째 제외한다. `backend/.venv/`(의존성 소스)도 파일째 제외한다 —
이 저장소의 코드가 아니다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_screen_language as csl  # noqa: E402 - sys.path 조정 뒤에 임포트한다

_EXCLUDED_DIR_PARTS = {"tests", "migrations", ".venv"}
# 라우터 선언이 아예 없는 공유 인증 유틸리티 — 운영자/원장 세션 전용이라
# 공개 앱에 닿지 않는다(위 모듈 docstring 참고).
_EXCLUDED_FILES = {BACKEND_ROOT / "core" / "operator_auth.py"}
# 라우터 단위로(개별 엔드포인트가 아니라) 이 이름의 `auth=` 콜을 쓰면
# 그 라우터 전체가 공개 앱 밖이다 — 운영자(`OperatorAuth`)와 우리 인프라만
# 부르는 내부 표면(`InternalAuth`, 스캔 틱·e2e 시드·채점 콜백) 둘 다.
_NON_PUBLIC_AUTH_CALLABLES = {"OperatorAuth", "InternalAuth"}


def _iter_target_files():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        if path in _EXCLUDED_FILES:
            continue
        if _EXCLUDED_DIR_PARTS & set(path.relative_to(BACKEND_ROOT).parts):
            continue
        yield path


def _auth_call_name(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    fn = node.func
    return fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)


def _router_assignments(tree: ast.Module) -> dict[str, bool]:
    """모듈 최상위의 `X = Router(...)` 대입을 찾아 `{이름: 공개 앱 밖인가}`로
    답한다.

    `operator_router`라는 이름 자체가 이 저장소 전체의 관례이지만, 그 관례를
    안 지킨 자리도 실제로 있다(`accounts/operator_api.py`는 그 라우터를
    `router`라고 부른다) — 그래서 이름과 무관하게 `auth=OperatorAuth()`/
    `auth=InternalAuth()` 키워드도 함께 본다. 셋 중 하나만 참이어도 공개 앱
    밖이다.
    """

    routers: dict[str, bool] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "Router"
        ):
            continue
        name = node.targets[0].id
        is_non_public = name == "operator_router"
        for kw in node.value.keywords:
            if kw.arg == "auth" and _auth_call_name(kw.value) in _NON_PUBLIC_AUTH_CALLABLES:
                is_non_public = True
        routers[name] = is_non_public
    return routers


def _decorator_router_label(func: ast.FunctionDef | ast.AsyncFunctionDef, routers: dict[str, bool]) -> str | None:
    """`func`가 붙은 라우터로 공개/제외를 답한다. 라우터 자체가 공개여도
    (`core/api.py`의 `router`처럼) 엔드포인트마다 `auth=InternalAuth()`를 따로
    거는 자리가 있어, 데코레이터 키워드도 라우터 판정과 별개로 확인한다."""

    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        for kw in dec.keywords:
            if kw.arg == "auth" and _auth_call_name(kw.value) in _NON_PUBLIC_AUTH_CALLABLES:
                return "excluded"
        fn = dec.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            router_name = fn.value.id
            if router_name in routers:
                return "excluded" if routers[router_name] else "public"
    return None


def _direct_calls(func: ast.FunctionDef | ast.AsyncFunctionDef, local_names: set[str]) -> set[str]:
    calls = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in local_names
            and node.func.id != func.name
        ):
            calls.add(node.func.id)
    return calls


def _reachable(seeds: list[str], graph: dict[str, set[str]]) -> set[str]:
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        current = stack.pop()
        for nxt in graph.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _is_httperror_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id == "HttpError"
    if isinstance(fn, ast.Attribute):
        return fn.attr == "HttpError"
    return False


def _literal_text(node: ast.AST) -> str | None:
    """`message` 인자의 정적 텍스트만 뽑는다. f-string 의 `{expr}` 자리는 뺀다 —
    거기 담기는 값(예: `evidence.kind`)까지 검사할 수는 없고, 검사할 필요도
    없다(사용자가 고른 값이지 우리가 고른 낱말이 아니다)."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        return "".join(parts) if parts else None
    return None


def _exception_reason(raw_lines: list[str], call_lineno: int, message_lineno: int) -> str | None:
    """`SCREEN-LANGUAGE-EXCEPTION: <이유>`를 찾는다 — `check_screen_language`와
    같은 표시, 같은 규율(이유가 비면 표시 자체가 실패다)이다.

    `raise HttpError(` 여는 줄부터 실제 `message` 문자열이 있는 줄까지, 그리고
    그 앞 한 줄까지 본다 — 여러 줄짜리 호출에서는 사람이 표시를 `raise
    HttpError(` 바로 그 줄에 달지, 문자열 리터럴이 있는 줄에 달지 코드리뷰마다
    다르다. 한 줄만 보면 다른 쪽에 단 표시를 놓친다."""

    for candidate in range(call_lineno - 1, message_lineno + 1):
        if 1 <= candidate <= len(raw_lines):
            reason = csl.exception_reason(raw_lines[candidate - 1])
            if reason is not None:
                return reason
    return None


def analyze_file(path: Path, terms: list[csl.Term]) -> list[str] | None:
    """`HttpError(` 를 아예 안 부르는 파일은 `None` — 「검사할 것이 없었다」와
    「검사했는데 문제가 없었다」(빈 리스트)를 갈라, 호출부가 파일을 두 번 읽지
    않고도 스캔한 파일 수를 셀 수 있게 한다."""

    text = path.read_text()
    if "HttpError(" not in text:
        return None

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: 파싱 실패 — {exc}"]

    routers = _router_assignments(tree)
    top_funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    label = {name: _decorator_router_label(func, routers) for name, func in top_funcs.items()}
    graph = {name: _direct_calls(func, set(top_funcs)) for name, func in top_funcs.items()}
    public_reach = _reachable([n for n, l in label.items() if l == "public"], graph)
    excluded_reach = _reachable([n for n, l in label.items() if l == "excluded"], graph)

    def is_public_facing(name: str) -> bool:
        if label[name] == "public":
            return True
        if label[name] == "excluded":
            return False
        # 데코레이터가 없는 도우미 함수 — 호출 그래프로 판정한다(모듈 docstring 3번).
        if name in public_reach:
            return True
        if name in excluded_reach:
            return False
        return True  # 어느 쪽에서도 닿지 않으면 놓치지 않는 쪽으로 기본값을 잡는다.

    raw_lines = text.split("\n")
    problems: list[str] = []
    for name, func in top_funcs.items():
        if not is_public_facing(name):
            continue
        for node in ast.walk(func):
            if not _is_httperror_call(node) or len(node.args) < 2:
                continue
            message_node = node.args[1]
            message_text = _literal_text(message_node)
            if message_text is None:
                continue
            lineno = getattr(message_node, "lineno", node.lineno)

            reason = _exception_reason(raw_lines, node.lineno, lineno)
            if reason is not None:
                if not reason:
                    problems.append(
                        f"{path}:{lineno}: SCREEN-LANGUAGE-EXCEPTION 에 이유가 없다 — "
                        f"`SCREEN-LANGUAGE-EXCEPTION: <이유>` 형태로 적을 것."
                    )
                continue

            for term in terms:
                if term.pattern.search(message_text):
                    fix = (
                        f"`{term.screen_name}`로 바꿀 것"
                        if term.screen_name
                        else f"영어 용어 `{term.name}`를 한국어로 옮길 것"
                    )
                    problems.append(
                        f"{path}:{lineno}: 영어 도메인 용어 `{term.name}`가 사용자 대면 "
                        f"메시지에 있다 — {fix}"
                    )
            for pattern, ref_label in (
                (csl.ADR_REF_RE, "ADR 번호"),
                (csl.ISSUE_REF_RE, "이슈 번호"),
            ):
                match = pattern.search(message_text)
                if match:
                    problems.append(
                        f"{path}:{lineno}: {ref_label} 참조가 사용자 대면 메시지에 있다 — "
                        f"규칙의 내용만 남기고 출처 표기(`{match.group(0)}`)는 뺄 것."
                    )

    return problems


def main() -> int:
    terms = csl.load_terms()

    files = list(_iter_target_files())
    if not files:
        print(f"::error::{BACKEND_ROOT} 아래에서 검사할 파일을 하나도 못 찾았다.")
        return 1

    problems: list[str] = []
    scanned = 0
    for f in files:
        file_problems = analyze_file(f, terms)
        if file_problems is None:
            continue
        scanned += 1
        problems.extend(file_problems)

    for p in problems:
        print(f"::error::{p}")

    if problems:
        print(f"\n{scanned}개 파일 중 {len(problems)}건 문제.")
        return 1

    print(f"백엔드 {scanned}개 파일 전부 사용자 대면 오류 메시지에 영어 도메인 용어·ADR/이슈 번호가 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
