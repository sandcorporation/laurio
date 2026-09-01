"""Developer 가 자기 Submission 의 채점 결과를 본다 (#74).

**이게 없으면 이의 제기는 화면이 아니다.** 지금까지 Score 가 노출되는 곳은
운영자의 이의 상세(`AppealDetailOut`) 하나뿐이었다 — 즉 이의를 제기한 다음에야,
그것도 제기한 본인이 아니라 심판하는 운영자만 볼 수 있었다. 「채점이 끝났다」는
알림을 받은 Developer 가 무엇에 이의를 제기할지 볼 데가 없었던 것이다.

**`prompt` 는 주지 않는다.** 프롬프트에는 본인 소스가 통째로 임베드되어 있어
(`scoring._build_prompt`) 본인에게 보여도 유출은 아니지만, 응답 크기에 상한이
사라진다 — 이 저장소는 상한 없는 필드가 4xx 가 나야 할 자리에서 500 을 내는 것을
이미 겪었다(#72). 재현이 필요한 자리는 이의 심판이고, 그 경로는 ADR-0022 가
따로 세워 뒀다(펼치면 `SourceReading` 이 남는다).

시임은 언제나 HTTP 다(CLAUDE.md).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType

from tests.test_source_readings import (
    _close_contest,
    _login,
    _publish_contest,
    _run_scoring,
    _submit,
    _verified_user,
)


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _score_url(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/score"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.fixture
def scored(client, category, landing_type):
    """채점까지 끝난 Submission 하나와 그 주인을 돌려준다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-own-score", "ci-own-score")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return {"submission_id": submission["id"], "dev": dev, "contest": contest}


@pytest.mark.django_db
def test_the_owner_sees_the_score_that_was_given_to_their_submission(client, scored):
    """채점이 끝나면 주인은 점수와 Requirement 별 판정 근거를 본다."""

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(scored["dev"]["access"])
    )

    assert response.status_code == 200
    body = response.json()
    # 컷라인 판정의 근거가 되는 값이므로 문자열로 정확히 준다 — float 로 만들면
    # 화면이 반올림해 보여준 값과 배분이 쓴 값이 갈릴 수 있다.
    assert body["percentage"] == "100.00"
    assert body["model_version"]
    assert isinstance(body["reasoning"], list)
    assert body["reasoning"], "Requirement 별 판정 근거가 비어 있으면 이의를 쓸 수 없다"
    assert "reasoning" in body["reasoning"][0]
    assert body["created_at"]


@pytest.mark.django_db
def test_the_score_response_never_carries_the_prompt(client, scored):
    """프롬프트는 본인 소스를 통째로 안고 있다 — 응답 크기에 상한이 사라진다."""

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(scored["dev"]["access"])
    )

    assert response.status_code == 200
    assert "prompt" not in response.json()


@pytest.mark.django_db
def test_another_developer_cannot_read_someone_elses_score(client, scored, category):
    """남의 점수는 못 본다 — 소유권은 이 표면의 전제다."""

    intruder = _verified_user(client, "dev-intruder", "ci-intruder")

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(intruder["access"])
    )

    # **404 를 허용하지 않는다.** 라우트가 아예 없어도 404 라서, 그렇게 두면 이
    # 테스트는 엔드포인트가 존재하지 않을 때도 통과한다 — 실제로 red 단계에서
    # 혼자 초록이었다.
    assert response.status_code == 403


@pytest.mark.django_db
def test_asking_for_a_score_before_scoring_says_so_instead_of_failing(
    client, category, landing_type
):
    """마감 전에는 404 다 — 「아직 채점되지 않았다」와 「그런 제출이 없다」는 다르다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-unscored", "ci-unscored")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )

    response = client.get(_score_url(submission["id"]), **_auth_header(dev["access"]))

    assert response.status_code == 404
    assert "채점" in response.json()["detail"]


@pytest.mark.django_db
def test_reading_a_score_requires_authentication(client, scored):
    """비로그인은 401 이다 — 「내」 점수를 보는 표면이므로 신원이 먼저다."""

    response = client.get(_score_url(scored["submission_id"]))

    assert response.status_code == 401


# --- 이의 창이 언제 닫히는지 (#74 스토리 15·13·14) --------------------------------
#
# 기한을 만들어 놓고 화면에 안 적으면, 그 기한은 "달력을 들고 계산한 사람에게만"
# 유리한 함정이 된다. 창이 닫히는 시각과 지금 낼 수 있는지를 채점 결과와 같은
# 응답에 넣는다 — 점수를 여는 것이 곧 창을 여는 사건이고, 이의 화면이 이미
# 부르는 응답이 이것뿐이다.


@pytest.mark.django_db
def test_the_score_says_when_the_appeal_window_closes(client, scored):
    """언제까지 낼 수 있는지가 화면에 있을 사실이어야 한다."""

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(scored["dev"]["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["appeal_deadline"], "이의 기한이 없으면 화면이 계산해야 한다"
    assert body["can_appeal"] is True


@pytest.mark.django_db
def test_after_the_judging_period_ends_the_score_says_the_window_is_closed(client, scored):
    """기한이 지나면 `can_appeal` 이 False 다 — 화면이 버튼을 감출 근거가 된다.

    조건은 `appeals.api.create_appeal` 이 쓰는 것과 같은 함수에서 나온다
    (`submissions.participation.within_appeal_window`). 두 벌로 쓰면 언젠가
    갈라지고, 그때 화면은 이의를 권해놓고 API 가 거절한다.
    """

    from core.models import ClockOverride
    from contests.models import Contest

    contest = Contest.objects.get(id=scored["contest"]["id"])
    assert contest.judging_ends_at is not None
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": contest.judging_ends_at + timedelta(minutes=1)}
    )

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(scored["dev"]["access"])
    )

    assert response.status_code == 200
    assert response.json()["can_appeal"] is False


@pytest.mark.django_db
def test_once_an_appeal_exists_the_score_no_longer_offers_another(client, scored):
    """이미 냈으면 못 낸다 — 중복 거절과 같은 조건이다."""

    client.post(
        f"/api/submissions/{scored['submission_id']}/appeal",
        data={"reason": "Evidence 가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth_header(scored["dev"]["access"]),
    )

    response = client.get(
        _score_url(scored["submission_id"]), **_auth_header(scored["dev"]["access"])
    )

    assert response.json()["can_appeal"] is False
