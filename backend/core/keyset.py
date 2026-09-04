"""커서(keyset) 페이지네이션 (#151).

오프셋(`?page=N`)은 목록이 **머리 쪽에서** 자라면 조용히 틀린다 — 1페이지를 읽은 뒤 새 행이
하나 생기면 경계가 한 칸 밀려서, 2페이지가 1페이지의 마지막 행을 다시 돌려주고 원래 그
자리에 와야 했던 행은 어느 페이지에도 안 나온다. 운영자 지급 큐가 가장 먼저 걸렸다:
스캔이 60초마다 Payout 을 확정해 계속 머리에 행을 넣으므로, 운영자가 「더 보기」를 누르는
그 몇 초 사이에 실제로 일어난다.

커서는 「몇 번째부터」가 아니라 **「마지막으로 본 행 다음부터」**를 묻는다. 앞이 자라도
그 기준점은 흔들리지 않는다.

**정렬 키와 커서가 같은 것을 가리켜야 한다.** 여기 커서는 `(created_at, id)` 이고, 이
모듈을 쓰는 질의는 반드시 `-created_at, -id` 로 정렬해야 한다 — 동점에서 순서가 흔들리면
커서로 바꾼 의미가 없다(그게 오프셋의 결함 중 하나였다).

커서 문자열은 **URL 로 오는 사용자 조작 가능한 입력**이다. 잘리거나 손대졌거나 옛 형식일
수 있고, 그때 500 이 아니라 「모르는 커서」로 답해야 한다 — 목록 화면이 죽으면 운영자는
「밀린 일이 없다」와 「화면이 깨졌다」를 구별할 수 없다.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime

# base64 로 감싸는 것은 비밀로 하기 위해서가 아니라(내용은 그대로 읽힌다) **손으로 조립하는
# 형태로 두지 않기 위해서**다. 사람이 URL 에 `?after=2026-09-04T...|42` 를 직접 적기 시작하면
# 그 형식이 곧 계약이 되어 바꿀 수 없다.
_SEPARATOR = "|"


def encode_cursor(created_at: datetime, row_id: int) -> str:
    raw = f"{created_at.isoformat()}{_SEPARATOR}{row_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(raw: str | None) -> tuple[datetime, int] | None:
    """읽을 수 없으면 None 이다 — 예외를 던지지 않는다(모듈 docstring 참고)."""

    if not raw or not raw.strip():
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if _SEPARATOR not in decoded:
        return None
    moment_text, _, id_text = decoded.rpartition(_SEPARATOR)
    try:
        moment = datetime.fromisoformat(moment_text)
    except ValueError:
        return None
    try:
        row_id = int(id_text)
    except ValueError:
        return None
    return moment, row_id


def after_cursor_q(cursor: tuple[datetime, int]):
    """`-created_at, -id` 정렬에서 이 커서 **다음** 행들을 고르는 Q.

    「같은 시각이면 id 가 더 작은 것」까지 포함해야 한다 — 그러지 않으면 동점 그룹의
    나머지가 통째로 건너뛰어진다. 오프셋이 동점에서 흔들리던 것과 정확히 같은 자리다.
    """

    from django.db.models import Q

    created_at, row_id = cursor
    return Q(created_at__lt=created_at) | Q(created_at=created_at, id__lt=row_id)


def keyset_page(queryset, *, after: str | None, page_size: int):
    """`(items, next_cursor)` — 한 페이지와, 더 있으면 다음 커서.

    `page_size + 1` 을 읽어 「더 있는가」를 **행의 존재로** 판정한다. 전체 건수와 받은 수를
    비교하는 방식은 목록이 자라는 동안 틀린다(그게 이 티켓이 고치는 증상 중 하나다).

    읽을 수 없는 커서는 호출부가 먼저 4xx 로 막는다 — 여기서 조용히 처음부터 돌려주면
    사용자는 「더 보기」를 눌렀는데 1페이지로 되돌아간 화면을 본다.
    """

    cursor = decode_cursor(after) if after else None
    if cursor is not None:
        queryset = queryset.filter(after_cursor_q(cursor))

    rows = list(queryset[: page_size + 1])
    if len(rows) <= page_size:
        return rows, None
    last = rows[page_size - 1]
    return rows[:page_size], encode_cursor(last.created_at, last.id)
