"""「내 참가 현황」 — Developer 가 자기 제출들과 각각의 「다음 행동」을 본다 (#74).

지금까지 로그인한 Developer 가 "내가 어디에 냈고 각각 지금 어떤 상태인가" 를 보는
곳이 없었다. 공개 프로필은 마감 후 아카이브이고 단건 조회는 하나씩이다. 이의도
지급도 걸 데가 없어 운영자 앱 전체가 소비할 입력이 없는 상태였다.

**행은 도메인 상태가 아니라 「다음 행동」을 말한다.** Developer 의 상태는 Contest·
Score·Award·Appeal·Payout 다섯 모델에서 파생되는데, 그것을 그대로 노출하면
참가자가 읽을 수 없는 수의 조합이 된다. 그래서 백엔드가 판정해 타입 있는 값
하나로 내려준다 — 화면이 원시 상태에서 재파생하면 새 상태가 생길 때 조용히
「알 수 없음」으로 떨어진다(이 저장소가 반복해 겪은 모양이다).

**그 값은 대응하는 행위 엔드포인트의 전제와 같은 판정에서 나와야 한다.** 조건을
두 번 쓰면 언젠가 갈라지고, 그러면 화면이 시키는 대로 했는데 API 가 거절한다.
이 파일에서 가장 중요한 테스트가 그것을 친다 — 각 값이 가리키는 행위를 실제로
수행해 성공하는지 본다.
"""

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType

MY_PARTICIPATION_URL = "/api/submissions/mine"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


# 흐름 헬퍼는 test_source_readings.py 의 것을 그대로 쓴다 — Contest 발행·본인확인·
# 제출은 이미 그 파일이 검증해 둔 순서이고, 여기서 또 손으로 조립하면 그 검증이
# 갈라진다.
from tests.test_source_readings import (  # noqa: E402
    _login,
    _publish_contest,
    _submit,
    _verified_user,
)


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


# --- 소유권 경계 -----------------------------------------------------------------


@pytest.mark.django_db
def test_my_participation_requires_authentication(client):
    """비로그인은 401 이다 — 「내」 것을 보는 표면이므로 신원이 먼저다."""

    response = client.get(MY_PARTICIPATION_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_my_participation_is_empty_for_a_developer_who_has_not_submitted(client):
    """아직 아무 데도 안 냈으면 빈 목록으로 200 이다 — 없는 리소스가 아니다."""

    dev = _login(client, "dev-empty")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(dev["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["items"] == []


@pytest.mark.django_db
def test_my_participation_does_not_show_another_developers_submission(
    client, category, landing_type
):
    """남의 제출은 보이지 않는다 — 「내」 목록이 다른 사람의 참가를 드러내면 안 된다."""

    mine = _seed_submission(client, category, landing_type, uid="dev-mine")
    other = _verified_user(client, "dev-other", "ci-other")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(other["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0, "남의 Submission 이 보였다"
    assert all(item["submission_id"] != mine["submission_id"] for item in body["items"])


# --- 다음 행동 -------------------------------------------------------------------


@pytest.mark.django_db
def test_a_submission_before_the_deadline_says_there_is_nothing_to_do(
    client, category, landing_type
):
    """마감 전에는 기다리는 것 말고 할 일이 없다."""

    seeded = _seed_submission(client, category, landing_type, uid="dev-waiting")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))

    assert response.status_code == 200
    (row,) = response.json()["items"]
    assert row["submission_id"] == seeded["submission_id"]
    assert row["next_action"] == "awaiting_deadline"


def _seed_submission(client, category, landing_type, *, uid: str) -> dict:
    """Contest 를 열고 결제까지 마친 뒤 그 Developer 로 제출한다.

    기존 테스트들이 각자 갖고 있는 흐름과 같은 순서다 — 여기서 새로 발명하지
    않는다. 반환값은 이 파일의 단언에 필요한 것만 담는다.
    """

    from datetime import timedelta

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid=f"{uid}-sponsor",
        sponsor_ci=f"{uid}-sponsor-ci",
        deadline_at=timezone.now() + timedelta(hours=1),
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, uid, f"{uid}-ci")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    return {
        "access": dev["access"],
        "submission_id": submission["id"],
        "contest_id": contest["id"],
    }


@pytest.mark.django_db
def test_after_scoring_the_row_says_an_appeal_can_be_filed_and_it_actually_can(
    client, category, landing_type
):
    """**이 파일에서 가장 중요한 테스트다** — 「다음 행동」이 실제 엔드포인트와
    어긋나지 않는다.

    화면이 시키는 대로 했는데 API 가 409 를 내는 조합이 있으면 안 된다.
    `next_action` 은 사고 예방이지 방어가 아니므로(방어는 각 엔드포인트가 이미
    한다), 둘이 갈라지면 그 대가는 전부 사용자가 치른다. 그래서 값을 확인하는
    데서 멈추지 않고 **그 값이 가리키는 행위를 실제로 수행해 성공하는지** 본다.
    """

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-canappeal")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))
    assert response.status_code == 200
    (row,) = response.json()["items"]
    assert row["next_action"] == "can_appeal"

    # 화면이 시킨 그대로 한다.
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "요구사항 3은 실제로는 충족됐습니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201, (
        f"목록이 can_appeal 이라고 했는데 실제 제기가 거절됐다: {filed.content}"
    )


@pytest.mark.django_db
def test_a_pending_appeal_shows_as_waiting_for_a_ruling(client, category, landing_type):
    """이의를 낸 뒤에는 기다리는 중이라고 말한다 — 침묵이 「접수 안 됨」으로 읽히면 안 된다."""

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-pendingappeal")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "재검토를 요청합니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))

    (row,) = response.json()["items"]
    assert row["next_action"] == "awaiting_appeal_ruling"


@pytest.mark.django_db
def test_the_row_does_not_offer_an_appeal_before_scoring(client, category, landing_type):
    """채점 전에는 이의를 권하지 않는다 — `create_appeal` 이 409 로 거절하는 조건과 같다.

    반대 방향도 함께 고정한다: 목록이 권하지 않는 행위는 실제로도 거절된다.
    """

    seeded = _seed_submission(client, category, landing_type, uid="dev-tooearly")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))
    (row,) = response.json()["items"]
    assert row["next_action"] != "can_appeal"

    refused = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "아직 채점 전인데 내본다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert refused.status_code == 409


def _seed_scored_submission(client, category, landing_type, *, uid: str) -> dict:
    """제출 후 마감시키고 채점까지 돌린다 — 이의 창이 열린 상태."""

    from datetime import timedelta

    from tests.test_source_readings import _close_contest, _run_scoring

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid=f"{uid}-sponsor",
        sponsor_ci=f"{uid}-sponsor-ci",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, uid, f"{uid}-ci")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return {
        "access": dev["access"],
        "submission_id": submission["id"],
        "contest_id": contest["id"],
    }


@pytest.mark.django_db
def test_a_ruled_appeal_does_not_offer_another_one(client, category, landing_type):
    """심판이 끝난 뒤에는 이의를 다시 권하지 않는다 — 권하면 그 제기는 409 로 거절된다.

    이 테스트는 **변이 확인으로 발견해서 추가했다.** 「다음 행동」에서 "이미
    이의가 있다" 조건을 빼도 기존 테스트가 전부 통과했다 — 심판 대기 케이스는
    함수의 더 앞쪽 분기가 잡아내서 가려졌고, 심판이 **끝난** 경우를 아무도 치지
    않고 있었다. Submission 당 이의는 하나이므로(`create_appeal` 의 전제),
    그 상태에서 can_appeal 을 권하면 화면이 시킨 대로 한 사용자가 거절당한다.
    """

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-ruled")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "재검토를 요청합니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201
    appeal_id = filed.json()["id"]

    from tests.test_source_readings import OPERATOR_ORIGIN, _operator_client

    operator = _operator_client("op-participation-ruled")
    ruled = operator.post(
        f"/api/operator/appeals/{appeal_id}/rule",
        data={"decision": "reject", "ruling_note": "판정을 유지한다."},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert ruled.status_code == 200, ruled.content

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))
    (row,) = response.json()["items"]
    assert row["next_action"] != "can_appeal", "심판이 끝났는데 또 이의를 권했다"

    refused = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "한 번 더 내본다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert refused.status_code == 409


@pytest.mark.django_db
def test_the_appeal_window_closes_when_the_judging_period_ends(
    client, category, landing_type
):
    """이의 기한은 심사기간 종료다 (#74) — 그 뒤로는 권하지도, 받지도 않는다.

    이 테스트도 **변이 확인으로 발견해서 추가했다.** `_within_appeal_window` 를
    통째로 `True` 로 바꿔도 기존 여덟 건이 전부 통과했다 — 심사기간이 지난
    시점을 아무도 치지 않고 있었다. 기한은 이 스펙이 내린 핵심 결정인데
    (`Score` 는 Award 를 결정하지 않으므로 점수가 돈을 정하는 곳은 배분의
    컷라인뿐이고, judging_ends_at 이면 배분은 아직 대기를 시작도 안 했다)
    그것을 지켜보는 테스트가 없었다.

    시간은 시임이 아니라 주입 가능한 의존성이므로(ADR-0003) 값을 바꾸지 않고
    시계를 옮긴다.
    """

    from datetime import timedelta

    from core.models import ClockOverride
    from contests.models import Contest

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-late")

    contest = Contest.objects.get(id=seeded["contest_id"])
    assert contest.judging_ends_at is not None, "마감 전이가 judging_ends_at 을 안 찍었다"

    # 심사기간이 끝난 뒤로 시계를 옮긴다.
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": contest.judging_ends_at + timedelta(minutes=1)}
    )
    try:
        response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))
        (row,) = response.json()["items"]
        assert row["next_action"] != "can_appeal", "기한이 지났는데 이의를 권했다"

        refused = client.post(
            f"/api/submissions/{seeded['submission_id']}/appeal",
            data={"reason": "기한이 지난 뒤에 내본다."},
            content_type="application/json",
            **_auth_header(seeded["access"]),
        )
        assert refused.status_code == 409, (
            "기한이 지났는데 제기가 받아들여졌다 — 화면이 감추는 것과 API 가 "
            f"거절하는 것은 둘 다 필요하다: {refused.status_code}"
        )
    finally:
        ClockOverride.objects.filter(pk=1).delete()


@pytest.mark.django_db
def test_after_the_deadline_but_before_scoring_the_row_says_scoring_is_pending(
    client, category, landing_type
):
    """마감은 됐는데 아직 채점 전 — 기다리는 중이고, 이의는 아직 낼 수 없다.

    이 테스트도 **변이 확인으로 발견해서 추가했다.** "Score 가 있는가" 검사를
    통째로 없애도 아홉 건이 전부 통과했다 — 기존 테스트의 데이터가 전부 마감
    **전**이거나 채점 **후**라, 그 사이의 상태에 아무도 닿지 않았다. 실제로는
    마감과 채점 사이에 스캔 주기만큼의 창이 있고(ADR-0003), 그 동안 Developer
    가 이 화면을 볼 수 있다.
    """

    from datetime import timedelta

    from tests.test_source_readings import _close_contest

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="dev-unscored-sponsor",
        sponsor_ci="dev-unscored-sponsor-ci",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-unscored", "dev-unscored-ci")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    # 마감만 시키고 채점은 돌리지 않는다.
    _close_contest(client, contest, deadline=deadline)

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(dev["access"]))

    (row,) = response.json()["items"]
    assert row["next_action"] == "awaiting_scoring"

    refused = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "채점 전인데 내본다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert refused.status_code == 409
