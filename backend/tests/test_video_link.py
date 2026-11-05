# ruff: noqa: F811 — category·landing_type 픽스처를 test_submissions 에서 가져온다
"""시연 영상 링크(`video_link`, #910) — 검증·공개 범위·합산 한도·채움률·확인 위치."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import ClockOverride
from submissions.models import SubmissionAsset
from tests.submission_assets import assets_of, values_of
from tests.test_contest_metrics import METRICS_URL
from tests.test_submissions import (  # noqa: F401 — category·landing_type 는 픽스처
    SUBMISSIONS_URL,
    _auth_header,
    _demo_video_object_key,
    _edit,
    _login,
    _publish_contest,
    _source_object_key,
    _submit,
    _verified_user,
    category,
    landing_type,
)

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def _assets(contest, dev, *extra):
    return {
        "assets": [
            {
                "kind": "source",
                "value": _source_object_key(contest["id"], dev["user_id"]),
            },
            *extra,
        ]
    }


@pytest.fixture
def setup(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    return sponsor, contest, dev, deadline


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url", [YOUTUBE, "http://example.com/v.mp4", "https://youtu.be/dQw4w9WgXcQ?t=30"]
)
def test_http_and_https_links_are_accepted(client, setup, url):
    _sponsor, contest, dev, _ = setup
    response = _submit(
        client,
        dev["access"],
        contest["id"],
        _assets(contest, dev, {"kind": "video_link", "value": url, "label": "시연"}),
    )
    assert response.status_code == 201, response.content
    assert values_of(response.json(), "video_link") == [url]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "ftp://example.com/v.mp4",
        "https://user:pass@example.com/v",
        "https://@example.com/v",
        "https:///nohost",
        "example.com/no-scheme",
        "https://example.com:notaport/v",
        "https://example.com/" + "a" * 2000,
    ],
)
def test_unsafe_or_malformed_links_are_rejected(client, setup, url):
    _sponsor, contest, dev, _ = setup
    response = _submit(
        client,
        dev["access"],
        contest["id"],
        _assets(contest, dev, {"kind": "video_link", "value": url}),
    )
    assert response.status_code == 422, response.content


@pytest.mark.django_db
def test_link_is_hidden_from_strangers_until_deadline_then_public(client, setup):
    _sponsor, contest, dev, deadline = setup
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        _assets(contest, dev, {"kind": "video_link", "value": YOUTUBE}),
    )
    submission_id = created.json()["id"]

    stranger = _login(client, uid="anyone")
    before = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(stranger["access"])
    )
    assert before.status_code == 404

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    after = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert after.status_code == 200
    assert values_of(after.json(), "video_link") == [YOUTUBE]
    assert assets_of(after.json(), "source") == []


@pytest.mark.django_db
def test_files_and_links_share_the_demo_video_limit(client, setup):
    from policies.services import get_current_policy

    _sponsor, contest, dev, _ = setup
    policy = get_current_policy()
    policy.max_demo_video_assets = 2
    policy.save(update_fields=["max_demo_video_assets"])
    video = {
        "kind": "demo_video",
        "value": _demo_video_object_key(contest["id"], dev["user_id"]),
    }
    link_a = {"kind": "video_link", "value": YOUTUBE}
    link_b = {"kind": "video_link", "value": "https://example.com/b"}

    rejected = _submit(
        client,
        dev["access"],
        contest["id"],
        _assets(contest, dev, video, link_a, link_b),
    )
    assert rejected.status_code == 422
    accepted = _submit(
        client, dev["access"], contest["id"], _assets(contest, dev, video, link_a)
    )
    assert accepted.status_code == 201, accepted.content


@pytest.mark.django_db
def test_link_only_counts_as_demo_video_in_completion(client, setup):
    sponsor, contest, dev, _ = setup
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        _assets(contest, dev, {"kind": "video_link", "value": YOUTUBE}),
    )
    assert created.status_code == 201, created.content

    response = client.get(
        METRICS_URL.format(contest_id=contest["id"]), **_auth_header(sponsor["access"])
    )
    assert response.status_code == 200, response.content
    assert response.json()["completion_distribution"]["demo_video_count"] == 1


@pytest.mark.django_db
def test_video_timestamp_evidence_can_point_at_a_link(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "요구", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    requirement_id = contest["requirements"][0]["id"]
    payload = _assets(contest, dev, {"kind": "video_link", "value": YOUTUBE})
    created = _submit(client, dev["access"], contest["id"], payload)
    link_id = assets_of(created.json(), "video_link")[0]["id"]
    payload["assets"][1]["id"] = link_id
    payload["requirement_responses"] = [
        {
            "requirement_id": requirement_id,
            "is_met": True,
            "evidence": [
                {"kind": "video_timestamp", "value": "01:23", "asset_id": link_id}
            ],
        }
    ]
    updated = _edit(client, dev["access"], contest["id"], payload)
    assert updated.status_code == 200, updated.content
    assert SubmissionAsset.objects.get(pk=link_id).evidence_items.count() == 1
