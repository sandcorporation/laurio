"""Assignment 4(#208, ADR-0028/0029) e2e 전용 — 과제 개최 자격을 가진 Sponsor 와
그 과제에 낼 학생 계정을 멱등하게 만든다.

`seed_e2e_assignment_permission_sponsor.py`(#206)가 Sponsor **후보**(자격을 아직
받지 않은 계정)를 만드는 것과 달리, 이 명령은 그 계정을 재사용해 실제로
`AssignmentPermission`을 부여까지 마친 상태로 되돌린다 — #208의 화면(과제 만들기·
InviteCode 입력·제출)을 걷는 e2e 는 "자격을 받는 과정"이 아니라 "자격을 이미
가진 강사"를 전제로 하기 때문이다(자격 부여 자체는 #206 이 이미 검증했다).

**세 단계를 순서대로, 전부 in-process `call_command`/`Client`로 한다** — 서브프로세스는
쓰지 않는다(#156 이후 원칙, `core/e2e_seeds.py` 참고):

1. `seed_e2e_assignment_permission_sponsor` — Sponsor 후보 계정(고정 (provider,
   provider_uid)).
2. `seed_e2e_operator --superuser` — 자격을 부여할 상위 등급 Operator(고정 계정,
   `seed_e2e_operator.py`의 기본값을 그대로 쓴다).
3. `POST /api/operator/assignment-permissions/grant` — 이미 부여돼 있으면(재실행)
   409 를 **성공으로 취급한다** — 멱등의 실제 구현이다.

학생 계정도 고정된 (provider, provider_uid)로 소셜 로그인해 만든다 — Assignment 는
본인확인을 요구하지 않으므로(ADR-0029) 그 이상은 하지 않는다.

배포 환경에서는 돌지 않는다 — 다른 `seed_e2e_*` 명령과 같은 이유(e2e 전용 고정
계정을 만드는 명령이 운영 이미지에 남아 있으면 안 된다).
"""

from __future__ import annotations

import json
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client

SOCIAL_LOGIN_URL = "/api/auth/social/kakao/login"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_LOGIN_URL = "/api/operator/login"
OPERATOR_ORIGIN = "http://testserver"

STUDENT_PROVIDER_UID = "e2e-assignment-student"
STUDENT_EMAIL = "e2e-assignment-student@example.com"

OPERATOR_USERNAME = "e2e-operator"
OPERATOR_PASSWORD = "e2e-operator-pw-9134-xyz"


class Command(BaseCommand):
    help = (
        "과제(Assignment) e2e가 쓸 자격 있는 Sponsor 와 학생 계정을 멱등하게 만든다."
    )

    def handle(self, *args, **options) -> None:
        if settings.IS_DEPLOYED_ENVIRONMENT:
            raise CommandError(
                f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 인데 "
                "이 명령을 실행하려 했다 — seed_e2e_assignment_sponsor_and_student 는 "
                "e2e 전용이라 배포 환경에서 실행할 수 없다."
            )

        client = Client()

        # 1. Sponsor 후보 계정 — 이미 있는 커맨드를 그대로 부른다(로직을 두 벌
        # 두지 않는다). `call_command`는 기본적으로 stdout을 캡처해 돌려주지
        # 않으므로(`self.stdout`이 실제 sys.stdout으로 바인딩된다) `stdout=`으로
        # 명시적으로 받는다 — `tests/test_prune_e2e_junk.py._prune()`와 같은 관용구.
        sponsor_buffer = StringIO()
        call_command("seed_e2e_assignment_permission_sponsor", stdout=sponsor_buffer)
        sponsor_username = json.loads(sponsor_buffer.getvalue().strip().splitlines()[-1])["username"]

        # 2. 자격을 부여할 상위 등급 Operator.
        call_command("seed_e2e_operator", superuser=True)
        operator_login = client.post(
            OPERATOR_LOGIN_URL,
            data={"username": OPERATOR_USERNAME, "password": OPERATOR_PASSWORD},
            content_type="application/json",
            HTTP_ORIGIN=OPERATOR_ORIGIN,
        )
        if operator_login.status_code != 200:
            raise CommandError(
                f"Operator 로그인에 실패했다: {operator_login.status_code} {operator_login.content!r}"
            )

        # 3. 부여 — 이미 부여돼 있으면(재실행) 409 를 성공으로 취급한다(멱등).
        grant = client.post(
            GRANT_URL,
            data={"username": sponsor_username, "reason": "e2e 시드 — 과제 화면 검증"},
            content_type="application/json",
            HTTP_ORIGIN=OPERATOR_ORIGIN,
        )
        if grant.status_code not in (200, 409):
            raise CommandError(f"자격 부여에 실패했다: {grant.status_code} {grant.content!r}")

        # 4. 학생 계정 — Assignment 는 본인확인을 요구하지 않으므로(ADR-0029) 소셜
        # 로그인만으로 계정을 확보한다.
        student_login = client.post(
            SOCIAL_LOGIN_URL,
            data={"access_token": f"{STUDENT_PROVIDER_UID}:{STUDENT_EMAIL}"},
            content_type="application/json",
        )
        if student_login.status_code != 200:
            raise CommandError(
                f"학생 소셜 로그인에 실패했다: {student_login.status_code} {student_login.content!r}"
            )
        student_me = client.get(
            "/api/accounts/me",
            HTTP_AUTHORIZATION=f"Bearer {student_login.json()['access']}",
        )
        student_username = student_me.json()["username"]

        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — 다른 seed_e2e_* 명령과 같은 관용구.
        self.stdout.write(
            json.dumps({"sponsor_username": sponsor_username, "student_username": student_username})
        )
