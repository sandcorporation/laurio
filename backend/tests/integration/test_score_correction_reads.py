"""정정 행이 있으면 점수를 읽는 자리가 정정 값을 쓴다(#1179, 스펙 #1178).

참가자 점수 API·운영자 이의 상세·이의 소스 펼침·완성도 대상 거르기. 컷라인은
`payouts/tests/test_distributions.py` 에 있다. 정정이 없으면 응답은 지금과 같다(기존 시험들).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ledger.models import AppendOnlyError
from scoring.models import ScoreCorrection
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION
from tests.integration.test_scoring_participant_facing import (
    _create_appeal,
    _score_url,
    category,  # noqa: F401 - 픽스처
    landing_type,  # noqa: F401 - 픽스처
)
from tests.integration.test_source_readings import (
    _auth_header,
    _close_contest,
    _operator_client,
    _publish_contest,
    _reveal_source,
    _run_scoring,
    _submit,
    _verified_user,
)
from tests.score_corrections import correct

OPERATOR_APPEALS_URL = "/api/operator/appeals"


def _scored_submissions(client, category, landing_type, *uids: str) -> list[tuple[dict, dict]]:
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    made = []
    for uid in uids:
        dev = _verified_user(client, uid, f"ci-{uid}")
        made.append((dev, _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])))
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return made


def _scored_submission(client, category, landing_type, uid: str) -> tuple[dict, dict]:
    return _scored_submissions(client, category, landing_type, uid)[0]


@pytest.mark.django_db
def test_own_score_without_correction_says_not_corrected(client, category, landing_type):
    dev, submission = _scored_submission(client, category, landing_type, "dev-plain")

    body = client.get(_score_url(submission["id"]), **_auth_header(dev["access"])).json()

    assert body["corrected"] is False
    assert body["original_percentage"] is None
    assert body["original_model_version"] is None
    assert body["correction_reason"] is None


@pytest.mark.django_db
def test_own_score_and_appeal_detail_show_the_latest_finished_correction(client, category, landing_type):
    dev, submission = _scored_submission(client, category, landing_type, "dev-corrected")
    before = client.get(_score_url(submission["id"]), **_auth_header(dev["access"])).json()

    correct(submission["id"], "12.50", model_version="old-correction")
    correct(submission["id"], "42.00", model_version="fixed-llm-v2", reason="채점기 오류")
    correct(submission["id"], "", status=ScoreCorrection.Status.IN_PROGRESS)
    correct(submission["id"], "", status=ScoreCorrection.Status.FAILED)

    body = client.get(_score_url(submission["id"]), **_auth_header(dev["access"])).json()
    assert body["percentage"] == "42.00"
    assert body["model_version"] == "fixed-llm-v2"
    assert body["corrected"] is True
    assert body["original_percentage"] == before["percentage"]
    assert body["original_model_version"] == before["model_version"]
    assert body["correction_reason"] == "채점기 오류"
    # 「채점된 때」는 원래 Score 의 것 그대로다 — 이의 창이 그것을 본다.
    assert body["created_at"] == before["created_at"]

    appeal_id = _create_appeal(client, dev, submission["id"])
    operator = _operator_client()
    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}").json()["score"]
    assert detail["percentage"] == "42.00"
    assert detail["model_version"] == "fixed-llm-v2"
    assert detail["corrected"] is True
    assert detail["original_percentage"] == before["percentage"]
    assert detail["correction_reason"] == "채점기 오류"

    revealed = _reveal_source(operator, appeal_id)
    assert revealed.status_code == 200, revealed.content
    assert revealed.json()["prompt"] == "정정 채점 프롬프트"


@pytest.mark.django_db
def test_unfinished_correction_leaves_the_original_score(client, category, landing_type):
    dev, submission = _scored_submission(client, category, landing_type, "dev-pending")
    before = client.get(_score_url(submission["id"]), **_auth_header(dev["access"])).json()

    correct(submission["id"], "", status=ScoreCorrection.Status.IN_PROGRESS)

    body = client.get(_score_url(submission["id"]), **_auth_header(dev["access"])).json()
    assert body["percentage"] == before["percentage"]
    assert body["corrected"] is False


@pytest.mark.django_db
def test_quality_targets_follow_the_corrected_model_version(client, category, landing_type):
    """자동 0%(플랫폼 오류)는 완성도를 건너뛴다 — 정정으로 AI 판정이 되면 대상이 되고, 그 반대면 빠진다."""

    from scoring.quality import _pending_quality

    (_, auto_zero), (_, judged) = _scored_submissions(client, category, landing_type, "dev-auto-zero", "dev-judged")
    ids = lambda: set(_pending_quality(None, None).values_list("id", flat=True))  # noqa: E731
    assert judged["id"] in ids()

    correct(judged["id"], "0.00", model_version=PLATFORM_FAILURE_MODEL_VERSION)
    assert judged["id"] not in ids()

    correct(auto_zero["id"], "0.00", model_version=PLATFORM_FAILURE_MODEL_VERSION)
    correct(auto_zero["id"], "80.00", model_version="fixed-llm-v2")
    assert auto_zero["id"] in ids()


@pytest.mark.django_db
def test_finished_correction_cannot_change_or_disappear(client, category, landing_type):
    _, submission = _scored_submission(client, category, landing_type, "dev-immutable")
    pending = correct(submission["id"], "", status=ScoreCorrection.Status.IN_PROGRESS)

    # 진행 중 → 끝은 한 번 넘어간다.
    pending.status = ScoreCorrection.Status.DONE
    pending.percentage = "55.00"
    pending.finished_at = timezone.now()
    pending.save()

    pending.percentage = "99.00"
    with pytest.raises(AppendOnlyError):
        pending.save()
    with pytest.raises(AppendOnlyError):
        pending.delete()
    with pytest.raises(AppendOnlyError):
        ScoreCorrection.objects.filter(pk=pending.pk).update(percentage="1.00")
    with pytest.raises(AppendOnlyError):
        ScoreCorrection.objects.filter(pk=pending.pk).delete()
