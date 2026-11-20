"""커서(keyset) 페이지네이션 (#151).

오프셋은 목록이 **머리 쪽에서** 자라면 경계가 밀린다 — 2페이지가 1페이지의 마지막 행을
다시 돌려주고, 원래 그 자리에 와야 했던 행은 어느 페이지에도 안 나온다. 운영자 지급 큐가
가장 먼저 걸리는 이유는 스캔이 60초마다 Payout 을 확정해 계속 머리에 행을 넣기 때문이다.

커서는 「몇 번째부터」가 아니라 **「마지막으로 본 행 다음부터」**를 묻는다. 그래서 앞이
자라도 경계가 흔들리지 않는다.

커서 문자열은 **사용자가 조작할 수 있는 입력**이다 — 잘리거나, 손대졌거나, 옛 형식일 수
있다. 그 경우 500 이 아니라 「모르는 커서」로 답해야 한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.keyset import decode_cursor, encode_cursor


def test_a_cursor_round_trips():
    moment = datetime(2026, 9, 4, 11, 22, 33, 456789, tzinfo=timezone.utc)

    assert decode_cursor(encode_cursor(moment, 42)) == (moment, 42)


def test_a_cursor_survives_a_time_without_microseconds():
    """마이크로초가 0 인 시각도 같은 값으로 돌아온다 — 직렬화가 그 자리를 떨어뜨리면
    경계에서 한 행이 새거나 빠진다."""

    moment = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    assert decode_cursor(encode_cursor(moment, 1)) == (moment, 1)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not-base64!!",
        # base64 이지만 우리 형식이 아니다.
        "aGVsbG8=",
        # 우리 형식인데 id 가 정수가 아니다.
        "MjAyNi0wOS0wNFQxMTowMDowMCswMDowMHxhYmM=",
        # 우리 형식인데 시각이 시각이 아니다.
        "bm90LWEtdGltZXwx",
        # 구분자가 없다.
        "MjAyNi0wOS0wNFQxMTowMDowMCswMDowMA==",
    ],
)
def test_a_cursor_we_cannot_read_is_none_not_an_exception(raw):
    """읽을 수 없는 커서는 예외가 아니라 None 이다 (#151).

    이 값은 URL 로 오는 **사용자 조작 가능한 입력**이다. 파싱 실패가 예외로 새면 목록
    화면이 500 을 내고, 운영자는 「밀린 일이 없다」와 「화면이 죽었다」를 구별할 수 없다.
    """

    assert decode_cursor(raw) is None


def test_a_cursor_is_opaque_enough_not_to_be_hand_written():
    """커서를 사람이 손으로 조립하는 형태로 두지 않는다 — 그러면 그 형식이 곧 계약이
    되어 바꿀 수 없다. 인코딩 결과에 원본 시각 문자열이 그대로 보이면 안 된다."""

    encoded = encode_cursor(datetime(2026, 9, 4, tzinfo=timezone.utc), 7)

    assert "2026-09-04" not in encoded
