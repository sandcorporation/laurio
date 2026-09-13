"""Contest 전이 그래프에서 다이어그램을 내고, 그래프 자체의 모순을 잡는다 (#257).

#255·#256 이 전이를 한 곳에 모으고 그 밖을 막았다. 이 파일은 그 선언에서 **부산물**
둘을 낸다 — `docs/features/backend.md` 에 박아 둘 mermaid 다이어그램이 선언과 갈리지
않는지(첫 번째 테스트), 그리고 그래프 자체가 스스로 모순인 세 경우를
`contests.transitions.validate_contest_transition_graph()` 가 잡는지(나머지 셋)다.
다이어그램은 목표가 아니라 부산물이다 — #255/#256 없이 이것만 있으면 선언이 코드와
갈릴 수 있는 동안 그림이 코드가 아니라 선언만 그린다는 사실이 위험해진다.

세 그래프 검사의 실제 로직은 `contests.transitions.validate_contest_transition_graph`
에 산다 — 이 파일은 그 결과를 얇게 단언할 뿐이다(로직 한 곳, 검증 여러 곳이 아니라
로직도 한 곳).
"""

from __future__ import annotations

from pathlib import Path

from contests.transitions import contest_transition_diagram, validate_contest_transition_graph
from core.scans import SCAN_REGISTRY

BACKEND_MD = Path(__file__).resolve().parent.parent.parent / "docs" / "features" / "backend.md"


def _diagram_embedded_in_backend_md() -> str:
    """`docs/features/backend.md`의 「Contest 의 상태」 절에 박힌 mermaid 블록 본문."""

    text = BACKEND_MD.read_text(encoding="utf-8")
    section = text.split("## Contest 의 상태", 1)[1]
    fenced = section.split("```mermaid\n", 1)[1]
    body = fenced.split("```", 1)[0]
    return body.strip("\n")


def test_the_diagram_in_backend_md_is_not_stale():
    """다이어그램은 선언에서 낸다 — 손으로 그리지 않는다. 선언이 바뀌었는데
    `docs/features/backend.md` 를 안 고치면 여기서 빨개진다(다이어그램이 낡지
    않게 하는 장치, #257 AC). 재생성 명령은
    `cd backend && uv run python manage.py print_contest_transition_diagram`."""

    assert contest_transition_diagram() == _diagram_embedded_in_backend_md(), (
        "선언(contests.transitions)에서 낸 다이어그램이 docs/features/backend.md 에 "
        "박힌 것과 다르다 — `uv run python manage.py print_contest_transition_diagram` "
        "을 다시 돌려 그 문서의 코드 블록을 통째로 바꿔 넣는다."
    )


def test_no_unreachable_states():
    """도달 불가능한 상태 — 어느 간선으로도 닿을 수 없고 생성으로도 만들어지지 않는
    상태는 코드에 값만 있고 실제로는 존재하지 않는 상태다.

    **이 검사는 오늘 자명하게 통과한다** — 다섯 상태가 전부 도달 가능하다(CREATION_
    STATES 의 DRAFT 하나 + 네 간선의 to_state 가 덮는 나머지 넷). 그런데도 넣는 이유는
    **래칫**이기 때문이다: 나중에 상태를 하나 더할 때 전이를 안 붙이면 그 순간
    이 테스트가 빨개진다. 지금 무언가를 잡고 있는 게 아니다 — 다음 사람이 이 테스트가
    지금 뭔가를 지키고 있다고 오해하지 않게, 그 사실을 여기 적어 둔다.
    """

    result = validate_contest_transition_graph(scan_registry=SCAN_REGISTRY)

    assert not result.unreachable_states, result.problems


def test_no_time_based_edge_missing_from_the_scan_registry():
    """시각이 지나면 일어나야 하는 전이(`ScanContestTransition`)인데 어떤 스캔도
    그것을 돌지 않으면, 그 전이는 영원히 일어나지 않는다 — 그리고 아무도 오류를
    보지 못한다(beat 도 `/tick` 도 등록부만 보고 도니까, ADR-0003 의 뒷면)."""

    result = validate_contest_transition_graph(scan_registry=SCAN_REGISTRY)

    assert not result.unregistered_scan_edges, result.problems


def test_no_non_terminal_state_without_an_outgoing_edge():
    """끝 상태(`TERMINAL_STATES` — 선정 완료·심사기간 종료·과제 마감)는 나가는 길이
    없어도 정상이다. 그런데 **끝이 아닌데** 나가는 길이 없으면 그건 갇힌 것이다 —
    Contest 가 그 상태에 들어가면 영원히 못 나온다."""

    result = validate_contest_transition_graph(scan_registry=SCAN_REGISTRY)

    assert not result.stuck_states, result.problems
