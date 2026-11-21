"""「현재 점수」는 `scoring.current` 하나로만 읽는다 (#1179, 스펙 #1178, ADR-0006 개정 절).

원래 `Score` 는 두고 `ScoreCorrection` 을 덧대므로, 점수 값을 원래 `Score` 에서 직접 읽는 자리는 정정을 놓친다.
이 스캔이 `backend/` 소스(시험·마이그레이션 제외)를 AST 로 훑어 세 꼴을 잡는다:

- `submission.score` — 제출에서 `score` 관계로 건너가는 속성 접근
- `"score"` 당기기 — `hasattr`/`getattr`/`select_related`/`prefetch_related` 의 `"score"`·`"…__score"`, 그리고
  `…RELATIONS` 튜플의 `"score"`
- 판정 필드 필터 — `score__percentage|model_version|prompt|reasoning|scored_assets|repository_reachability_check`

`score__isnull` 은 잡지 않는다 — 「채점이 한 번 돌았나」는 원래 Score 유무가 맞다(정정은 원래 Score 가 있어야
생긴다). 같은 물음을 `hasattr(…, "score")` 로 묻는 자리는 아래 허용 목록에 이유와 함께 올린다.

허용 목록은 (파일, 함수) 단위다 — 파일 하나를 통째로 열면 그 파일의 다른 함수가 원래 점수를 다시 읽어도 모른다.
"""

from __future__ import annotations

import ast
import re

from tests.ast_scan_support import BACKEND_ROOT, python_sources

_SUBMISSION_NAMES = {"submission", "contest_submission", "contestsubmission"}
_PULL_CALLS = {"hasattr", "getattr", "select_related", "prefetch_related"}
_RELATION_PATH = re.compile(r"^(\w+__)?score$")
_VERDICT_FILTER = re.compile(
    r"(^|__)score__(percentage|model_version|prompt|reasoning|scored_assets|repository_reachability_check)(__|$)"
)

#: (파일, 함수) → 이유. 모듈 수준은 함수 이름 `<module>`.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("scoring/current.py", "current_score"): "현재 점수 함수 자신이다.",
    ("scoring/current.py", "<module>"): "현재 점수 함수가 걷는 관계(`CURRENT_SCORE_RELATIONS`)를 적는 자리다.",
    ("scoring/participation.py", "<module>"): "「다음 행동」·점수 화면이 당길 관계 — 현재 점수 함수가 그 위에서 돈다.",
    ("scoring/participation.py", "is_scored"): "채점이 한 번 돌았나(원래 Score 유무).",
    ("contests/scoring_hold.py", "is_size_held"): "채점 보류 대상인가(원래 Score 유무).",
    ("appeals/api.py", "create_appeal"): "이의를 낼 수 있나 — 채점이 한 번 돌았나(원래 Score 유무).",
    ("scoring/corrections.py", "_in_progress"): "정정 채점이 원래 Score 의 처음 커밋(`scored_assets`)을 읽는다(#1180).",
    ("distributions/correction_api.py", "list_score_corrections"): "정정 목록이 정정 전 점수(`original_percentage`)를 함께 보인다(#1180).",
}


def _violations() -> list[tuple[str, str, int, str]]:
    found: list[tuple[str, str, int, str]] = []
    for path in python_sources():
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found.extend((rel, *hit) for hit in _scan(tree))
    return found


def _scan(tree: ast.Module) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, func: str, relations_tuple: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id.endswith("RELATIONS") for t in node.targets
        ):
            relations_tuple = True
        hit = _hit(node, relations_tuple)
        if hit is not None:
            hits.append((func, getattr(node, "lineno", 0), hit))
        for child in ast.iter_child_nodes(node):
            visit(child, func, relations_tuple)

    visit(tree, "<module>", False)
    return hits


def _hit(node: ast.AST, relations_tuple: bool) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == "score" and _is_submission(node.value):
        return f"{ast.unparse(node)} — 제출에서 원래 Score 로 건너간다"
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in _PULL_CALLS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _RELATION_PATH.match(arg.value):
                    return f'{name}("{arg.value}") — 원래 Score 를 당긴다'
        for kw in node.keywords:
            if kw.arg and _VERDICT_FILTER.search(kw.arg):
                return f"{kw.arg}= — 원래 Score 의 판정 필드로 거른다"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if _VERDICT_FILTER.search(node.value):
            return f'"{node.value}" — 원래 Score 의 판정 필드를 가리킨다'
        if relations_tuple and _RELATION_PATH.match(node.value):
            return f'관계 "{node.value}" — 원래 Score 를 당긴다'
    return None


def _is_submission(value: ast.expr) -> bool:
    if isinstance(value, ast.Name):
        return value.id in _SUBMISSION_NAMES
    if isinstance(value, ast.Attribute):
        return value.attr in _SUBMISSION_NAMES
    return False


def test_score_verdict_is_read_only_through_current_score():
    offenders = [
        f"{file}:{line} ({func}) {what}"
        for file, func, line, what in _violations()
        if (file, func) not in ALLOWLIST
    ]
    assert not offenders, (
        "원래 Score 를 직접 읽는다 — `scoring.current`(공모전·이의 앱은 `contests.ports.CURRENT_SCORE`)로 읽거나, "
        "「채점이 한 번 돌았나」만 묻는 자리면 이유와 함께 ALLOWLIST 에 올린다:\n" + "\n".join(offenders)
    )


def test_every_allowlist_entry_is_still_needed():
    used = {(file, func) for file, func, _, _ in _violations()}
    stale = sorted(key for key in ALLOWLIST if key not in used)
    assert not stale, f"더는 원래 Score 를 읽지 않는 허용 항목 — 지운다: {stale}"


def test_every_allowlist_entry_has_a_reason():
    assert all(reason.strip() for reason in ALLOWLIST.values())


def test_scan_catches_each_shape():
    """일부러 넣은 위반 셋이 모두 잡힌다 — 스캔이 무는지 확인한다."""

    source = '''
def f(submission, qs):
    a = submission.score.percentage
    b = qs.select_related("submission__score")
    c = qs.filter(score__model_version__in=["x"])
    d = qs.filter(score__isnull=False)
    return getattr(submission, "score", None)
'''
    hits = _scan(ast.parse(source))
    lines = sorted(line for _, line, _ in hits)
    assert lines == [3, 4, 5, 7], hits


def test_scan_ignores_unrelated_scores():
    source = '''
def f(row, b):
    return row.score + b.score, {"score": 1}
'''
    assert _scan(ast.parse(source)) == []

