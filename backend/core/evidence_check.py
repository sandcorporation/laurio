"""근거 인용(`경로:줄`)을 소스와 대조하는 규칙(#1284) — 실험(`scoring.selfloop.check_evidence`)과 강의실 staged
채점(`classroom.scoring`)이 함께 쓴다.

규칙: 경로가 보낸 소스에 있고, 줄 범위가 `1 ≤ start ≤ end ≤ 파일 줄 수` 이며, 그 줄이 모두 빈 줄·주석·import 뿐은
아니다. 경로를 어떻게 찾는지(박제본 디스크 · 프롬프트에 실은 파일)는 부르는 쪽 몫이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

#: 근거 한 줄의 꼴 — `경로`, `경로:줄`, `경로:줄-줄`.
EVIDENCE_RE = re.compile(r"^(?P<path>[^:\n]+)(?::(?P<start>[1-9][0-9]*)(?:-(?P<end>[1-9][0-9]*))?)?$")
#: 근거로 받지 않는 줄 — 빈 줄, 주석, import 류.
_TRIVIAL_LINE_RE = re.compile(
    r"^(?:$|#(?!include)|//|/\*|\*|\*/|<!--|-->|--\s|;|"
    r"import\s|from\s+\S+\s+import\s|#include\s|using\s+[\w.]+\s*;|package\s+[\w.]+\s*;?$|@import\s|"
    r"(?:const|let|var)\s+\w+\s*=\s*require\(|require\s|use\s+[\w:\\]+\s*;)"
)

#: 인용 하나가 틀린 까닭 — 없는 경로, 파일 밖 줄 범위, 빈 줄·주석·import 뿐인 줄.
CitationProblem = Literal["path", "range", "trivial"]


@dataclass(frozen=True)
class Citation:
    path: str
    start_line: int
    end_line: int

    def as_dict(self) -> dict[str, str | int]:
        return {"path": self.path, "start_line": self.start_line, "end_line": self.end_line}


def is_trivial_line(line: str) -> bool:
    return bool(_TRIVIAL_LINE_RE.match(line.strip()))


def line_range_problem(lines: Sequence[str], start: int, end: int) -> Literal["range", "trivial"] | None:
    """줄 범위가 파일 안이고 실제 내용이 있는가. 맞으면 None."""

    if start < 1 or end < start or end > len(lines):
        return "range"
    if all(is_trivial_line(line) for line in lines[start - 1 : end]):
        return "trivial"
    return None


def normalize_path(raw: str) -> str:
    """인용 경로를 비교할 꼴로 — 앞뒤 공백, `\\`, 앞의 `./` 를 걷는다. 절대 경로(`/…`)는 그대로 둬 맞지 않게 한다
    (박제본 대조 `selfloop.RepoTools.resolve` 가 루트 밖으로 거절하는 것과 같다)."""

    return raw.strip().replace("\\", "/").removeprefix("./")


def citation_problem(files: Mapping[str, Sequence[str]], citation: Citation) -> CitationProblem | None:
    """보낸 소스(정규화한 경로 → 줄들)에서 인용 하나를 확인한다. 맞으면 None."""

    lines = files.get(normalize_path(citation.path))
    if lines is None:
        return "path"
    return line_range_problem(lines, citation.start_line, citation.end_line)
