"""휴대폰 번호 정규화·검증 (#51 코드리뷰 지적 4).

알리고(Aligo) 발송 API의 `receiver` 파라미터는 콤마로 여러 수신자를 한 번에
지정하는 필드다 — 검증 없이 그대로 벤더에 넘기면, 값 하나에 콤마가 섞여 들어온
경우(오염된 입력, 혹은 미래의 어떤 호출자의 실수) 한 통이 최대 1000명에게
팬아웃될 수 있다. 여기서 숫자(와 international `+`) 외의 모든 문자를 걷어내므로
콤마·하이픈·공백이 전부 사라지고, 마지막에 국내 휴대폰 형식만 통과시킨다.
"""

from __future__ import annotations

import re

# 대한민국 휴대폰 번호: 010/011/016/017/018/019 + 7~8자리. 그 외 형식(유선전화,
# 해외 번호)은 이 프로젝트의 통지 대상이 아니다 — 필요해지면 그때 넓힌다.
_MOBILE_RE = re.compile(r"^01[0-9][0-9]{7,8}$")


class InvalidPhoneNumberError(ValueError):
    """정규화 후에도 국내 휴대폰 번호 형식이 아닐 때."""


def normalize_phone_number(raw: str) -> str:
    """자유 형식 입력을 알리고가 기대하는 숫자만 남은 국내 형식으로 정규화한다.

    하이픈(`010-1234-5678`)·공백·국가코드(`+82 10-1234-5678`, `82-10-...`)를
    전부 받아들이고, 숫자와 선행 `+` 외의 모든 문자(콤마 포함)를 제거한다 —
    이 제거 자체가 다중 수신자 콤마 인젝션을 원천 차단하는 방어선이다. 결과가
    국내 휴대폰 번호 형식이 아니면 `InvalidPhoneNumberError`를 던진다 — 조용히
    잘못된 값을 저장하지 않는다.
    """

    digits = re.sub(r"[^0-9+]", "", raw or "")

    if digits.startswith("+82"):
        digits = "0" + digits[3:]
    elif digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]

    digits = digits.lstrip("+")

    if not _MOBILE_RE.match(digits):
        raise InvalidPhoneNumberError(f"올바른 국내 휴대폰 번호 형식이 아니다: {raw!r}")

    return digits
