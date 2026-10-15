"""저장소 가시성 스캔(`repository-visibility`)이 GitHub 한도를 아끼는 두 길 (#490).

천장은 「동시에 열려 있는 저장소 제출 수」였다 — 채점 안 된 저장소 자산 하나당 한 시간에
한 번 GitHub REST 를 쳤고, 인증 토큰의 한도는 시간당 5,000회다(#486 이 그 모양을
한 번 봤다). 둘로 천장을 「실제로 바뀐 저장소 수」로 옮긴다:

- **조건부 요청** — 저장소 조회 응답의 ETag 를 자산에 두고 다음 조회에 `If-None-Match`
  로 보낸다. 304 면 그 호출은 한도에 세지 않고(GitHub 문서), `is_public` 은 그대로
  두고 `is_public_checked_at` 만 갱신한다.
- **값에 따라 다른 확인 주기** — 한 번 공개로 확인된 것은 길게(`_STALE_AFTER_PUBLIC`),
  아직 모르는 것·비공개로 확인된 것·마감이 임박한 것은 지금처럼 한 시간이다.

전제(「예전에 이렇게 확인했다」)는 실제 스캔을 돌려 세우고, 시간은 `ClockOverride` 로
옮긴다 — ORM 으로 상태를 만들지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, DeliverableType
from core.models import ClockOverride
from submissions.models import SubmissionAsset
from tests.test_repository_reachability_recheck import _repository_url, _submit_repository_only
from tests.test_source_readings import _publish_contest, _verified_user

VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _submit_contest_repository(client, category, landing_type, *, repo_url: str, deadline_at) -> int:
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline_at,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"], repo_url=repo_url
    )
    return SubmissionAsset.objects.get(
        submission_id=submission["id"], kind=SubmissionAsset.Kind.REPOSITORY
    ).id


def _scan_at(client, at) -> list[int]:
    """시각을 `at` 으로 옮기고 스캔 한 바퀴 — 이번에 본 자산 id 목록을 돌려준다."""

    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})
    response = client.post(
        VISIBILITY_SCAN_URL, content_type="application/json", HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN
    )
    assert response.status_code == 200, response.content
    return [row["asset_id"] for row in response.json()["rows"]]


@pytest.mark.django_db
def test_a_repository_confirmed_public_is_not_rechecked_before_the_long_interval(
    client, category, landing_type
):
    """공개로 확인된 저장소는 한 시간이 지나도 다시 후보가 아니다 — 12시간이 지나야
    다시 본다. 공개 여부는 거의 바뀌지 않고, 늦게 반영되는 대가(화면 배지)는 ADR-0003 이
    허용한 범위다. 채점은 어차피 채점 시점에 직접 재확인한다(#219)."""

    now = timezone.now()
    asset_id = _submit_contest_repository(
        client, category, landing_type, repo_url=_repository_url("public-org"), deadline_at=now + timedelta(days=10)
    )

    assert _scan_at(client, now) == [asset_id]
    assert SubmissionAsset.objects.get(pk=asset_id).is_public is True
    assert _scan_at(client, now + timedelta(hours=2)) == []
    assert _scan_at(client, now + timedelta(hours=11)) == []
    assert _scan_at(client, now + timedelta(hours=13)) == [asset_id]


@pytest.mark.django_db
def test_a_repository_confirmed_private_keeps_the_hourly_interval(client, category, landing_type):
    """비공개로 확인된 저장소는 지금처럼 한 시간마다 본다 — 참가자가 공개로 바꾼 뒤 배지가
    반영되기까지의 지연은 여기서만 생기고, 그 길이는 바꾸지 않는다."""

    now = timezone.now()
    asset_id = _submit_contest_repository(
        client, category, landing_type, repo_url=_repository_url("private-org"), deadline_at=now + timedelta(days=10)
    )

    assert _scan_at(client, now) == [asset_id]
    assert SubmissionAsset.objects.get(pk=asset_id).is_public is False
    assert _scan_at(client, now + timedelta(minutes=30)) == []
    assert _scan_at(client, now + timedelta(hours=2)) == [asset_id]


@pytest.mark.django_db
def test_a_public_repository_is_rechecked_hourly_once_the_deadline_is_within_the_long_interval(
    client, category, landing_type
):
    """마감까지 12시간이 안 남으면 공개로 확인된 것도 한 시간마다 본다 — 긴 주기를 그대로
    두면 마감 직전에 비공개로 바뀐 것을 마감 전 화면이 한 번도 못 본다."""

    now = timezone.now()
    asset_id = _submit_contest_repository(
        client, category, landing_type, repo_url=_repository_url("public-org"), deadline_at=now + timedelta(hours=10)
    )

    assert _scan_at(client, now) == [asset_id]
    assert _scan_at(client, now + timedelta(hours=2)) == [asset_id]


class _EtagGitHub:
    """저장소 하나짜리 GitHub — `If-None-Match` 가 지금 ETag 와 같으면 304 를 준다."""

    def __init__(self, *, etag: str, private: bool):
        self.etag = etag
        self.private = private
        self.sent_headers: list[dict] = []

    def __call__(self, url, *args, headers=None, **kwargs):
        self.sent_headers.append(dict(headers or {}))
        if (headers or {}).get("If-None-Match") == self.etag:
            return _Response(status_code=304, headers={"ETag": self.etag})
        return _Response(status_code=200, json_body={"private": self.private}, headers={"ETag": self.etag})


class _Response:
    def __init__(self, *, status_code, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self.headers = headers or {}

    def json(self):
        return self._json_body


@pytest.mark.django_db
def test_the_scan_sends_the_stored_etag_and_a_304_keeps_is_public_but_refreshes_checked_at(
    monkeypatch, client, category, landing_type
):
    """두 번째 확인부터는 자산에 둔 ETag 를 `If-None-Match` 로 보낸다. 304 면 `is_public`
    은 그대로, `is_public_checked_at` 만 이번 시각이다. 표현이 바뀌어(비공개 전환) 200 이
    오면 새 값과 새 ETag 를 쓴다."""

    github = _EtagGitHub(etag='"v1"', private=False)
    monkeypatch.setattr("requests.get", github)
    now = timezone.now()
    asset_id = _submit_contest_repository(
        client, category, landing_type, repo_url=_repository_url("etag-org"), deadline_at=now + timedelta(days=10)
    )

    with override_settings(GITHUB_ADAPTER_MODE="repositories.adapters.GitHubAPIAdapter"):
        assert _scan_at(client, now) == [asset_id]
        asset = SubmissionAsset.objects.get(pk=asset_id)
        assert (asset.is_public, asset.is_public_etag) == (True, '"v1"')
        assert "If-None-Match" not in github.sent_headers[0]

        later = now + timedelta(hours=13)
        assert _scan_at(client, later) == [asset_id]
        asset.refresh_from_db()
        assert github.sent_headers[1]["If-None-Match"] == '"v1"'
        assert (asset.is_public, asset.is_public_etag, asset.is_public_checked_at) == (True, '"v1"', later)

        github.etag, github.private = '"v2"', True
        latest = later + timedelta(hours=13)
        assert _scan_at(client, latest) == [asset_id]
        asset.refresh_from_db()
        assert github.sent_headers[2]["If-None-Match"] == '"v1"'
        assert (asset.is_public, asset.is_public_etag, asset.is_public_checked_at) == (False, '"v2"', latest)
