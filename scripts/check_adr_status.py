#!/usr/bin/env python3
"""모든 ADR 이 `Status:` 줄을 갖고, 그 줄이 가리키는 ADR 이 실재하는지 검사한다.

**「표시가 없는 것」이 정보가 되려면 조용히 깨지지 않아야 한다.** 일부에만 붙어 있으면
표시 없는 ADR 이 「살아있다」인지 「아무도 안 고쳤다」인지 구별되지 않는다 — 그 구별이
이 규율의 전부이므로 기계가 지킨다.

ADR 템플릿은 이 저장소가 아니라 플러그인 스킬 안에 있어 저장소가 모양을 강제할 다른
수단이 없다. 그래서 검사가 유일한 문이다.

문법 (셋 중 하나, 날짜는 그 결정이 내려진 날):

    Status: Accepted (2026-08-28 결정)
    Status: Amended by ADR-0022, ADR-0027 (2026-08-28 결정)
    Status: Superseded by ADR-0031 (2026-08-28 결정)

의미:

- **Accepted** — 유효하다.
- **Amended by** — **여전히 유효하되** 일부가 뒤 ADR 로 확장·수정됐다. 지금 저장소의
  모든 개정 관계가 이것이다 — 개정된 ADR 들이 전부 자기 본문에서 「여전히 유효하다」를
  명시한다(ADR-0016 「ADR-0012의 세 보완책 중 둘은 여전히 유효하다」, ADR-0027 「이
  ADR은 ADR-0014를 대체하지 않는다」).
- **Superseded by** — 더 이상 유효하지 않다. 지금은 한 건도 없다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ADR_DIR = Path(__file__).resolve().parent.parent / "docs" / "adr"

STATUS_RE = re.compile(
    r"^Status: (?:Accepted|(?:Amended|Superseded) by (ADR-\d{4}(?:, ADR-\d{4})*))"
    r" \(\d{4}-\d{2}-\d{2} 결정\)$"
)


def main() -> int:
    files = sorted(ADR_DIR.glob("[0-9]*.md"))
    if not files:
        print(f"::error::{ADR_DIR} 에 ADR 이 하나도 없다 — 경로가 바뀌었는가?")
        return 1

    known = {f.name[:4] for f in files}
    problems: list[str] = []

    for f in files:
        lines = f.read_text().split("\n")
        status = next((l for l in lines[:6] if l.startswith("Status:")), None)
        if status is None:
            problems.append(
                f"{f.name}: 머리 6줄 안에 `Status:` 줄이 없다. "
                f"예: `Status: Accepted (YYYY-MM-DD 결정)`"
            )
            continue

        m = STATUS_RE.match(status)
        if m is None:
            problems.append(f"{f.name}: Status 줄의 모양이 다르다 — {status!r}")
            continue

        for ref in re.findall(r"ADR-(\d{4})", m.group(1) or ""):
            if ref not in known:
                problems.append(f"{f.name}: 없는 ADR 을 가리킨다 — ADR-{ref}")
            if ref == f.name[:4]:
                problems.append(f"{f.name}: 자기 자신을 가리킨다")

    for p in problems:
        print(f"::error::{p}")

    if problems:
        print(f"\nADR {len(files)}개 중 {len(problems)}건 문제.")
        return 1

    print(f"ADR {len(files)}개 전부 Status 줄이 있고 참조가 실재한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
