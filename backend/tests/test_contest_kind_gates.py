"""종류 게이트가 한 자리에 남아 있는지를 정적으로 증명한다 (#232, ADR-0033).

`Contest.Status.PAYABLE` 은 **status 만의 순수 함수**라 「이 행이 공모전인가 과제인가」에
답하지 못한다 — `DRAFT` 를 둘이 공유하기 때문이다(ADR-0028). 그것을 직접 부르는 자리가
생기면 그 자리가 과제를 통과시킨다. 실제로 두 번 그랬다(#207 편집 표면, #232 결제).

그래서 규율이 아니라 **테스트**로 막는다. `contests.gates` 의 독스트링이 왜 그 모듈이
있는지를 적고, 이 테스트가 새로 쓴 코드를 그 모듈로 데려간다 — `appeals` 의
`test_no_rescoring_code_path_exists_in_appeals_app` 과 같은 방식이다(설명 주석에서
이름을 언급하는 것과 실제 호출은 다르므로 AST 로 검사한다).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.ast_scan_support import BACKEND_ROOT, python_sources

#: 이 분류를 직접 불러도 되는 자리 — 정의하는 곳과, 종류를 함께 보는 게이트 하나뿐이다.
ALLOWED = {
    Path("contests/models.py"),
    Path("contests/gates.py"),
}


def _references_payable(tree: ast.AST) -> bool:
    """`<무엇>.Status.PAYABLE` 모양의 속성 접근이 있는가."""

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "PAYABLE"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "Status"
        ):
            return True
    return False


def test_payable_classification_is_only_called_through_the_kind_gate():
    offenders = []
    for path in python_sources():
        relative = path.relative_to(BACKEND_ROOT)
        if relative in ALLOWED:
            continue
        if _references_payable(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(str(relative))

    assert not offenders, (
        "`Contest.Status.PAYABLE` 을 직접 부르는 자리가 생겼다: "
        f"{', '.join(sorted(offenders))}. 그 분류는 status 만 보므로 아직 열리지 않은 "
        "과제(DRAFT)를 공모전과 구별하지 못한다 — `contests.gates.payable()` 을 쓰거나, "
        "종류를 함께 보는 새 게이트를 그 모듈에 더한다(#232)."
    )


def test_the_gate_module_itself_still_answers_both_questions():
    """게이트가 종류와 상태를 **둘 다** 본다 — 어느 한쪽만 보면 이 파일의 다른 테스트가
    통과하면서도 구멍은 그대로 남는다."""

    source = (BACKEND_ROOT / "contests" / "gates.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert _references_payable(tree), "게이트가 status 분류를 더 이상 보지 않는다"
    assert any(
        isinstance(node, ast.Attribute) and node.attr == "is_assignment"
        for node in ast.walk(tree)
    ), "게이트가 종류를 더 이상 보지 않는다"


@pytest.mark.django_db
def test_payable_gate_refuses_an_assignment_in_every_status():
    """과제는 어떤 status 에서도 결제 대상이 아니다 — `DRAFT` 하나만 막으면 다음에
    과제가 새 status 를 갖게 될 때 같은 구멍이 다시 열린다."""

    from contests import gates
    from contests.models import Contest

    for status in Contest.Status:
        assignment = Contest(kind=Contest.Kind.ASSIGNMENT, status=status)
        assert gates.payable(assignment) is False, f"{status} 과제가 결제 대상으로 판정됐다"
