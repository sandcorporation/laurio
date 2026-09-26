"""저장소 가시성 스캔(`repository-visibility`)은 공모전 제출물만 본다 (GlitchTip 오류 80).

이 스캔의 후보 조건은 「공모전 채점(`scoring.Score`)이 아직 없다」인데, 강의실
제출물(#286)도 같은 `SubmissionAsset` 테이블에 저장소 자료를 두고 **공모전 Score 는
영영 생기지 않는다**(강의실 채점은 `ClassroomScore`다). 그래서 강의실 저장소 하나가
한 시간마다(`_STALE_AFTER`) 영원히 GitHub 을 다시 쳤다 — 쓰는 곳도 없는 값이다
(강의실 채점은 채점 시점에 `check_public` 을 직접 부른다). 제출이 쌓일수록 호출이
끝없이 늘어, prod 의 인증 없는 GitHub API 한도(시간당 60)가 `rate limit exceeded`
403 으로 막혔다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings

from core.clock import Clock
from submissions.models import SubmissionAsset

CLASSES_URL = "/api/classroom/classes"
VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


def _login(client, uid: str) -> dict:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _submit_classroom_repository(client, url: str) -> None:
    instructor = _login(client, "instructor-1")
    created = client.post(
        CLASSES_URL,
        data={"name": "웹 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth(instructor["access"]),
    )
    assert created.status_code == 201
    class_id = created.json()["id"]

    problem = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth(instructor["access"]),
    )
    assert problem.status_code == 201
    problem_id = problem.json()["id"]
    item = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth(instructor["access"]),
    )
    assert item.status_code == 201
    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth(instructor["access"]),
    )
    assert opened.status_code == 200

    join_code = client.get(f"{CLASSES_URL}/{class_id}", **_auth(instructor["access"])).json()["join_code"]
    participant = _login(client, "participant-1")
    joined = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": "참여자"},
        content_type="application/json",
        **_auth(participant["access"]),
    )
    assert joined.status_code == 200

    submitted = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url, "submission_format": "repository"},
        content_type="application/json",
        **_auth(participant["access"]),
    )
    assert submitted.status_code == 201, submitted.content


def _run_visibility_scan(client) -> dict:
    response = client.post(
        VISIBILITY_SCAN_URL,
        content_type="application/json",
        HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN,
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.mark.django_db
def test_visibility_scan_never_calls_github_for_classroom_repositories(client):
    _submit_classroom_repository(client, "https://github.com/octocat/hello")
    asset = SubmissionAsset.objects.get(kind=SubmissionAsset.Kind.REPOSITORY)

    # 처음 보는 때와, 한 시간(`_STALE_AFTER`)이 지나 다시 보는 때 — 둘 다 후보가 아니어야
    # 한다. 예전에는 둘 다 이 자산을 집었고, 그 뒤로도 매시간 영원히 집었다.
    first = _run_visibility_scan(client)
    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": Clock.now() + timedelta(hours=2)})
    later = _run_visibility_scan(client)

    assert [r["asset_id"] for r in first["rows"]] == []
    assert [r["asset_id"] for r in later["rows"]] == []
    asset.refresh_from_db()
    assert asset.is_public_checked_at is None
