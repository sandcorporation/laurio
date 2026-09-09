"""자동 0% Score 가 자기 사유를 참가자에게는 순화해서, 운영자에게는 원문 그대로
말한다 (#246, ADR-0006/0030/0031).

**#244가 알림에서 푼 것과 같은 문제.** `Score`는 append-only라(ADR-0006)
ADR-0030(참가자가 저장소를 닫았다)·ADR-0031(플랫폼이 채점하지 못했다)의 자동
미달이 남긴 `reasoning` 원문(ADR 번호·내부 임계값 그대로)을 고칠 수 없다.
그래서 참가자가 보는 `submissions.schemas.OwnScoreOut`은 직렬화 시점에 이
문구를 새로 파생하고(`submissions.scoring_basis.participant_facing_reasoning`),
운영자가 심판 근거로 보는 `appeals.schemas.ScoreSnapshotOut`은 원문을 그대로
낸다.

핵심 대상:

- 세 성격(AI 판정 / 참가자 귀책 채점 입력 없음 / 플랫폼 귀책 채점 실패 상한)
  모두 `scoring_basis`라는 기계가 읽을 수 있는 값으로 갈린다.
- 자동 0% 둘 다 참가자 응답에서는 문장이 Requirement 개수만큼 반복되지
  않는다(한 번만 나온다) — 플랫폼 귀책(ADR-0031) 쪽은 저장된 원문 자체에 ADR
  번호·내부 임계값(5회, 6시간)이 박혀 있어 그것도 함께 사라진다.
- 운영자 응답은 두 경우 모두 원문(Requirement별 반복, 플랫폼 귀책 쪽은 ADR
  번호까지)을 그대로 유지한다 — 이의 심판이 ADR-0030과 ADR-0031을 정확히
  구별해야 한다.
- AI가 실제로 판정한 경우는 참가자·운영자 양쪽 다 지금과 똑같이 Requirement별
  근거를 그대로 본다.

시임은 언제나 HTTP 다(CLAUDE.md).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, DeliverableType
from scoring.models import Score

from tests.test_source_readings import (
    CONTESTS_URL,
    _auth_header,
    _close_contest,
    _internal_headers,
    _operator_client,
    _publish_contest,
    _run_scoring,
    _submit,
    _verified_user,
)

OPERATOR_APPEALS_URL = "/api/operator/appeals"
SCORING_RUN_PENDING_URL = "/api/internal/scans/submission-scoring"
VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _score_url(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/score"


def _appeal_url(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/appeal"


def _repository_url(owner: str) -> str:
    return f"https://github.com/{owner}/repo-{uuid.uuid4().hex[:12]}"


def _submit_repository_only(client, dev: dict, contest_id: int, *, requirement_id: int, repo_url: str) -> dict:
    """소스 자료 없이 저장소 하나만 낸다 — ADR-0030의 자동 미달(#218)을 재현하는
    최소 형태다. 참가자가 통제하는 상태만 판정에 쓴다는 원칙대로, owner에
    "private"가 들어가면 `FakeGitHubAdapter.check_public()`이 확정적으로
    False를 돌려준다."""

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [{"kind": "repository", "value": repo_url}],
            "requirement_responses": [{"requirement_id": requirement_id, "is_met": False}],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _run_visibility_scan(client) -> dict:
    response = client.post(VISIBILITY_SCAN_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _create_appeal(client, dev: dict, submission_id: int) -> int:
    response = client.post(
        _appeal_url(submission_id),
        data={"reason": "이 판정이 왜 그런지 확인하고 싶습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def _operator_appeal_detail(appeal_id: int) -> dict:
    operator = _operator_client()
    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")
    assert detail.status_code == 200
    return detail.json()


# --- AI가 실제로 판정한 경우 — 지금과 똑같이 보인다 -------------------------------


@pytest.mark.django_db
def test_ai_judged_score_reports_ai_judged_basis_and_unchanged_reasoning(
    client, category, landing_type
):
    """AI가 실제로 채점했으면 `scoring_basis`가 "ai_judged"이고, `reasoning`은
    Requirement별 근거를 그대로 담는다 — 자동 0%가 아니므로 파생이 끼어들지
    않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-ai-judged", "ci-ai-judged")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    own_score = client.get(_score_url(submission["id"]), **_auth_header(dev["access"]))
    assert own_score.status_code == 200
    body = own_score.json()
    assert body["scoring_basis"] == "ai_judged"

    score = Score.objects.get(submission_id=submission["id"])
    assert body["reasoning"] == score.reasoning

    appeal_id = _create_appeal(client, dev, submission["id"])
    detail = _operator_appeal_detail(appeal_id)
    assert detail["score"]["scoring_basis"] == "ai_judged"
    assert detail["score"]["reasoning"] == score.reasoning


# --- ADR-0030: 참가자 귀책 — 채점할 입력이 없었다 --------------------------------


@pytest.mark.django_db
def test_no_scoring_input_score_says_it_once_instead_of_per_requirement(
    client, category, landing_type
):
    """소스 없이 저장소만 냈고 그 저장소가 확정적으로 비공개면(ADR-0030) 참가자
    응답은 "no_scoring_input"을 말한다. 저장된 원문 자체엔 ADR 번호가 없지만
    (`scoring.services._NO_SCORING_INPUT_REASONING`) Requirement 개수만큼
    반복되는 것은 참가자·운영자 공통 문제다(#246 AC) — 참가자 쪽만 한 번으로
    접힌다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-no-input", "ci-no-input")
    repo_url = _repository_url("private-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )
    # 가시성 스캔이 한 번 확정해야 채점 스캔이 이 제출을 후보로 집는다 — 아직
    # is_public이 null인 저장소는 "아직 모른다"로 미뤄지고 채점되지 않는다
    # (`test_repository_scoring.py::
    # test_scoring_is_deferred_while_repository_visibility_is_still_unresolved`).
    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)
    assert result["rows"][0]["status"] == "scored"

    score = Score.objects.get(submission_id=submission["id"])
    assert score.model_version == "platform-auto (채점 입력 없음)"
    # Requirement가 둘인데 원문은 Requirement 개수만큼 반복된다 — 아래
    # "한 번만" 단언이 처음부터 무의미하지 않다는 사전 확인이다.
    assert len(score.reasoning) == 2

    own_score = client.get(_score_url(submission["id"]), **_auth_header(dev["access"]))
    assert own_score.status_code == 200
    body = own_score.json()
    assert body["scoring_basis"] == "no_scoring_input"

    reasoning = body["reasoning"]
    # 같은 문장이 Requirement 개수만큼 반복되지 않는다 — 한 번만 말한다.
    assert len(reasoning) == 1
    text = reasoning[0]["reasoning"]
    assert "ADR" not in text
    assert "5회" not in text and "6시간" not in text
    # 무슨 일이 있었는지는 여전히 말한다.
    assert "채점" in text


@pytest.mark.django_db
def test_no_scoring_input_score_keeps_the_original_verbatim_for_the_operator(
    client, category, landing_type
):
    """운영자가 심판 근거로 보는 스냅샷은 저장된 원문과 Requirement별 반복을
    그대로 유지한다 — 참가자 쪽만 한 문장으로 접히고 감사 기록은 순화되지
    않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-no-input-op", "ci-no-input-op")
    repo_url = _repository_url("private-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )
    # 가시성 스캔이 한 번 확정해야 채점 스캔이 이 제출을 후보로 집는다 — 아직
    # is_public이 null인 저장소는 "아직 모른다"로 미뤄지고 채점되지 않는다
    # (`test_repository_scoring.py::
    # test_scoring_is_deferred_while_repository_visibility_is_still_unresolved`).
    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    score = Score.objects.get(submission_id=submission["id"])
    appeal_id = _create_appeal(client, dev, submission["id"])
    detail = _operator_appeal_detail(appeal_id)

    assert detail["score"]["scoring_basis"] == "no_scoring_input"
    assert detail["score"]["reasoning"] == score.reasoning
    assert len(detail["score"]["reasoning"]) == 2


# --- ADR-0031: 플랫폼 귀책 — 채점이 반복 실패해 상한에 도달했다 --------------------


def _finalize_via_permanent_failure(client, submission_id: int) -> None:
    """`LLMAdapterPermanentError`로 즉시 0%까지 확정한다(ADR-0031) —
    `tests.test_scoring._PermanentFailureAdapter`를 그대로 재사용한다."""

    with override_settings(
        LLM_ADAPTER_MODE="tests.test_scoring._PermanentFailureAdapter",
        LLM_PERMANENT_FAILURE_SUBMISSION_IDS=[submission_id],
    ):
        first = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
        assert first.status_code == 200
        statuses = {r["submission_id"]: r["status"] for r in first.json()["rows"]}
        assert statuses[submission_id] == "failed_permanently"

        second = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
        assert second.status_code == 200
        statuses = {r["submission_id"]: r["status"] for r in second.json()["rows"]}
        assert statuses[submission_id] == "scored"


@pytest.mark.django_db
def test_platform_failure_score_hides_adr_references_and_offers_appeal(
    client, category, landing_type
):
    """채점 실패 상한(ADR-0031)에 도달하면 참가자 응답은 "platform_failure"를
    말하고, 문장은 한 번만 나오며 ADR 번호·임계값 없이 이의를 낼 수 있다는
    것까지 말한다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-platform-fail", "ci-platform-fail")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)

    _finalize_via_permanent_failure(client, submission["id"])

    score = Score.objects.get(submission_id=submission["id"])
    assert score.model_version == "platform-auto (채점 실패 상한)"
    assert "ADR-0031" in score.reasoning[0]["reasoning"]
    assert len(score.reasoning) == 2

    own_score = client.get(_score_url(submission["id"]), **_auth_header(dev["access"]))
    assert own_score.status_code == 200
    body = own_score.json()
    assert body["scoring_basis"] == "platform_failure"

    reasoning = body["reasoning"]
    assert len(reasoning) == 1
    text = reasoning[0]["reasoning"]
    assert "ADR" not in text
    assert "5회" not in text and "6시간" not in text
    # 플랫폼 귀책이므로 이의를 낼 수 있다는 것까지 말한다.
    assert "이의" in text

    raw = own_score.content.decode("utf-8")
    assert "ADR-0030" not in raw
    assert "ADR-0031" not in raw


@pytest.mark.django_db
def test_platform_failure_score_keeps_the_original_verbatim_for_the_operator(
    client, category, landing_type
):
    """운영자 스냅샷은 ADR-0031 원문과 Requirement별 반복을 그대로 유지한다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-platform-fail-op", "ci-platform-fail-op")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)

    _finalize_via_permanent_failure(client, submission["id"])

    score = Score.objects.get(submission_id=submission["id"])
    appeal_id = _create_appeal(client, dev, submission["id"])
    detail = _operator_appeal_detail(appeal_id)

    assert detail["score"]["scoring_basis"] == "platform_failure"
    assert detail["score"]["reasoning"] == score.reasoning
    assert len(detail["score"]["reasoning"]) == 2
    assert "ADR-0031" in detail["score"]["reasoning"][0]["reasoning"]
