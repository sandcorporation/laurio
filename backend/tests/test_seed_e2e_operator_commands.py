"""운영자 앱 e2e 전용 시드 명령 둘의 안전장치 (코드리뷰 지적, ADR-0018/0019).

- `seed_e2e_operator`: 이미 있는 계정을 아무거나 Operator로 승격시키면 안 된다
  (서로소 불변식, ADR-0018) — `backend/tests/test_operators.py`가 부트스트랩
  명령(`create_operator`)에 대해 치는 것과 같은 불변식을, 이 멱등 시드 명령에
  대해서도 친다.
- `seed_e2e_operator_queues`: 배포 환경에서 돌면 안 되고(실제 데이터를 만들거나
  `--clear`로 지운다), `--clear`는 이 명령이 심은 데이터에만 한정돼야 한다.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from accounts.models import DeveloperProfile, SocialAccount, SponsorProfile
from appeals.models import Appeal
from contests.models import Category, Contest, DeliverableType
from django.contrib.auth import get_user_model
from submissions.models import Submission


def _social_login(client, uid="dev-1", email="dev@example.com"):
    return client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )


# --- seed_e2e_operator — 서로소 불변식 ------------------------------------------


@pytest.mark.django_db
def test_seed_e2e_operator_refuses_to_promote_an_existing_participant(client):
    """참가자 → 운영자 방향(ADR-0018) — test_operators.py의 부트스트랩 명령
    테스트와 같은 불변식을 멱등 시드 명령에 대해서도 확인한다."""

    assert _social_login(client, uid="seed-e2e-participant-1").status_code == 200
    participant = SocialAccount.objects.get(provider_uid="seed-e2e-participant-1").user

    with pytest.raises(CommandError) as exc:
        call_command("seed_e2e_operator", username=participant.username)

    assert "소셜" in str(exc.value), str(exc.value)
    participant.refresh_from_db()
    assert participant.is_staff is False


@pytest.mark.django_db
def test_seed_e2e_operator_is_idempotent_for_an_operator_it_already_made():
    """정상 경로 — 반복 실행은 여전히 돼야 한다(비밀번호·등급 갱신이 이 명령의
    핵심 목적이다)."""

    call_command("seed_e2e_operator", username="seed-e2e-op-idempotent", password="first-pw-9134-xyz")
    call_command(
        "seed_e2e_operator",
        username="seed-e2e-op-idempotent",
        password="second-pw-9134-xyz",
        superuser=True,
    )

    operator = get_user_model().objects.get(username="seed-e2e-op-idempotent")
    assert operator.is_staff is True
    assert operator.is_superuser is True
    assert operator.check_password("second-pw-9134-xyz")


@pytest.mark.django_db
def test_seed_e2e_operator_refuses_to_run_in_a_deployed_environment():
    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, LAURIO_DEPLOYMENT_TARGET="staging"):
        with pytest.raises(CommandError):
            call_command("seed_e2e_operator", username="seed-e2e-op-deployed-guard")

    assert not get_user_model().objects.filter(username="seed-e2e-op-deployed-guard").exists()


# --- seed_e2e_operator_queues — 배포 환경 거부 + 삭제 범위 ----------------------


@pytest.mark.django_db
def test_seed_e2e_operator_queues_refuses_to_run_in_a_deployed_environment():
    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, LAURIO_DEPLOYMENT_TARGET="production"):
        with pytest.raises(CommandError):
            call_command("seed_e2e_operator_queues", only="appeal")


@pytest.mark.django_db
def test_seed_e2e_operator_queues_clear_refuses_to_run_in_a_deployed_environment():
    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, LAURIO_DEPLOYMENT_TARGET="production"):
        with pytest.raises(CommandError):
            call_command("seed_e2e_operator_queues", clear=True)


def _make_unrelated_pending_appeal(uid: str) -> Appeal:
    """이 명령이 전혀 모르는, 제목 접두어가 다른 pending Appeal 하나를 직접
    ORM으로 만든다 — `--clear`가 자기 것이 아닌 데이터를 건드리지 않는지 확인하는
    대조군이다."""

    User = get_user_model()
    sponsor_user = User.objects.create_user(username=f"unrelated-sponsor-{uid}")
    developer_user = User.objects.create_user(username=f"unrelated-dev-{uid}")
    SponsorProfile.objects.create(user=sponsor_user)
    developer = DeveloperProfile.objects.create(user=developer_user)

    category = Category.objects.create(name=f"무관한 카테고리 {uid}")
    deliverable_type = DeliverableType.objects.create(
        name=f"무관한 산출물 {uid}", minimum_prize=100_000
    )
    contest = Contest.objects.create(
        sponsor=sponsor_user.sponsor_profile,
        title=f"이 명령과 무관한 공모전 {uid}",
        category=category,
        prize=1_000_000,
        deadline_at=timezone.now(),
        status=Contest.Status.CLOSED,
    )
    contest.deliverable_types.add(deliverable_type)

    submission = Submission.objects.create(
        contest=contest, developer=developer, source_object_key=f"unrelated/{uid}/source"
    )
    return Appeal.objects.create(
        submission=submission, reason="이 명령과 무관한 이의", status=Appeal.Status.PENDING
    )


@pytest.mark.django_db
def test_clear_only_removes_appeals_from_contests_this_command_made():
    """삭제 범위가 이 명령이 만든 Contest(TITLE_PREFIX)로 좁혀져 있는지 —
    무관한 pending Appeal은 --clear 뒤에도 그대로 남아야 한다(코드리뷰 지적)."""

    unrelated = _make_unrelated_pending_appeal("clear-scope-1")

    call_command("seed_e2e_operator_queues", only="appeal")
    assert Appeal.objects.filter(status=Appeal.Status.PENDING).count() >= 2

    call_command("seed_e2e_operator_queues", clear=True)

    # 이 명령이 심은 pending Appeal은 사라지고, 무관한 것은 그대로 남는다.
    remaining = Appeal.objects.filter(status=Appeal.Status.PENDING)
    assert list(remaining) == [unrelated]
    unrelated.refresh_from_db()  # ProtectedError 등으로 조용히 깨지지 않았는지도 함께 확인.
