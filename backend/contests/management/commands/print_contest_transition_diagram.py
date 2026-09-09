"""Contest 전이 그래프의 mermaid 다이어그램을 표준출력으로 낸다 (#257).

`docs/features/backend.md` 의 「Contest 의 상태」 절에 붙는 코드 블록이 이 명령의
출력과 **글자 그대로** 같아야 한다 — 선언(`contests/transitions.py`)이 바뀌어 다이어그램이
낡으면 이 명령을 다시 돌려 그 자리를 통째로 바꿔 넣는다. `tests/test_contest_transition_
graph.py` 가 CI 에서 같은 비교를 자동으로 한다 — 이 명령은 사람이 손으로 그 결과를
문서에 옮길 때 쓰는 것뿐이다.

`export_openapi_schema` 와 같은 이유로 DB 접속이 필요 없다 — `contests.transitions` 의
선언은 순수 파이썬 값이다.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from contests.transitions import contest_transition_diagram


class Command(BaseCommand):
    help = "Contest 전이 그래프의 mermaid stateDiagram-v2 텍스트를 표준출력으로 낸다."

    def handle(self, *args, **options) -> None:
        self.stdout.write(contest_transition_diagram())
