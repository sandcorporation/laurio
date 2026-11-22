"""근거 인용 대조 규칙(#1284, `core.evidence_check`) — 강의실 staged 채점과 실험(`scoring.experiment.count_real_evidence`)이
함께 쓴다. 우리 루프(`scoring.selfloop`)는 이미지에 혼자 실리는 표준 라이브러리 파일이라 같은 규칙의 사본을 든다 — 그
사본이 어긋나지 않게 여기서 못 박는다.
"""

from __future__ import annotations

import pytest

from core import evidence_check
from core.evidence_check import Citation, citation_problem
from scoring import selfloop

FILES = {
    "src/app.py": ("import os", "", "def main():", "    print('hello')"),
    "README.md": ("# 데모",),
}


@pytest.mark.parametrize(
    ("citation", "problem"),
    [
        (Citation("src/app.py", 3, 4), None),
        (Citation("./src/app.py", 3, 3), None),
        (Citation("src/nope.py", 1, 1), "path"),
        (Citation("/src/app.py", 3, 3), "path"),  # 절대 경로는 박제본 대조처럼 맞지 않는다
        (Citation("src/app.py", 3, 9), "range"),
        (Citation("src/app.py", 4, 3), "range"),
        (Citation("src/app.py", 0, 1), "range"),
        (Citation("src/app.py", 1, 2), "trivial"),  # import·빈 줄뿐
    ],
)
def test_a_citation_is_checked_against_the_sent_files(citation, problem):
    assert citation_problem(FILES, citation) == problem


def test_the_selfloop_copy_keeps_the_same_rule():
    assert selfloop.EVIDENCE_RE.pattern == evidence_check.EVIDENCE_RE.pattern
    assert selfloop._TRIVIAL_LINE_RE.pattern == evidence_check._TRIVIAL_LINE_RE.pattern
