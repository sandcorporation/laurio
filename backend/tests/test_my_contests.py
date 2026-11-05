"""「내 공모전」 — Sponsor 가 자기가 연 공모전들과 각각의 「다음 행동」을 본다 (#81).

Sponsor 는 개최·결제·심사까지 할 수 있는데 **자기가 연 것들을 모아 보는 곳이
없다.** 그래서 "내 공모전이 끝났는가, 안 끝났으면 무엇을 기다리는가"에 답할
자리가 없었다 — #74 가 참가자 쪽에 지어 준 것을 개최자 쪽에는 아무도 짓지
않았다.

**모양은 참가자 표면과 같다**(`submissions.participation`). 백엔드가 상태를
하나의 값으로 판정해 타입 있는 enum 으로 내리고, 화면은 그것을 문구로 옮기기만
한다. 이유도 같다: 화면이 원시 상태(Contest.status · Score 유무 · Award ·
Handover · Distribution · Appeal)에서 재파생하면 새 상태가 생겼을 때 어느
분기에도 안 걸려 조용히 「알 수 없음」이 된다.

**#81 의 존재 이유는 스토리 40 이다** — 이의 심판 때문에 배분이 보류된 공모전이
「조용히 늦은 것」이 아니라 「보류」로 보여야 한다. 그리고 그 사실은 공개
Contest 상세에 실을 수 없다: 그 응답은 비로그인 포함 누구나 보므로, 거기 실으면
참가자의 분쟁 사실이 공개된다. 그래서 Sponsor 스코프의 표면이 필요했다.

시임은 언제나 HTTP 다(CLAUDE.md).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType

from tests.test_source_readings import (
    _close_contest,
    _publish_contest,
    _run_scoring,
    _submit,
    _verified_user,
)

MY_CONTESTS_URL = "/api/contests/mine"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _mine(client, access: str) -> list[dict]:
    response = client.get(MY_CONTESTS_URL, **_auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["items"]


# --- 소유권 경계 -----------------------------------------------------------------


@pytest.mark.django_db
def test_my_contests_requires_authentication(client):
    """비로그인은 401 이다 — 「내」 것을 보는 표면이므로 신원이 먼저다."""

    assert client.get(MY_CONTESTS_URL).status_code == 401


@pytest.mark.django_db
def test_a_sponsor_sees_only_their_own_contests(client, category, landing_type):
    """남이 연 공모전은 목록에 나타나지 않는다."""

    mine_sponsor, mine_contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-mine", sponsor_ci="ci-mine",
    )
    _other_sponsor, other_contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-other", sponsor_ci="ci-other",
    )

    ids = [row["contest_id"] for row in _mine(client, mine_sponsor["access"])]

    assert mine_contest["id"] in ids
    assert other_contest["id"] not in ids


@pytest.mark.django_db
def test_someone_who_has_never_opened_a_contest_gets_an_empty_list(client):
    """개최한 적 없는 사람은 빈 목록이다 — 404 도 500 도 아니다."""

    nobody = _verified_user(client, "never-opened", "ci-never-opened")

    response = client.get(MY_CONTESTS_URL, **_auth_header(nobody["access"]))

    assert response.status_code == 200
    assert response.json()["items"] == []


# --- 「다음 행동」이 각 단계에서 무엇을 말하는가 -----------------------------------


@pytest.mark.django_db
def test_before_the_deadline_the_row_says_it_is_waiting_for_submissions(
    client, category, landing_type
):
    """공개됐고 마감 전 — 기다리는 것 말고 할 일이 없다."""

    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-open", sponsor_ci="ci-open",
    )

    row = _mine(client, sponsor["access"])[0]

    assert row["contest_id"] == contest["id"]
    assert row["next_action"] == "awaiting_submissions"
    assert row["title"] == contest["title"]
    assert row["prize"] == contest["prize"]


@pytest.mark.django_db
def test_after_the_deadline_but_before_scoring_the_row_says_scoring_is_pending(
    client, category, landing_type
):
    """마감은 됐지만 채점이 아직이다 — 심사하라고 하면 안 된다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-scoring", sponsor_ci="ci-scoring",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-scoring", "ci-dev-scoring")
    _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])
    _close_contest(client, contest, deadline=deadline)

    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_scoring"


@pytest.mark.django_db
def test_once_scoring_is_done_the_row_tells_the_sponsor_to_judge(
    client, category, landing_type
):
    """채점이 끝나고 심사기간 안이면 **Sponsor 차례**다 — 이게 이 화면의 핵심이다.

    아무도 심사하지 않으면 심사기간이 지나 무응답 배분으로 넘어간다. 개최자가
    그 사실을 모른 채 지나가면, 자기가 고를 수 있었던 결과를 고르지 못한다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-judge", sponsor_ci="ci-judge",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-judge", "ci-dev-judge")
    _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    row = _mine(client, sponsor["access"])[0]

    assert row["next_action"] == "judge_and_award"
    # 몇 명이 냈는지가 그 자리에서 보여야 심사하러 갈지 판단할 수 있다.
    assert row["submission_count"] == 1


@pytest.mark.django_db
def test_a_closed_contest_with_no_submissions_says_so_instead_of_asking_to_judge(
    client, category, landing_type
):
    """제출이 0건이면 고를 것이 없다 — 「심사하세요」는 거짓말이다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-empty", sponsor_ci="ci-empty",
        deadline_at=deadline,
    )
    _close_contest(client, contest, deadline=deadline)

    row = _mine(client, sponsor["access"])[0]

    assert row["next_action"] == "no_submissions"
    assert row["submission_count"] == 0


# --- 스토리 40: 보류가 「조용히 늦음」으로 보이지 않는다 ---------------------------


@pytest.mark.django_db
def test_a_contest_whose_distribution_is_held_by_an_appeal_says_it_is_held(
    client, category, landing_type
):
    """#81 이 존재하는 이유. 배분이 이의 때문에 멈춰 있으면 그렇게 말한다.

    개최자 입장에서 「끝났어야 할 공모전이 안 끝났다」는 사실만 보이면 고장으로
    읽힌다. 이유가 있고, 그 이유가 제도의 정상 동작이라는 것을 말해야 한다.
    """

    from core.models import ClockOverride
    from contests.models import Contest
    from policies.scope import current_policy

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-held", sponsor_ci="ci-held",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-held", "ci-dev-held")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    filed = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert filed.status_code == 201, filed.content

    # 심사기간이 끝나고 배분 대기일까지 지난다 — 지금쯤 배분이 됐어야 한다.
    row = Contest.objects.get(id=contest["id"])
    assert row.judging_ends_at is not None
    policy = current_policy()
    ClockOverride.objects.update_or_create(
        pk=1,
        defaults={
            "overridden_at": row.judging_ends_at
            + timedelta(days=policy.distribution_wait_days + 1)
        },
    )
    client.post("/api/internal/tick", **_internal_headers())

    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_appeal_ruling"


def _internal_headers() -> dict:
    from tests.test_source_readings import _internal_headers as headers

    return headers()


# --- 공개 상세는 이 사실을 말하지 않는다 -------------------------------------------


@pytest.mark.django_db
def test_the_public_contest_detail_never_reveals_that_an_appeal_exists(
    client, category, landing_type
):
    """공개 응답에 「이의로 보류 중」이 실리면 참가자의 분쟁이 공개된다 (#81).

    #74 가 이 필드를 공개 `ContestOut` 에 넣지 **않기로** 한 이유이고, 그래서
    Sponsor 스코프 표면이 따로 필요했다. 여기가 그 결정을 붙잡아 두는 자리다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-public", sponsor_ci="ci-public",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-public", "ci-dev-public")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    public = client.get(f"/api/contests/{contest['id']}")

    assert public.status_code == 200
    body = public.content.decode()
    assert "appeal" not in body
    assert "보류" not in body


# --- 나머지 단계들 ---------------------------------------------------------------


@pytest.mark.django_db
def test_an_unpaid_draft_says_it_needs_payment(client, category, landing_type):
    """초안인 채로 두면 아무 일도 일어나지 않는다 — 그 사실을 말할 곳이 여기다.

    공개 목록은 draft 를 감추므로, 결제하지 않은 공모전은 지금까지 개최자에게도
    보이지 않았다.
    """

    sponsor = _verified_user(client, "sponsor-draft", "ci-draft")
    created = client.post(
        "/api/contests",
        data={
            "title": "결제하지 않은 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 900_000,
            "deadline_at": (timezone.now() + timedelta(days=3)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert created.status_code == 200, created.content

    row = _mine(client, sponsor["access"])[0]

    assert row["status"] == "draft"
    assert row["next_action"] == "pay_to_publish"


@pytest.mark.django_db
def test_after_awarding_the_row_asks_the_sponsor_to_accept_the_handover(
    client, category, landing_type
):
    """선정했으면 인수 확인이 **Sponsor 차례**다.

    확인하지 않아도 기간이 지나면 Escrow 는 풀리지만, 그때까지 개발자의 돈이
    묶인다 — 개최자가 그것을 모른 채 방치하지 않게 한다.
    """

    awarded = _awarded_contest(client, category, landing_type, uid="accept")

    row = _mine(client, awarded["sponsor"]["access"])[0]

    assert row["next_action"] == "accept_handover"


@pytest.mark.django_db
def test_after_accepting_the_handover_the_sponsor_has_nothing_left_to_do(
    client, category, landing_type
):
    """인수 확인 뒤에는 개발자와 지급대행사 사이의 일이다 — 개최자는 기다린다.

    지급 진행 상태를 개최자에게 자세히 보여주지 않는 것은 의도다: 수취인 등록도
    주민등록번호도 개최자가 알 일이 아니다.
    """

    awarded = _awarded_contest(client, category, landing_type, uid="released")
    from tests.test_payouts import _accept_handover

    _accept_handover(client, awarded["sponsor"], awarded["contest"]["id"])

    row = _mine(client, awarded["sponsor"]["access"])[0]

    assert row["next_action"] == "awaiting_payout"


def _awarded_contest(client, category, landing_type, *, uid: str) -> dict:
    """채점까지 끝난 Contest 에 Award 를 하나 걸어둔다."""

    from tests.test_payouts import _award

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid=f"sponsor-{uid}", sponsor_ci=f"ci-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, f"dev-{uid}", f"ci-dev-{uid}")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _award(client, sponsor, contest["id"], submission["id"])

    return {"sponsor": sponsor, "contest": contest, "submission": submission, "dev": dev}


@pytest.mark.django_db
def test_when_the_judging_window_closes_the_row_stops_asking_to_judge(
    client, category, landing_type
):
    """심사기간이 지나면 「심사하세요」가 사라진다 — API 가 거절할 일을 권하지 않는다.

    스토리 40 의 대조군이기도 하다: 이의가 없으면 같은 시점에 「배분 대기」다.
    「보류」와 「대기」가 같아 보이면 #81 이 하려던 구분이 사라진다.
    """

    from core.models import ClockOverride
    from contests.models import Contest

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-lapsed", sponsor_ci="ci-lapsed",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-lapsed", "ci-dev-lapsed")
    _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    assert _mine(client, sponsor["access"])[0]["next_action"] == "judge_and_award"

    row = Contest.objects.get(id=contest["id"])
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": row.judging_ends_at + timedelta(minutes=1)}
    )
    client.post("/api/internal/tick", **_internal_headers())

    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_distribution"


@pytest.mark.django_db
def test_a_partially_scored_contest_still_tells_the_sponsor_to_judge(
    client, category, landing_type
):
    """한 건의 채점이 막혀도 심사는 열려 있어야 한다.

    「전부 채점됨」을 요구하면 채점이 계속 실패하는 제출 하나가 개최자를
    심사기간 내내 「채점 대기」에 가둔다 — 그러면 고를 수 있었던 결과를 못 고른
    채 무응답 배분으로 넘어간다. Award 는 Score 를 조회조차 하지 않으므로
    (ADR-0006/0014) 심사 자체는 언제든 가능하다: 화면이 API 가 허용하는 행위를
    감추면 안 된다.
    """

    from django.test import override_settings

    from scoring.models import Score

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-partial", sponsor_ci="ci-partial",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev_a = _verified_user(client, "dev-partial-a", "ci-partial-a")
    dev_b = _verified_user(client, "dev-partial-b", "ci-partial-b")
    a = _submit(client, dev_a, contest["id"], requirement_id=requirement_id)
    b = _submit(client, dev_b, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)

    # b 의 채점만 실패시킨다 — 저장소가 이미 가진 실패 주입 경로다
    # (`LLM_FAKE_RAISING_SUBMISSION_IDS`). Score 는 append-only 라 지울 수 없고,
    # 지울 수 있다 해도 그건 실제로 일어나는 모양이 아니다.
    with override_settings(LLM_FAKE_RAISING_SUBMISSION_IDS={b["id"]}):
        _run_scoring(client)

    assert Score.objects.filter(submission_id=a["id"]).exists()
    assert not Score.objects.filter(submission_id=b["id"]).exists()

    assert _mine(client, sponsor["access"])[0]["next_action"] == "judge_and_award"


# --- 코드리뷰가 잡은 두 구멍 -----------------------------------------------------


@pytest.mark.django_db
def test_a_contest_where_no_submission_could_be_scored_still_offers_judging(
    client, category, landing_type
):
    """채점이 **전량** 실패해도 심사는 열려 있다 (코드리뷰 지적).

    「하나라도 채점됨」을 바깥 조건으로 두면, 소스가 사라져 채점이 영영 성공하지
    못하는 공모전은 심사기간 내내 「채점 대기」에 갇히고 심사 링크도 사라진다.
    Award 도 심사 비교도 Score 를 조회조차 하지 않는데 그렇다.
    """

    from django.test import override_settings

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-allfail", sponsor_ci="ci-allfail",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-allfail", "ci-dev-allfail")
    only = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)

    with override_settings(LLM_FAKE_RAISING_SUBMISSION_IDS={only["id"]}):
        _run_scoring(client)

    # 채점 전에는 「보여줄 것이 아직 없다」가 맞다. 문제는 그 뒤다.
    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_scoring"

    # 심사기간이 지나면 더는 「채점 대기」가 아니다 — 채점 게이트가 심사 창
    # 밖으로 새면 배분이 끝난 뒤에도 영원히 「채점 대기」라고 말한다.
    from core.models import ClockOverride
    from contests.models import Contest

    row = Contest.objects.get(id=contest["id"])
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": row.judging_ends_at + timedelta(minutes=1)}
    )
    client.post("/api/internal/tick", **_internal_headers())

    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_distribution"


@pytest.mark.django_db
def test_a_distribution_whose_payouts_have_not_settled_is_not_called_complete(
    client, category, landing_type
):
    """배분 행이 생긴 것과 돈이 간 것은 다르다 (코드리뷰 지적).

    지급이 실패해 매 스캔 재시도되는 중에도 `Distribution` 행은 있다. 그때
    「완료되었습니다」라고 하면 개최자는 끝났다고 믿는다 — Award 경로는 이미
    `Payout.Status.CONFIRMED` 를 확인하고서야 완료라고 하므로 비대칭이기도 했다.
    """

    from core.models import ClockOverride
    from contests.models import Contest
    from distributions.models import Distribution
    from policies.scope import current_policy

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-unsettled", sponsor_ci="ci-unsettled",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-unsettled", "ci-dev-unsettled")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    row = Contest.objects.get(id=contest["id"])
    policy = current_policy()
    ClockOverride.objects.update_or_create(
        pk=1,
        defaults={
            "overridden_at": row.judging_ends_at
            + timedelta(days=policy.distribution_wait_days + 1)
        },
    )

    # 스캔이 Contest 를 JUDGING_ENDED 로 옮겨야 배분 후보가 된다 — 전이 스캔만 돌린다(`/tick`
    # 은 배분·지급 스캔까지 한 바퀴 돌아 아래의 실패 주입보다 먼저 지급을 끝내 버린다, #137).
    client.post("/api/internal/scans/contest-judging-end", **_internal_headers())

    # 이 Submission 의 지급만 실패시킨 채 배분을 돌린다 — 저장소가 이미 가진 실패 주입
    # 경로다(distribution-share-payout 스캔의 `fail_submission_ids` params, #140).
    client.post("/api/internal/scans/distribution-create", **_internal_headers())
    client.post(
        "/api/internal/scans/distribution-share-payout",
        data={"params": {"fail_submission_ids": [submission["id"]]}},
        content_type="application/json",
        **_internal_headers(),
    )

    assert Distribution.objects.filter(contest_id=contest["id"]).exists()
    assert _mine(client, sponsor["access"])[0]["next_action"] == "awaiting_payout"


# --- #152: 커서 페이지네이션 --------------------------------------------------------


def _clone_contests(count: int, *, profile, category) -> None:
    """개최자에게 딸린 공모전을 `count` 개 더 만든다 — 페이지네이션 부피용이다.

    HTTP 흐름(`_publish_contest`)을 스물몇 번 다시 태울 이유가 없다 — 여기서
    확인할 것은 개최·결제가 아니라 목록이 자라는 동안 커서가 버티는가다.
    픽스처는 ORM 으로, 단언은 HTTP 로(운영자 지급 큐의 `_clone_blocked_payouts`
    와 같은 관용구, #151).
    """

    from contests.models import Contest

    for index in range(count):
        Contest.objects.create(
            sponsor=profile,
            title=f"{profile.display_name} 사본 {index}",
            category=category,
            prize=900_000,
            deadline_at=timezone.now() + timedelta(hours=1),
            status=Contest.Status.PUBLISHED,
        )


@pytest.mark.django_db
def test_my_contests_does_not_repeat_or_lose_a_row_when_the_list_grows(
    client, category, landing_type
):
    """1페이지를 받은 뒤 공모전이 하나 더 생겨도 「더 보기」가 같은 행을 두 번
    그리지 않고, 경계에 있던 행을 잃지 않는다 (#152).

    개최자가 목록을 넘기는 동안 공모전을 하나 더 열면 머리에 새 행이 들어온다 —
    오프셋이면 그 몇 초 사이에 경계가 밀려 2페이지가 1페이지의 마지막 행을 다시
    돌려주고, 원래 그 자리에 와야 했던 행은 어느 페이지에도 안 나온다(#151 이
    운영자 지급 큐에서 세운 것과 같은 시나리오).
    """

    from accounts.models import SponsorProfile

    sponsor, _first_contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-152-1", sponsor_ci="ci-152-1",
    )
    profile = SponsorProfile.objects.get(user_id=sponsor["user_id"])
    _clone_contests(24, profile=profile, category=category)

    first = client.get(MY_CONTESTS_URL, **_auth_header(sponsor["access"]))
    assert first.status_code == 200, first.content
    first_body = first.json()
    first_ids = [row["contest_id"] for row in first_body["items"]]
    assert len(first_ids) == 20
    assert first_body["next"], "더 있는데 다음 커서를 주지 않았다"

    # **여기서 목록이 자란다** — 개최자가 공모전을 셋 더 연다.
    _clone_contests(3, profile=profile, category=category)

    second = client.get(
        f"{MY_CONTESTS_URL}?after={first_body['next']}", **_auth_header(sponsor["access"])
    )
    assert second.status_code == 200, second.content
    second_ids = [row["contest_id"] for row in second.json()["items"]]

    assert not set(first_ids) & set(second_ids), (
        "목록이 자란 뒤 2페이지가 1페이지의 행을 다시 돌려줬다"
    )
    # 1페이지 이후로 밀린 다섯(25건 중 나머지)은 그대로 나온다 — 새로 생긴 셋은
    # 이미 지나간 커서보다 앞이라 나오지 않는 것이 옳다(그건 다음 조회의 몫이다).
    assert len(second_ids) == 5, second_ids


@pytest.mark.django_db
def test_my_contests_rejects_a_cursor_it_cannot_read(client, category, landing_type):
    """읽을 수 없는 커서는 조용히 처음부터가 아니라 422 다 (#152) — 운영자 지급
    큐와 같은 규율(#151)."""

    sponsor, _contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-152-2", sponsor_ci="ci-152-2",
    )

    response = client.get(
        f"{MY_CONTESTS_URL}?after=not-a-cursor", **_auth_header(sponsor["access"])
    )

    assert response.status_code == 422, response.content


# --- 「수정하기」 — can_edit 은 수정 게이트와 같은 판정이다 (#881) -------------------


@pytest.mark.django_db
def test_can_edit_is_true_for_draft_and_published_and_false_after_close(
    client, category, landing_type
):
    """초안·공개 중에는 수정하기가 보이고, 마감 뒤에는 보이지 않는다 — 같은 행이
    PUT 게이트(409)와 어긋나지 않는다."""

    from tests.test_source_readings import CONTESTS_URL

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-edit", sponsor_ci="ci-edit", deadline_at=deadline,
    )
    draft = client.post(
        CONTESTS_URL,
        data={
            "title": "초안 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 900_000,
            "deadline_at": (timezone.now() + timedelta(days=3)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert draft.status_code == 200, draft.content

    by_id = {row["contest_id"]: row for row in _mine(client, sponsor["access"])}
    assert by_id[draft.json()["id"]]["can_edit"] is True
    assert by_id[contest["id"]]["can_edit"] is True

    _close_contest(client, contest, deadline=deadline)

    by_id = {row["contest_id"]: row for row in _mine(client, sponsor["access"])}
    assert by_id[contest["id"]]["can_edit"] is False
    assert by_id[draft.json()["id"]]["can_edit"] is True
