"""개인정보처리방침의 시행일(#803) — 시행일 전에는 새 위탁·국외 이전이 생기지 않게 한다.

방침 5·6항에 Anthropic, PBC(미국)를 더한 개정은 `settings.PRIVACY_POLICY_EFFECTIVE_DATE` 에 시행한다
(시행일 7일 전 공지, 방침 12항). 강의실 「Claude(Anthropic) 키」 연결은 제출 소스를 그 회사로 보내므로
**시행일 0시(한국 시간) 전에는 저장할 수 없다** — 고지 없는 국외 이전이 생기지 않게. 시행일이 지나면
저절로 열린다. 시계는 `core.clock.Clock` 이라 시험은 `ClockOverride` 로 앞뒤를 가른다.

**이 날짜는 방침 화면의 현재 판 시행일이 아니다**(#897). 화면의 현재 판(완성도 채점을 6항 이전 목적에 더한 개정)은
병합일+7일에 시행하고, 이 설정은 «Anthropic 이전을 더한 개정(#803)의 시행일» 그대로 둔다 — 옮기면 열린 키
저장이 다시 잠긴다. 화면은 그 날짜를 `ANTHROPIC_TRANSFER_EFFECTIVE_ISO` 로 따로 들고 시험이 같은 값인지 지킨다.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.conf import settings

from .clock import Clock

_KST = ZoneInfo("Asia/Seoul")


def effective_date():
    return settings.PRIVACY_POLICY_EFFECTIVE_DATE


def anthropic_key_connection_open() -> bool:
    """Claude(Anthropic) 키 연결을 저장할 수 있는가 — 시행일 0시(KST) 이후만 참."""

    opens_at = datetime.combine(effective_date(), time.min, tzinfo=_KST)
    return Clock.now() >= opens_at


def anthropic_key_connection_opens_label() -> str:
    d = effective_date()
    return f"{d.year}년 {d.month}월 {d.day}일"
