"""e2e 전용 관리 명령이 배포 환경에서 멈추는 한 자리(#1086 — `appeals` 시드 명령에서 옮겼다, 공모전·이의 명령이 같이 쓴다).
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import CommandError


def refuse_in_deployed_environment(command_name: str) -> None:
    # 이 명령은 실제 Contest·Payment·Payout을 만들고(--clear는 그것도 모자라
    # 지운다) 운영 이미지에 그대로 들어간다 — ADR-0019가 Django admin을 내린
    # 이유(행을 직접 편집·삭제할 수 있으면 감사 추적에 우회로가 남는다)가 여기도
    # 그대로 적용된다. dev·CI(IS_DEPLOYED_ENVIRONMENT가 아닌 곳)에서만 돈다 —
    # config/settings.py의 다른 배포 가드들과 같은 판정 기준이다.
    if settings.IS_DEPLOYED_ENVIRONMENT:
        raise CommandError(
            f"CODEMIT_DEPLOYMENT_TARGET={settings.CODEMIT_DEPLOYMENT_TARGET} 인데 "
            # **이름을 인자로 받는다.** 이 헬퍼는 세 명령이 함께 쓰는데, 메시지가
            # 자기 이름을 하드코딩하고 있어서 `prune_e2e_junk` 를 staging 에서 친
            # 사람에게 「seed_e2e_operator_queues 가 거부됐다」고 말했다 — HTTP
            # 입구(core/api.py)는 이 문자열을 그대로 422 본문으로 내보낸다.
            f"이 명령을 실행하려 했다 — {command_name} 는 e2e 전용이라 "
            "배포 환경에서 실행할 수 없다(실제 데이터를 만들거나 지운다)."
        )
