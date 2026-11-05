"""공모전의 연결된 앱 자원 (#870, ADR-0069).

OAuth 2.1 인가 서버의 몸은 `core.oauth` 에 있다. 여기에는 공모전 자원 하나 — 범위 `contests`,
공개 앱(frontend)의 오리진(`PUBLIC_WEB_ORIGIN`) — 와 「누가 이 자원을 쓸 수 있는가」가 있다.

**쓸 수 있는 사람**: 무료 공모전 개최 권한(`HostingPermission.is_granted`)이 켜진 사용자.
운영자(`is_staff`)도 같은 검사를 받는다(대표 결정 — 운영자는 다루는 범위만 넓다). 동의 단계와
MCP 호출마다 이 검사를 다시 한다 — 권한이 회수되면 그 순간부터 모든 호출이 거절된다.
"""

from __future__ import annotations

from core.models import ConnectedApp
from core.oauth import OAuthResource

from .models import HostingPermission

CONTESTS = OAuthResource(
    scope=ConnectedApp.Scope.CONTESTS,
    resource_name="Codemit 공모전",
    realm="codemit-contests",
    origin_setting="PUBLIC_WEB_ORIGIN",
)

NOT_ELIGIBLE = "무료 공모전 개최 권한이 있는 계정만 공모전 도구를 연결할 수 있습니다."


def may_host(user) -> bool:
    return HostingPermission.objects.filter(user=user, is_granted=True).exists()


def admission_refusal(grant: ConnectedApp) -> str | None:
    """MCP 호출마다 — 개최 권한이 꺼졌으면 거절한다."""

    return None if may_host(grant.instructor) else NOT_ELIGIBLE
