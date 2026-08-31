"""운영자 앱 e2e 전용 시드 명령들의 안전장치 (코드리뷰 지적, ADR-0018/0019).

- `seed_e2e_operator`: 이미 있는 계정을 아무거나 Operator로 승격시키면 안 된다
  (서로소 불변식, ADR-0018) — `backend/tests/test_operators.py`가 부트스트랩
  명령(`create_operator`)에 대해 치는 것과 같은 불변식을, 이 멱등 시드 명령에
  대해서도 친다.
- `seed_e2e_operator_queues`: 배포 환경에서 돌면 안 되고(실제 데이터를 만들거나
  `--clear`로 지운다), `--clear`는 이 명령이 심은 데이터에만 한정돼야 한다.
- `seed_e2e_operator_queues._close_contest`: **이 Contest 하나만** CLOSED로
  전이시켜야 한다(#66 코드리뷰 지적, 심각). 예전 구현은 시계를 얼리고 전역
  `/api/internal/tick`을 태웠는데, 그 틱이 DB의 **모든** PUBLISHED Contest를
  스캔해 CLOSED/JUDGING_ENDED로 옮기고, 곧이어 부르는 scoring/run-pending이
  그 Submission들에 append-only `Score`를 남겼다 — 되돌릴 수 없는 사고였다.
  `core.transitions.claim_transition`으로 좁힌 지금은 이 Contest만 옮겨야
  한다.
- `seed_e2e_operator_queues._clear_stale_seed_contests`: 오래된(STALE_AFTER
  이전) own-prefix Contest만 지워야 한다 — 무관한 Contest, 그리고 방금 만든
  (STALE_AFTER 이내) own-prefix Contest는 손대면 안 된다. Award가
  `submission`을 PROTECT하므로(awards/models.py) Award를 먼저 지우지 않으면
  Contest 삭제 자체가 `ProtectedError`로 막힌다는 것도 함께 확인한다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from accounts.models import DeveloperProfile, SocialAccount, SponsorProfile
from appeals.models import Appeal
from awards.models import Award
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


# --- seed_e2e_operator_queues._close_contest — 좁은 전이(#66 코드리뷰 지적, 심각) ---


def _make_unrelated_published_contest_with_submission(uid: str) -> tuple[Contest, Submission]:
    """이 명령이 전혀 모르는 PUBLISHED Contest와 그 Submission을 직접 ORM으로
    만든다(아직 Score 없음) — `_close_contest`가 좁게 전이하는지 확인하는
    대조군이다: 예전 구현(전역 `/api/internal/tick`)이었다면 이 Contest도
    함께 CLOSED로 옮겨지고, 그 Submission도 채점까지 끝났을 것이다."""

    User = get_user_model()
    sponsor_user = User.objects.create_user(username=f"unrelated-published-sponsor-{uid}")
    developer_user = User.objects.create_user(username=f"unrelated-published-dev-{uid}")
    SponsorProfile.objects.create(user=sponsor_user)
    developer = DeveloperProfile.objects.create(user=developer_user)

    category = Category.objects.create(name=f"무관한 발행 카테고리 {uid}")
    deliverable_type = DeliverableType.objects.create(
        name=f"무관한 발행 산출물 {uid}", minimum_prize=100_000
    )
    contest = Contest.objects.create(
        sponsor=sponsor_user.sponsor_profile,
        title=f"이 명령과 무관한 PUBLISHED 공모전 {uid}",
        category=category,
        prize=1_000_000,
        # 실시간 기준으로 이미 지난 마감이어야, 예전 버그(전역 tick이 "지금"
        # 기준으로 스캔)가 재발했을 때 이 Contest도 걸린다는 것을 증명할 수
        # 있다 — 마감이 미래면 두 구현이 우연히 같은 결과(안 건드림)를 내서
        # 이 테스트가 아무것도 증명하지 못한다.
        deadline_at=timezone.now() - timedelta(days=1),
        status=Contest.Status.PUBLISHED,
    )
    contest.deliverable_types.add(deliverable_type)

    submission = Submission.objects.create(
        contest=contest, developer=developer, source_object_key=f"unrelated-published/{uid}/source"
    )
    return contest, submission


@pytest.mark.django_db
def test_close_contest_does_not_touch_other_published_contests():
    """#66 코드리뷰 지적(심각) — `_close_contest`가 이 Contest **하나만**
    CLOSED로 전이시켜야 한다. 예전 구현은 시계를 얼려 전역
    `/api/internal/tick`을 태웠는데, 그 한 번의 틱이 DB의 모든 PUBLISHED
    Contest를 스캔해 CLOSED로(그리고 그중 심사기간이 지난 것은 JUDGING_ENDED로)
    옮기고, 곧이어 부르는 scoring/run-pending이 그 Submission들에
    append-only `Score`를 남겼다 — `seed_dev_data`가 만든 개발 데이터가
    e2e 한 번에 조용히 전부 채점 완료 상태가 될 수 있었다(되돌릴 수 없다).

    이 테스트는 실시간 기준으로 이미 마감이 지난 무관한 PUBLISHED Contest를
    하나 심어두고, `seed_e2e_operator_queues`를 한 번 부른 뒤에도 그 Contest가
    여전히 PUBLISHED이고 그 Submission에 Score가 없는지를 직접 확인한다 —
    "고쳤다"는 주장이 아니라 회귀를 잡는 테스트로 남긴다.
    """

    unrelated_contest, unrelated_submission = _make_unrelated_published_contest_with_submission(
        "close-scope-1"
    )
    before_status = unrelated_contest.status
    assert before_status == Contest.Status.PUBLISHED

    call_command("seed_e2e_operator_queues", only="appeal")

    unrelated_contest.refresh_from_db()
    assert unrelated_contest.status == Contest.Status.PUBLISHED, (
        "무관한 PUBLISHED Contest가 전역 스캔에 휩쓸려 상태가 바뀌었다 — "
        "_close_contest가 다시 전역 경로를 쓰고 있을 가능성이 크다."
    )
    unrelated_submission.refresh_from_db()
    assert not hasattr(unrelated_submission, "score"), (
        "무관한 Submission이 채점됐다 — Score는 append-only라 되돌릴 수 없는 사고다."
    )


# --- seed_e2e_operator_queues._clear_stale_seed_contests — 축적 정리(#66 코드리뷰 지적) ---


def _make_stale_own_prefix_contest_with_award(uid: str, *, age) -> Contest:
    """`TITLE_PREFIX`로 시작하는, `age`만큼 오래된 Contest를 Award까지 딸려
    직접 만든다 — `Award.submission`이 PROTECT라(awards/models.py) Contest를
    그냥 지우면 `ProtectedError`가 난다는 것과, `_clear_stale_seed_contests`가
    Award를 먼저 지워 그 보호를 올바르게 푸는지를 함께 확인하는 데 쓴다."""

    from accounts.management.commands.seed_e2e_operator_queues import TITLE_PREFIX

    User = get_user_model()
    sponsor_user = User.objects.create_user(username=f"stale-sponsor-{uid}")
    developer_user = User.objects.create_user(username=f"stale-dev-{uid}")
    SponsorProfile.objects.create(user=sponsor_user)
    developer = DeveloperProfile.objects.create(user=developer_user)

    category = Category.objects.create(name=f"오래된 카테고리 {uid}")
    deliverable_type = DeliverableType.objects.create(
        name=f"오래된 산출물 {uid}", minimum_prize=100_000
    )
    contest = Contest.objects.create(
        sponsor=sponsor_user.sponsor_profile,
        title=f"{TITLE_PREFIX}stale-{uid}",
        category=category,
        prize=1_000_000,
        deadline_at=timezone.now() - age,
        status=Contest.Status.AWARDED,
    )
    contest.deliverable_types.add(deliverable_type)
    # created_at은 auto_now_add라 Model.save() 경로에서만 자동으로 찍힌다 —
    # QuerySet.update()로 우회해 "오래됐다"를 흉내낸다.
    Contest.objects.filter(pk=contest.pk).update(created_at=timezone.now() - age)

    submission = Submission.objects.create(
        contest=contest, developer=developer, source_object_key=f"stale/{uid}/source"
    )
    Award.objects.create(contest=contest, submission=submission, awarded_at=timezone.now())

    contest.refresh_from_db()
    return contest


@pytest.mark.django_db
def test_clear_stale_seed_contests_removes_old_own_prefix_data_only():
    """#66 코드리뷰 지적 — 정렬 오염의 진짜 원인은 축적이었다(마감을 미루는 것은
    답이 아니었다). 오래된 own-prefix Contest는 Award의 PROTECT를 뚫고
    지워지고, 무관한 Contest와 이 호출이 방금 만든 own-prefix Contest는
    그대로 남아야 한다."""

    from accounts.management.commands.seed_e2e_operator_queues import STALE_AFTER, TITLE_PREFIX

    stale = _make_stale_own_prefix_contest_with_award(
        "cleanup-1", age=STALE_AFTER + timedelta(minutes=1)
    )
    unrelated_contest, _unrelated_submission = _make_unrelated_published_contest_with_submission(
        "cleanup-unrelated-1"
    )

    call_command("seed_e2e_operator_queues", only="appeal")

    assert not Contest.objects.filter(pk=stale.pk).exists(), (
        "오래된 own-prefix Contest가 정리되지 않았다 — 축적이 다시 시작된다."
    )
    assert Contest.objects.filter(pk=unrelated_contest.pk).exists(), (
        "무관한 Contest까지 지워졌다 — 삭제 범위가 자기 접두어를 벗어났다."
    )
    # 이 호출이 방금 만든 own-prefix Contest(seed_pending_appeal)는 STALE_AFTER
    # 이내라 정리 대상이 아니어야 한다 — 남은 own-prefix Contest는 그것 하나뿐.
    fresh_own_prefix = Contest.objects.filter(title__startswith=TITLE_PREFIX)
    assert fresh_own_prefix.count() == 1, list(fresh_own_prefix.values_list("title", flat=True))


@pytest.mark.django_db
def test_running_the_seed_twice_in_a_row_does_not_push_a_fresh_own_prefix_contest_out():
    """#66 코드리뷰 지적 — "연속 두 번 돌려도 초록"을 백엔드 레벨에서도
    고정한다. 첫 호출이 own-prefix Contest 하나를 남기고, 그 직후(=STALE_AFTER
    이내) 두 번째 호출이 그것까지 지워버리면 축적 정리 자체가 정렬 문제를
    다시 만든다 — 그런 일이 없는지 직접 센다."""

    from accounts.management.commands.seed_e2e_operator_queues import TITLE_PREFIX

    call_command("seed_e2e_operator_queues", only="appeal")
    first_titles = set(
        Contest.objects.filter(title__startswith=TITLE_PREFIX).values_list("title", flat=True)
    )
    assert len(first_titles) == 1

    call_command("seed_e2e_operator_queues", only="appeal")
    second_titles = set(
        Contest.objects.filter(title__startswith=TITLE_PREFIX).values_list("title", flat=True)
    )

    # 두 번째 호출 뒤에도 첫 번째 호출이 만든 Contest가 여전히 있어야 한다
    # (STALE_AFTER 이내라 정리 대상이 아니다) — 그리고 새로 하나가 더 늘어야
    # 한다(멱등하지 않다는 이 명령의 계약대로).
    assert first_titles <= second_titles
    assert len(second_titles) == 2
