"""과제 개최 자격 화면(#206) e2e 전용 — 자격을 줄 대상 Sponsor 계정을 멱등하게 만든다.

`seed_e2e_operator.py`와 같은 관용구(멱등: 있으면 그대로 재사용, 없으면 만든다)를
쓰지만, 대상은 Operator가 아니라 **소셜 로그인으로 들어온 참가자**다. Assignment
개최 자격은 SponsorProfile의 플래그이고 SponsorProfile은 지연 생성이므로(#206),
이 명령은 SponsorProfile을 미리 만들지 않는다 — 그건 정확히 부여 API
(`accounts.assignment_permission_services.grant_assignment_permission`)가 검증해야
할 경로("아직 SponsorProfile이 없는 사용자에게도 자격을 줄 수 있다")이기 때문이다.

고정된 provider_uid로 카카오 소셜 로그인을 반복 호출한다 — `accounts.api.
social_login`의 (provider, provider_uid) 조회가 이미 멱등하므로(있으면 그
User를, 없으면 새로 만든다), 이 명령도 몇 번을 불러도 같은 사용자명을 돌려준다.
username은 `accounts.api._username_for`가 짓는 `"kakao:<uid>"` 형태 그대로다 —
e2e 스펙이 운영자 화면의 "사용자명" 입력칸에 그대로 타이핑할 수 있다.

배포 환경에서는 돌지 않는다 — `seed_e2e_operator.py`와 같은 이유(e2e 전용 고정
계정을 만드는 명령이 운영 이미지에 남아 있으면 안 된다).
"""

from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

SOCIAL_LOGIN_URL = "/api/auth/social/kakao/login"

# 고정 값 — 반복 호출해도 항상 같은 (provider, provider_uid)로 귀결되어야
# 이 명령이 멱등하다.
PROVIDER_UID = "e2e-assignment-permission-sponsor"
EMAIL = "e2e-assignment-permission-sponsor@example.com"


class Command(BaseCommand):
    help = "과제 개최 자격 화면 e2e가 자격을 줄 대상으로 쓸 Sponsor 계정을 멱등하게 만든다."

    def handle(self, *args, **options) -> None:
        if settings.IS_DEPLOYED_ENVIRONMENT:
            raise CommandError(
                f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 인데 "
                "이 명령을 실행하려 했다 — seed_e2e_assignment_permission_sponsor 는 "
                "e2e 전용이라 배포 환경에서 실행할 수 없다."
            )

        client = Client()
        response = client.post(
            SOCIAL_LOGIN_URL,
            data={"access_token": f"{PROVIDER_UID}:{EMAIL}"},
            content_type="application/json",
        )
        if response.status_code != 200:
            raise CommandError(f"소셜 로그인에 실패했다: {response.status_code} {response.content!r}")

        pair = response.json()
        me = client.get(
            "/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {pair['access']}"
        )
        if me.status_code != 200:
            raise CommandError(f"/api/accounts/me 조회에 실패했다: {me.status_code}")

        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — 다른 seed_e2e_* 명령과 같은 관용구.
        self.stdout.write(json.dumps({"username": me.json()["username"]}))
