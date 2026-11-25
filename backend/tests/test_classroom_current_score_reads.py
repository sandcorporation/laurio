"""강의실 「현재 점수」는 `classroom.current_score` 하나로만 읽는다 (#1317, ADR-0006 개정 절).

원래 `ClassroomScore` 는 두고 `ClassroomScoreCorrection` 을 덧대므로, 판정을 원래 점수에서 직접 읽는 자리는 정정을
놓친다. 공모전 `tests/test_current_score_reads.py` 와 같은 꼴로 `backend/` 소스(시험·마이그레이션 제외)를 AST 로 훑어
네 꼴을 잡는다:

- `….classroom_score` — 시도에서 원래 점수로 건너가는 속성 접근
- `getattr`/`hasattr(…, "classroom_score")`
- 판정 필드 경로 — `classroom_score__model_version|prompt|reasoning|syntax_check_result|unseen_files|input_fingerprint`
- `ClassroomScore` 이름 — 모델을 직접 질의·생성하는 자리(타입 주석·import 는 세지 않는다)

`select_related("classroom_score")`·`classroom_score__isnull` 은 잡지 않는다 — 불러 두기·「채점이 한 번 돌았나」는
원래 점수 유무가 맞다(정정은 원래 점수가 있어야 생긴다). 원래 점수를 만들거나 그 유무만 묻는 자리, 원래 판정을
일부러 읽는 자리(재사용)는 아래 허용 목록에 이유와 함께 올린다. 허용 목록은 (파일, 함수) 단위다.
"""

from __future__ import annotations

import ast
import re

import pytest

from tests.ast_scan_support import ParsedSource

_RELATION = "classroom_score"
_VERDICT_PATH = re.compile(
    r"(^|__)classroom_score__(model_version|prompt|reasoning|syntax_check_result|unseen_files|input_fingerprint)(__|$)"
)
_PULL_CALLS = {"hasattr", "getattr"}

#: (파일, 함수) → 이유. 모듈 수준은 함수 이름 `<module>`.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("classroom/models.py", "<module>"): "정정이 원래 점수를 가리킨다(FK).",
    ("classroom/current_score.py", "<module>"): "현재 점수 모듈 자신이다 — 다루는 쿼리셋의 모델 타입.",
    ("classroom/current_score.py", "original_score"): "현재 점수 모듈 자신이다 — 원래 점수 행을 꺼내는 한 자리.",
    ("classroom/current_score.py", "without_score_prompt"): "현재 점수 모듈 자신이다 — 원래 점수의 프롬프트 칸을 뺀다.",
    ("classroom/current_score.py", "scores_with_current_fields"): "현재 점수 모듈 자신이다 — 원래 점수에 현재 값을 붙인다.",
    ("classroom/api.py", "<module>"): "목록 질의가 불러 둘 칸(프롬프트 빼기·통과 판정 칸만) — 읽기는 `current_score` 로 한다.",
    ("classroom/api.py", "_class_row_stats"): "클래스별 「채점된 시도 수」 — 채점이 한 번 돌았나(원래 점수 유무).",
    ("classroom/api.py", "remove_problem"): "문제를 지울 때 강사 자신의 시도에 달린 채점을 걷는다(ADR-0050).",
    ("classroom/management/commands/seed_demo_classroom.py", "_purge"): "데모 시드가 자기 `[데모]` 클래스의 채점을 걷는다.",
    ("classroom/management/commands/seed_demo_classroom.py", "_attempts"): "데모 시드가 원래 점수를 만든다.",
    ("classroom/score_reuse.py", "find_reusable_score"): "재사용(#1287)은 같은 입력으로 낸 원래 벤더 판정을 찾는다 — 정정은 다른 때·모델의 판정이다.",
    ("classroom/scoring.py", "_finalize_platform_failure"): "처음 채점이 원래 점수(실패 상한)를 만든다.",
    ("classroom/scoring.py", "_apply_vendor_outcome"): "처음 채점이 원래 점수를 만든다.",
    ("classroom/scoring.py", "_prepare_head"): "이미 채점됐나 — 원래 점수 유무.",
    ("classroom/scoring.py", "conclude_scoring"): "이미 채점됐나 — 원래 점수 유무.",
    ("classroom/scoring.py", "finish_scoring"): "방금 만든 원래 점수로 채점 완료 알림을 보낸다.",
    ("classroom/scoring.py", "claim_attempt"): "임대를 집을 때 이미 채점됐나 — 원래 점수 유무.",
    ("classroom/scoring.py", "extend_lease"): "임대를 늘릴 때 이미 채점됐나 — 원래 점수 유무.",
}


@pytest.fixture(scope="module")
def violations(backend_sources: list[ParsedSource]) -> list[tuple[str, str, int, str]]:
    found: list[tuple[str, str, int, str]] = []
    for source in backend_sources:
        assert isinstance(source.tree, ast.Module)
        found.extend((source.relative.as_posix(), *hit) for hit in _scan(source.tree))
    return found


def _scan(tree: ast.Module) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []

    # 타입 주석은 읽기가 아니다 — 세션 픽스처의 트리를 고치지 않고 건너뛸 노드로만 센다.
    annotations: set[int] = set()

    def visit(node: ast.AST, func: str) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in annotations:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            annotations.update(id(a.annotation) for a in arguments if a.annotation is not None)
            if node.returns is not None:
                annotations.add(id(node.returns))
        if isinstance(node, ast.AnnAssign):
            annotations.add(id(node.annotation))
        hit = _hit(node)
        if hit is not None:
            hits.append((func, getattr(node, "lineno", 0), hit))
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(tree, "<module>")
    return hits


def _hit(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == _RELATION:
        return f"{ast.unparse(node)} — 시도에서 원래 점수로 건너간다"
    if isinstance(node, ast.Name) and node.id == "ClassroomScore" and isinstance(node.ctx, ast.Load):
        return "ClassroomScore — 원래 점수를 직접 질의·생성한다"
    if isinstance(node, ast.Call):
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in _PULL_CALLS:
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == _RELATION:
                    return f'{name}(…, "{_RELATION}") — 원래 점수를 꺼낸다'
        for kw in node.keywords:
            if kw.arg and _VERDICT_PATH.search(kw.arg):
                return f"{kw.arg}= — 원래 점수의 판정 필드로 거른다"
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and _VERDICT_PATH.search(node.value):
        return f'"{node.value}" — 원래 점수의 판정 필드를 가리킨다'
    return None


def test_classroom_verdict_is_read_only_through_current_score(violations):
    offenders = [
        f"{file}:{line} ({func}) {what}" for file, func, line, what in violations if (file, func) not in ALLOWLIST
    ]
    assert not offenders, (
        "원래 ClassroomScore 를 직접 읽는다 — `classroom.current_score` 로 읽거나, 원래 점수를 만들거나 그 유무만 "
        "묻는 자리면 이유와 함께 ALLOWLIST 에 올린다:\n" + "\n".join(offenders)
    )


def test_every_allowlist_entry_is_still_needed(violations):
    used = {(file, func) for file, func, _, _ in violations}
    stale = sorted(key for key in ALLOWLIST if key not in used)
    assert not stale, f"더는 원래 점수를 읽지 않는 허용 항목 — 지운다: {stale}"


def test_every_allowlist_entry_has_a_reason():
    assert all(reason.strip() for reason in ALLOWLIST.values())


def test_scan_catches_each_shape():
    """일부러 넣은 위반 넷이 모두 잡힌다 — 스캔이 무는지 확인한다."""

    source = '''
from classroom.models import ClassroomScore
def f(submission: ClassroomScore, qs) -> ClassroomScore:
    a = submission.classroom_score.reasoning
    b = qs.filter(classroom_score__model_version__in=["x"])
    c = qs.filter(classroom_score__isnull=False).select_related("classroom_score")
    d = ClassroomScore.objects.all()
    return getattr(submission, "classroom_score", None)
'''
    hits = _scan(ast.parse(source))
    lines = sorted(line for _, line, _ in hits)
    assert lines == [4, 5, 7, 8], hits
