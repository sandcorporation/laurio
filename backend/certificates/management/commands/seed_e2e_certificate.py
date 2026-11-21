"""받는 사람 상장 e2e(#1130)용 — 마감된 무료 공모전 하나, 그 공모전에 제출한 개발자 하나, 그에게 발급한
상장 하나를 심고 `{developer_uid, certificate_id, number, token}` JSON 을 마지막 줄에 찍는다.

개최·제출·마감은 ORM 으로 바로 만들고 발급만 실제 서비스(`issue_certificates`)로 한다 — PDF 를 그리고
저장소에 올리는 길까지 e2e 가 걷게 하려는 것이다. 호출마다 새 행만 만들고 이름이 `run_id` 로 갈린다.
제목이 `[E2E` 로 시작하면 안 된다 — `seed_e2e_contests` 가 그 접두어의 공모전을 통째로 지우는데(`[E2E-…]`
도 잡힌다), 상장이 공모전을 PROTECT 로 잡고 있어 그 정리가 통째로 깨진다(e2e 에서 실제로 겪었다).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import DeveloperProfile, SocialAccount, SponsorProfile
from contests.models import Category, Contest, ContestSubmission, DeliverableType, Requirement
from core.management.stdout_utf8 import write_stdout_utf8

from certificates.rendering import CertificateText
from certificates.services import IssueRequest, issue_certificates


def _user(username: str):
    user = get_user_model().objects.create_user(username=username, email=f"{username}@example.invalid")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    return user


class Command(BaseCommand):
    help = "마감된 공모전 하나와 그 제출자에게 발급한 상장 하나를 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--run-id", default="", help="이름을 가르는 실행 표식")

    def handle(self, *args, **options) -> None:
        run_id = options["run_id"] or uuid.uuid4().hex[:8]
        tag = f"{run_id}-{uuid.uuid4().hex[:6]}"

        sponsor_user = _user(f"e2e-cert-host-{tag}")
        sponsor = SponsorProfile.objects.create(user=sponsor_user, display_name="E2E 상장 개최자")
        developer_uid = f"e2e-cert-dev-{tag}"
        developer_user = _user(developer_uid)
        # `social_login` 은 (provider, provider_uid) 로 사용자를 찾는다 — e2e 가 이 uid 로 로그인하면 이 계정이 된다.
        SocialAccount.objects.create(
            user=developer_user,
            provider=SocialAccount.Provider.KAKAO,
            provider_uid=developer_uid,
            email=f"{developer_uid}@example.invalid",
        )
        developer = DeveloperProfile.objects.create(user=developer_user, display_name="E2E 상장 받는 사람")

        category = Category.objects.create(name=f"[E2E] 상장 {tag}")
        deliverable_type = DeliverableType.objects.create(name=f"[E2E] 상장 {tag}", minimum_prize=0)
        title = f"E2E-CERT 상장 공모전 {tag}"
        # 시드는 마감된 공모전을 바로 심는다 — 변수로 넘기는 것은 `seed_e2e_contests._contest` 와 같은 경계다
        # (`contests/tests/test_contest_status_writes_are_declared.py` 가 리터럴 생성만 CREATION_STATES 로 묶는다).
        status = Contest.Status.CLOSED
        contest = Contest.objects.create(
            sponsor=sponsor,
            title=title,
            category=category,
            description="상장 e2e 용 마감된 무료 공모전입니다.",
            prize=0,
            deadline_at=timezone.now() - timedelta(days=1),
            status=status,
            is_free=True,
        )
        contest.deliverable_types.set([deliverable_type])
        Requirement.objects.create(contest=contest, text="할 일을 추가할 수 있다", grade="required", order=0)
        submission = ContestSubmission.objects.create(
            user=developer_user, product=ContestSubmission.Product.CONTEST, contest=contest, developer=developer
        )

        [certificate] = issue_certificates(
            contest=contest,
            issuer=sponsor_user,
            requests=[
                IssueRequest(
                    submission_id=submission.id,
                    text=CertificateText(
                        award_name="최우수상",
                        recipient_name="상장받는사람",
                        body="위 사람은 뛰어난 완성도로 우수한 성과를 거두었기에 이 상장을 수여합니다.",
                        giver_name="이개최",
                        giver_title="심사위원장",
                        award_date=timezone.localdate(),
                    ),
                )
            ],
        )
        payload = {
            "developer_uid": developer_uid,
            "certificate_id": certificate.id,
            "number": certificate.number,
            "token": certificate.token,
            "contest_title": title,
        }
        write_stdout_utf8(self.stdout, json.dumps(payload, ensure_ascii=False) + "\n")
