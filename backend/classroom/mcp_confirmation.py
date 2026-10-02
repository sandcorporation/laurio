"""되돌릴 수 없는 도구의 확인 표 (#515, spec #511 「두 단계 확인」, ADR-0052).

연결된 앱이 문제·클래스를 지우거나 참여자를 내보내거나 템플릿을 공개하려 하면, 첫 호출은
실행하지 않고 **무엇이 사라지거나 나가는가**의 미리보기와 확인 표를 돌려준다. 같은 도구를
같은 인자에 `confirmation` 만 더해 다시 부르면 그때 실행된다 — AI 의 한 번 실수로 지워지지
않게, 그리고 모델이 미리보기를 강사에게 보여 줄 틈을 두려고.

**표가 묶이는 것**: 그 연결된 앱(`ConnectedApp`) · 그 도구 이름 · 표를 뺀 인자 전부(대상
번호가 인자에 있으므로 곧 그 대상)· `CONFIRMATION_TTL` 안. 표는 저장하지 않고 SHA-256
해시만 둔다(`ConnectedAppConfirmation`). 서명이 아니라 서버에 저장하는 이유는 「한 번만」을
지키려면 어차피 서버가 쓴 표를 기억해야 하기 때문이다.

**한 번만**: 실행에 쓰이면 같은 트랜잭션에서 `used_at` 이 찍힌다. 행을 `select_for_update`
로 잡으므로 같은 표를 동시에 두 번 내도 하나만 실행된다. 실행이 화면과 같은 이유로 거절되면
(확인 사이에 참여자가 냈다 등) 쓰기와 함께 표 사용도 되돌아간다 — 그 표는 여전히 그 대상·그
인자·남은 시간에만 쓰이고, 거절 사유가 그대로면 다시 내도 같은 이유로 거절된다.

시각은 `Clock.now()` 다 — 시험이 시계를 옮겨 만료를 본다.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta

from core.clock import Clock

from .mcp_tool import ToolInputError
from .models import ConnectedApp, ConnectedAppConfirmation

#: 확인 표의 수명 — 미리보기를 읽고 강사에게 묻고 다시 부르기에 넉넉하되, 오래 남아 엉뚱한
#: 때에 쓰이지 않을 만큼.
CONFIRMATION_TTL = timedelta(minutes=5)

#: 인자 이름 — 모든 위험 도구가 같은 이름을 쓴다.
CONFIRMATION_ARGUMENT = "confirmation"

CONFIRMATION_SCHEMA = {
    "type": "string",
    "description": (
        "확인 표. 처음에는 넣지 않는다 — 그러면 실행하지 않고 미리보기와 확인 표를 돌려준다. "
        "미리보기를 사용자에게 보여 주고 동의를 받은 뒤, 같은 인자에 이 값만 더해 다시 부르면 실행된다. "
        "한 번만, 같은 대상·같은 인자에만, 5분 안에만 쓸 수 있다."
    ),
}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _arguments_digest(arguments: dict) -> str:
    bound = {key: value for key, value in arguments.items() if key != CONFIRMATION_ARGUMENT}
    canonical = json.dumps(bound, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def presented(arguments: dict) -> str | None:
    """인자에 확인 표가 실려 왔으면 그 값을, 아니면 None 을."""

    token = arguments.get(CONFIRMATION_ARGUMENT)
    if token is None:
        return None
    if not isinstance(token, str) or not token:
        raise ToolInputError(f"{CONFIRMATION_ARGUMENT} 는 미리보기가 돌려준 문자열이어야 합니다.")
    return token


def issue(grant: ConnectedApp, tool: str, arguments: dict) -> tuple[str, datetime]:
    """새 확인 표를 낸다 — (표, 만료 시각). 이 앱의 만료된 표는 이때 걷는다."""

    now = Clock.now()
    ConnectedAppConfirmation.objects.filter(connected_app=grant, expires_at__lte=now).delete()
    token = secrets.token_urlsafe(24)
    expires_at = now + CONFIRMATION_TTL
    ConnectedAppConfirmation.objects.create(
        connected_app=grant,
        tool=tool,
        arguments_digest=_arguments_digest(arguments),
        token_hash=_hash(token),
        created_at=now,
        expires_at=expires_at,
    )
    return token, expires_at


_AGAIN = "확인 표 없이 다시 불러 새 미리보기를 받으세요."


def redeem(grant: ConnectedApp, tool: str, arguments: dict, token: str) -> None:
    """표를 쓴다 — 맞지 않으면 `ToolInputError`(도구 오류)로 거절한다. 호출부는 디스패치의
    트랜잭션 안에 있다(`classroom.mcp._call_tool`)."""

    row = (
        ConnectedAppConfirmation.objects.select_for_update()
        .filter(connected_app=grant, token_hash=_hash(token))
        .first()
    )
    if row is None:
        raise ToolInputError(f"확인 표가 올바르지 않습니다. {_AGAIN}")
    if row.used_at is not None:
        raise ToolInputError(f"이미 쓴 확인 표입니다. {_AGAIN}")
    now = Clock.now()
    if row.expires_at <= now:
        raise ToolInputError(f"확인 표가 만료됐습니다. {_AGAIN}")
    if row.tool != tool or row.arguments_digest != _arguments_digest(arguments):
        raise ToolInputError(f"이 확인 표는 다른 도구나 다른 대상·인자로 받은 것입니다. {_AGAIN}")
    row.used_at = now
    row.save(update_fields=["used_at"])


def needs_confirmation(grant: ConnectedApp, tool: str, arguments: dict, preview: dict) -> dict:
    """미리보기 결과의 모양 — 도구 넷이 같은 봉투를 쓴다."""

    token, expires_at = issue(grant, tool, arguments)
    return {
        "status": "needs_confirmation",
        "preview": preview,
        "confirmation": token,
        "expires_at": expires_at.isoformat(),
        "how_to_confirm": (
            "아직 아무것도 바뀌지 않았다. 이 미리보기를 사용자에게 보여 주고 동의를 받으면, 같은 도구를 "
            f"같은 인자에 confirmation 만 더해 {int(CONFIRMATION_TTL.total_seconds() // 60)}분 안에 다시 부른다."
        ),
    }
