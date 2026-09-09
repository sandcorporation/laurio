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
def test_a_submission_before_the_deadline_can_still_be_edited(client, category, landing_type):
    """마감 전에는 제출물을 고칠 수 있다 (#245).

    예전 이름(`awaiting_deadline`, "마감 전에는 기다리는 것 말고 할 일이 없다")은
    거짓이었다 — 제출 화면은 기존 제출을 불러와 PUT으로 고칠 수 있는데, 「내
    참가 현황」이 그 화면으로 가는 링크를 안 주고 있었을 뿐이다. 이 파일의
    규율대로 값을 확인하는 데서 멈추지 않고, 화면이 시킨 그대로(PUT) 했을 때
    실제로 성공하는지 본다.
    """

    seeded = _seed_submission(client, category, landing_type, uid="dev-waiting")

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))

    assert response.status_code == 200
    (row,) = response.json()["items"]
    assert row["submission_id"] == seeded["submission_id"]
    assert row["next_action"] == "can_edit_submission"
    # 공모전 참가 행이다 — Assignment로 돌아가는 InviteCode 는 여기 없다.
    assert row["invite_code"] is None

    # 화면이 시킨 그대로 한다: 기존 자료·체크리스트를 그대로 실어 PUT한다.
    existing = client.get(
        f"/api/contests/{seeded['contest_id']}/submissions/me",
        **_auth_header(seeded["access"]),
    ).json()
    edited = client.put(
        f"/api/contests/{seeded['contest_id']}/submissions/me",
        data={
            "assets": [
                {"id": asset["id"], "kind": asset["kind"], "value": asset["value"]}
                for asset in existing["assets"]
            ],
            "requirement_responses": [
                {
                    "requirement_id": r["requirement_id"],
                    "is_met": r["is_met"],
                    "note": r["note"],
                    "evidence": [
                        {"kind": e["kind"], "value": e["value"], "asset_id": e["asset_id"]}
                        for e in r["evidence"]
                    ],
                }
                for r in existing["requirement_responses"]
            ],
        },
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert edited.status_code == 200, (
        f"목록이 can_edit_submission 이라고 했는데 실제 수정이 거절됐다: {edited.content}"
    )


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


# --- 알림: 이의 창의 시작과 끝 (#74) ----------------------------------------------


@pytest.mark.django_db
def test_scoring_notifies_the_developer_with_the_appeal_deadline(
    client, category, landing_type
):
    """채점이 끝나면 알린다 — 그 통지가 이의 창이 열렸다는 신호다.

    기한을 만들었으면 그 시작을 알리는 것까지가 같은 결정이다. 알리지 않으면
    기한은 "들어와 본 사람에게만 공정한" 규칙이 된다. 그래서 **언제까지인지**도
    통지에 함께 담는다 — 받는 사람이 다시 들어와 찾게 만들지 않는다.
    """

    from notifications.models import Notification, NotificationType

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-notify-score")

    notice = Notification.objects.filter(
        notification_type=NotificationType.SCORING_COMPLETE
    ).first()
    assert notice is not None, "채점이 끝났는데 알림이 없다"
    assert notice.context["submission_id"] == seeded["submission_id"]
    assert notice.context["appeal_deadline"], "이의 기한이 통지에 없다"


@pytest.mark.django_db
def test_ruling_an_appeal_notifies_the_developer_without_the_operators_name(
    client, category, landing_type
):
    """심판 결과를 알리되 **심판자 개인의 이름은 담지 않는다**.

    #61 이 열람 기록에 대해 세운 것과 같은 이유다 — 결과와 이유는 주되 운영자
    신원을 참가자에게 흘리면 ADR-0018 이 서로소로 갈라놓은 두 경계 사이에 새
    문제가 생긴다(누가 자기를 떨어뜨렸는지 아는 참가자).
    """

    from notifications.models import Notification, NotificationType
    from tests.test_source_readings import OPERATOR_ORIGIN, _operator_client

    seeded = _seed_scored_submission(client, category, landing_type, uid="dev-notify-rule")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "재검토를 요청합니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201
    appeal_id = filed.json()["id"]

    operator_name = "op-secret-ruler"
    operator = _operator_client(operator_name)
    ruled = operator.post(
        f"/api/operator/appeals/{appeal_id}/rule",
        data={"decision": "reject", "ruling_note": "판정을 유지한다."},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert ruled.status_code == 200, ruled.content

    notice = Notification.objects.filter(
        notification_type=NotificationType.APPEAL_RULED
    ).first()
    assert notice is not None, "심판이 끝났는데 알림이 없다"
    assert notice.context["decision"] == "rejected"
    assert notice.context["ruling_note"] == "판정을 유지한다."
    assert operator_name not in str(notice.context), "심판자의 이름이 통지에 들어갔다"


# --- #152: 커서 페이지네이션 --------------------------------------------------------


def _clone_submissions(count: int, *, developer, category) -> None:
    """개발자에게 딸린 제출을 `count` 개 더 만든다 — 페이지네이션 부피용이다.

    한 Developer 는 한 Contest 에 하나만 낼 수 있으므로
    (`unique_submission_per_contest_developer`), Contest 도 함께 새로 만든다.
    HTTP 흐름(`_seed_submission`)을 스물몇 번 다시 태울 이유가 없다 — 여기서
    확인할 것은 개최·제출이 아니라 목록이 자라는 동안 커서가 버티는가다.
    픽스처는 ORM 으로, 단언은 HTTP 로(운영자 지급 큐의 `_clone_blocked_payouts`
    와 같은 관용구, #151).
    """

    import uuid
    from datetime import timedelta

    from django.contrib.auth import get_user_model

    from accounts.models import SponsorProfile
    from contests.models import Contest
    from submissions.models import Submission

    suffix = uuid.uuid4().hex[:8]
    sponsor_user = get_user_model().objects.create_user(
        username=f"clone-sponsor-{suffix}", email=f"clone-sponsor-{suffix}@example.invalid"
    )
    sponsor_profile = SponsorProfile.objects.create(
        user=sponsor_user, display_name="사본 스폰서"
    )

    for index in range(count):
        contest = Contest.objects.create(
            sponsor=sponsor_profile,
            title=f"사본 공모전 {suffix}-{index}",
            category=category,
            prize=900_000,
            deadline_at=timezone.now() + timedelta(hours=1),
            status=Contest.Status.PUBLISHED,
        )
        Submission.objects.create(contest=contest, developer=developer)


@pytest.mark.django_db
def test_my_participation_does_not_repeat_or_lose_a_row_when_the_list_grows(
    client, category, landing_type
):
    """1페이지를 받은 뒤 참가가 하나 더 생겨도 「더 보기」가 같은 행을 두 번
    그리지 않고, 경계에 있던 행을 잃지 않는다 (#152).

    다른 탭에서 제출을 하나 더 하면 머리에 새 행이 들어온다 — 오프셋이면 그
    몇 초 사이에 경계가 밀려 2페이지가 1페이지의 마지막 행을 다시 돌려주고,
    원래 그 자리에 와야 했던 행은 어느 페이지에도 안 나온다(#151 이 운영자
    지급 큐에서 세운 것과 같은 시나리오).
    """

    from submissions.models import Submission

    seeded = _seed_submission(client, category, landing_type, uid="dev-152-1")
    developer = Submission.objects.get(id=seeded["submission_id"]).developer
    _clone_submissions(24, developer=developer, category=category)

    first = client.get(MY_PARTICIPATION_URL, **_auth_header(seeded["access"]))
    assert first.status_code == 200, first.content
    first_body = first.json()
    first_ids = [row["submission_id"] for row in first_body["items"]]
    assert len(first_ids) == 20
    assert first_body["next"], "더 있는데 다음 커서를 주지 않았다"

    # **여기서 목록이 자란다** — 다른 탭에서 제출을 셋 더 한다.
    _clone_submissions(3, developer=developer, category=category)

    second = client.get(
        f"{MY_PARTICIPATION_URL}?after={first_body['next']}", **_auth_header(seeded["access"])
    )
    assert second.status_code == 200, second.content
    second_ids = [row["submission_id"] for row in second.json()["items"]]

    assert not set(first_ids) & set(second_ids), (
        "목록이 자란 뒤 2페이지가 1페이지의 행을 다시 돌려줬다"
    )
    # 1페이지 이후로 밀린 다섯(25건 중 나머지)은 그대로 나온다 — 새로 생긴 셋은
    # 이미 지나간 커서보다 앞이라 나오지 않는 것이 옳다(그건 다음 조회의 몫이다).
    assert len(second_ids) == 5, second_ids


@pytest.mark.django_db
def test_my_participation_rejects_a_cursor_it_cannot_read(client, category, landing_type):
    """읽을 수 없는 커서는 조용히 처음부터가 아니라 422 다 (#152) — 운영자 지급
    큐와 같은 규율(#151)."""

    seeded = _seed_submission(client, category, landing_type, uid="dev-152-2")

    response = client.get(
        f"{MY_PARTICIPATION_URL}?after=not-a-cursor", **_auth_header(seeded["access"])
    )

    assert response.status_code == 422, response.content


# --- Assignment 도 같은 길로 돌아간다 (#245) --------------------------------------


@pytest.mark.django_db
def test_an_assignment_participation_row_carries_the_active_invite_code_to_get_back(
    client, landing_type
):
    """Assignment 는 「내 참여」로 돌아가는 길의 모양이 다르다 (#245).

    `/console/contests/{id}/submit`은 본인확인을 요구해 Assignment 제출을
    받지 않는다(`submissions.api.create_submission`의 `SUBMISSION_REQUIRES_
    VERIFICATION` 분기) — 학생이 돌아갈 화면은 InviteCode 로만 여는
    `/assignments/{code}`이고, 그 URL을 조립하려면 코드가 있어야 한다. 이
    값은 **지금 활성인** 코드를 낸다 — 재발급으로 학생이 처음 쓴 코드가
    죽어도(#209) 새 코드로 계속 편집할 수 있다는 것이 이미 정해진 동작이다
    (`test_old_invite_code_dies_but_existing_submission_survives_reissue`).
    """

    from tests.test_assignment_submissions import _create_and_open_assignment, _submit

    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="myp-asgn-sponsor"
    )
    student = _login(client, "myp-asgn-student")
    student_user_id = client.get(
        "/api/accounts/me", **_auth_header(student["access"])
    ).json()["id"]

    submitted = _submit(
        client,
        student["access"],
        assignment["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": f"submission:{assignment['id']}:{student_user_id}:source/x",
                }
            ],
            "invite_code": assignment["invite_code"],
        },
    )
    assert submitted.status_code == 201, submitted.content

    response = client.get(MY_PARTICIPATION_URL, **_auth_header(student["access"]))

    assert response.status_code == 200, response.content
    (row,) = response.json()["items"]
    assert row["next_action"] == "can_edit_submission"
    assert row["invite_code"] == assignment["invite_code"]
