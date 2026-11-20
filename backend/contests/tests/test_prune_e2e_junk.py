"""`prune_e2e_junk` — e2e 가 남긴 기준데이터와 정책 오염을 걷는다 (#183).

**왜 별도 명령인가.** Contest 는 이미 걷힌다 — `seed_e2e_contests` 가 제목 접두어로
자기 것을 가르고, `--prune-all-namespaces` 가 스위트 시작에 한 번 전부 걷는다. 그런데
그 관용구가 **Category·DeliverableType·정책 단일 행에는 적용되지 않았다.** 그 결과 dev
스택에서 산출물 종류가 132개(진짜는 5개), 카테고리가 24개(진짜는 4개)까지 쌓여 개최
화면의 체크박스 목록과 운영자 화면이 사람이 쓸 수 없는 상태가 됐고, 플랫폼 수수료율은
e2e 가 남긴 324bps 였다 — dev 에서 확인한 실수령액이 실제 정책과 다르다는 뜻이다.

**이 파일은 HTTP 를 거치지 않는다.** 검증 대상이 관리 명령 자신의 행동이고,
`tests/test_seed_e2e_contests_namespace.py` 가 같은 이유로 `call_command` 를 직접 부른다.
HTTP 입구(`core/e2e_seeds.py` 등록부)를 거치는 경로는 `tests/test_e2e_seed_api.py` 가
따로 덮는다.
"""

from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.utils import timezone

from accounts.models import SponsorProfile
from contests.models import Category, Contest, DeliverableType, DeliverableTypeChange
from policies.models import PlatformPolicy, PolicyChange


def _prune() -> dict:
    """명령을 돌리고 마지막 줄의 JSON 을 돌려준다 — 다른 e2e 시드와 같은 규약이다."""

    out = StringIO()
    call_command("prune_e2e_junk", stdout=out, stderr=StringIO())
    return json.loads(out.getvalue().strip().splitlines()[-1])


def _real_reference_data() -> tuple[Category, DeliverableType]:
    """e2e 이름이 아닌 진짜 기준데이터 — 무슨 일이 있어도 살아남아야 한다."""

    category = Category.objects.create(name="교육")
    deliverable = DeliverableType.objects.create(name="웹 서비스", minimum_prize=2_000_000)
    return category, deliverable


def test_prunes_every_shape_of_e2e_name(db):
    """**세 이름 모양을 전부 잡는다.**

    실측한 dev DB 에는 서로 다른 시절이 남긴 세 모양이 함께 있었다 —
    `seed_e2e_contests` 의 네임스페이스 접두어(`[E2E-w0] 웹 서비스`), 운영자 큐 시드의
    `E2E 운영자 큐용 웹서비스`, 그리고 지금은 지워진 운영자 스펙들이 화면으로 만든
    `e2e 생성 종류 1788…`. 하나라도 놓치면 목록은 여전히 묻힌다.
    """

    real_category, real_deliverable = _real_reference_data()
    Category.objects.create(name="[E2E-w0] 라이프스타일")
    Category.objects.create(name="E2E 운영자 큐")
    DeliverableType.objects.create(name="[E2E-bench] 모바일 앱", minimum_prize=1)
    DeliverableType.objects.create(name="E2E 운영자 큐용 웹서비스", minimum_prize=1)
    DeliverableType.objects.create(name="e2e 생성 종류 1788", minimum_prize=1)

    result = _prune()

    assert result["categories_deleted"] == 2
    assert result["deliverable_types_deleted"] == 3
    assert set(Category.objects.values_list("name", flat=True)) == {real_category.name}
    assert set(DeliverableType.objects.values_list("name", flat=True)) == {real_deliverable.name}


def test_prunes_deactivated_types_too(db):
    """**비활성화된 종류도 정리 대상이다.**

    운영자 화면은 비활성 종류도 목록에 남겨 보여준다(지우지 않고 비활성화만 하는 것이
    그 모델의 규율이다) — 실측에서 `e2e 비활성화 대상 …` 27개가 그렇게 남아 목록을
    채우고 있었다. 「비활성이니 안 보인다」는 사실이 아니다.
    """

    _real_reference_data()
    DeliverableType.objects.create(name="e2e 비활성화 대상 42", minimum_prize=1, is_active=False)

    result = _prune()

    assert result["deliverable_types_deleted"] == 1
    assert not DeliverableType.objects.filter(name__istartswith="e2e").exists()


def test_prunes_types_that_carry_change_history(db):
    """**이력이 달린 종류도 지운다 — 그 이력과 함께.**

    `DeliverableTypeChange.deliverable_type` 은 PROTECT 라, 이력을 남긴 채로는 종류를
    지울 수 없다. 실측에서 e2e 종류 127개 중 **108개**가 이력을 달고 있었다(운영자
    화면으로 만들어졌기 때문이다) — 이력을 건드리지 않으면 정리는 19개만 걷고 끝난다.

    지우는 것은 **e2e 가 만든 종류에 달린 이력뿐**이다. 진짜 종류의 이력은 대상이 아니고,
    정책 변경 이력(`PolicyChange`)은 이 명령이 아예 손대지 않는다 — 아래 테스트가 그것을
    따로 고정한다.
    """

    _real_reference_data()
    operator = get_user_model().objects.create_user(username="op-183", password="x")
    junk = DeliverableType.objects.create(name="e2e 수정 대상 7", minimum_prize=1)
    DeliverableTypeChange.objects.create(
        deliverable_type=junk,
        operator=operator,
        action=DeliverableTypeChange.Action.CREATED,
        reason="e2e",
        before={},
        after={"minimum_prize": 1},
        changed_at=timezone.now(),
    )

    result = _prune()

    assert result["deliverable_types_deleted"] == 1
    assert not DeliverableType.objects.filter(pk=junk.pk).exists()
    assert not DeliverableTypeChange.objects.exists()


def test_keeps_reference_data_a_surviving_contest_still_points_at(db):
    """**정리가 남의 것을 지워 명령을 죽이지 않는다.**

    `Contest.category` 는 PROTECT 다. 접두어 없는 Contest 가 e2e 카테고리를 참조하고
    있으면(런타임에 Contest 를 만드는 스펙들이 실제로 그 기준데이터를 재사용한다) 그
    삭제는 막힌다 — 예전에 `seed_e2e_contests` 가 기준데이터를 지우려다 바로 이
    `ProtectedError` 로 통째로 죽었고, 그러면 JSON 이 안 나와 e2e 가 엉뚱한 id 로 404 를
    맞았다.

    그래서 막힌 것은 **건너뛰고 이름을 보고한다.** 청소는 검증이 아니다 — 실패가
    스위트를 빨갛게 만들면 안 되지만, 조용히 넘어가서도 안 된다.
    """

    _real_reference_data()
    held = Category.objects.create(name="[E2E-w0] 라이프스타일")
    free = Category.objects.create(name="[E2E-w0] 생산성")
    user = get_user_model().objects.create_user(username="sponsor-183", password="x")
    sponsor = SponsorProfile.objects.create(user=user)
    Contest.objects.create(
        sponsor=sponsor,
        title="접두어 없는 Contest",
        category=held,
        prize=1_000_000,
        deadline_at=timezone.now() + timedelta(days=1),
    )

    result = _prune()

    assert Category.objects.filter(pk=held.pk).exists(), "참조가 걸린 것을 지워버렸다"
    assert not Category.objects.filter(pk=free.pk).exists(), "막히지 않은 것까지 남겼다"
    assert result["categories_deleted"] == 1
    assert held.name in result["skipped"]


def test_resets_the_policy_row_to_the_model_defaults(db):
    """**정책 단일 행이 기준값으로 돌아온다.**

    실측 dev DB 의 수수료율은 324bps 였다 — 변경 이력 28건이 전부 e2e 가 남긴 무작위
    값의 연쇄(`1000 → 332 → 589 → …`)였다. 기준값을 이 명령이 따로 적어 두지 않고
    **모델 필드의 기본값**에서 읽는 것이 요점이다: 기준값이 두 곳에 적히면 정책이 하나
    늘 때마다 여기가 조용히 뒤처진다.
    """

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"platform_fee_bps": 324, "withholding_tax_bps": 111}
    )

    result = _prune()

    policy = PlatformPolicy.objects.get(pk=1)
    assert policy.platform_fee_bps == 1000
    assert policy.withholding_tax_bps == 440
    assert result["policy_reset"] == {
        "platform_fee_bps": [324, 1000],
        "withholding_tax_bps": [111, 440],
    }


def test_touches_only_the_fields_the_operator_api_can_change(db):
    """**정책값만 되돌린다 — 장부 필드는 건드리지 않는다.**

    처음엔 「기본값이 있는 필드 전부」를 되돌렸고, 그것이 실제로 사고를 냈다: `version`
    은 정책값이 아니라 낙관적 동시성 카운터인데(#76 — GET 이 돌려준 값과 같을 때만
    갱신한다) 그것을 28에서 0으로 되돌렸다. 카운터가 뒤로 가면 나중 쓰기가 앞선 쓰기를
    조용히 덮을 길이 열린다.

    그래서 대상을 `policies.services.UPDATABLE_FIELDS` 로 좁혔다 — 운영자 API 가 바꿀 수
    있는 집합이고, 그 API 가 유일한 변경 경로이므로 **e2e 가 오염시킬 수 있는 것과 정확히
    같다.** 그 집합 밖은 이 명령의 일이 아니다.
    """

    PlatformPolicy.objects.update_or_create(
        pk=1,
        defaults={"platform_fee_bps": 324, "version": 28, "judging_period_days": 3},
    )

    result = _prune()

    policy = PlatformPolicy.objects.get(pk=1)
    assert policy.version == 28, "동시성 카운터를 되돌렸다 — 나중 쓰기가 앞선 것을 덮는다"
    assert policy.judging_period_days == 3, "운영자 API 가 못 바꾸는 값까지 건드렸다"
    assert set(result["policy_reset"]) == {"platform_fee_bps"}


def test_leaves_the_policy_change_history_alone(db):
    """**변경 이력은 지우지 않는다 — 감사 추적이다**(ADR-0023).

    정리 대상은 정책의 **값**이지 그 값이 어떻게 움직였는지의 기록이 아니다. e2e 가
    남긴 이력이라도 지우는 순간 「이 표를 청소해도 된다」는 선례가 생기고, 그 선례는
    진짜 변경 이력에도 그대로 적용된다.
    """

    operator = get_user_model().objects.create_user(username="op-183-policy", password="x")
    PlatformPolicy.objects.update_or_create(pk=1, defaults={"platform_fee_bps": 324})
    PolicyChange.objects.create(
        operator=operator,
        reason="e2e",
        before={"platform_fee_bps": 1000},
        after={"platform_fee_bps": 324},
        changed_at=timezone.now(),
    )

    _prune()

    assert PolicyChange.objects.count() == 1, "감사 추적을 지웠다"


def test_does_nothing_when_the_policy_row_is_absent(db):
    """정책 행이 아직 없으면 만들지 않는다 — 이 명령의 일은 청소지 초기화가 아니다."""

    assert not PlatformPolicy.objects.exists()

    result = _prune()

    assert result["policy_reset"] == {}
    assert not PlatformPolicy.objects.exists()


def test_refuses_to_run_in_a_deployed_environment(db, settings):
    """배포 환경에서는 실행 자체를 거부한다 — 다른 e2e 명령과 같은 가드다(ADR-0019).

    이 명령은 행을 **지우고** 정책값을 되돌린다. staging 에서 한 번 돌면 운영자가 실제로
    내린 정책 판단이 조용히 기본값으로 돌아간다.
    """

    settings.IS_DEPLOYED_ENVIRONMENT = True

    with pytest.raises(CommandError, match="배포 환경"):
        call_command("prune_e2e_junk", stdout=StringIO(), stderr=StringIO())


def test_keeps_a_deliverable_type_a_surviving_contest_still_uses(db):
    """**M2M 은 예외를 던지지 않는다 — 그래서 명시적으로 본다.**

    `Contest.deliverable_types` 는 평범한 M2M 이라 종류를 지우면 조인 행만 조용히
    사라진다. `Contest.category` 처럼 `ProtectedError` 가 나지 않으므로, 예외에만 기대면
    그 Contest 는 산출물 종류가 0개가 된 채 **아무 데도 보고되지 않는다**(스냅샷해 둔 최소
    제안 상금은 이제 아무것도 가리키지 않는다).

    사람이 손으로 부르는 경로에서 실제로 일어날 수 있다 — 잡데이터로 덮인 개최 화면에서
    e2e 이름의 종류를 골라 만든 Contest 가 그렇다.
    """

    real_category, _ = _real_reference_data()
    used = DeliverableType.objects.create(name="e2e 생성 종류 99", minimum_prize=1)
    unused = DeliverableType.objects.create(name="e2e 생성 종류 100", minimum_prize=1)
    user = get_user_model().objects.create_user(username="sponsor-183-m2m", password="x")
    contest = Contest.objects.create(
        sponsor=SponsorProfile.objects.create(user=user),
        title="접두어 없는 Contest",
        category=real_category,
        prize=1_000_000,
        deadline_at=timezone.now() + timedelta(days=1),
    )
    contest.deliverable_types.add(used)

    result = _prune()

    assert list(contest.deliverable_types.all()) == [used], "Contest 의 산출물 종류를 비웠다"
    assert used.name in result["skipped"], "조용히 지나갔다 — 건너뛴 사실이 보고되지 않는다"
    assert not DeliverableType.objects.filter(pk=unused.pk).exists()


def test_stamps_updated_at_when_it_resets_the_policy(db):
    """**되돌린 시각이 실제로 찍힌다.**

    `updated_at` 은 `auto_now` 지만 `save(update_fields=…)` 에 넣지 않으면 Django 가
    `pre_save` 를 아예 부르지 않아 값이 그대로 남는다. 그러면 운영자 화면이 「수수료율
    1000, 마지막 변경은 그것이 324 이던 시각」을 보여준다 — 이 티켓이 없애려는 바로 그
    「화면의 숫자가 실제와 다르다」이다.
    """

    PlatformPolicy.objects.update_or_create(pk=1, defaults={"platform_fee_bps": 324})
    stale = timezone.now() - timedelta(days=3)
    # `auto_now` 를 우회해 과거 시각을 심는다 — `save()` 로는 심을 수 없다.
    PlatformPolicy.objects.filter(pk=1).update(updated_at=stale)

    _prune()

    assert PlatformPolicy.objects.get(pk=1).updated_at > stale
