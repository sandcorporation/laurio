"""참여자가 공모전 문제의 시도를 「공모전에도 내기」로 공모전에 낸다
(#549, 스펙 #546, ADR-0054, CONTEXT.md 「공모전에도 내기」).

두 앱을 실제로 함께 돌린다. 개최자는 공모전 HTTP 로 열고, 강사는 강의실 HTTP 로 들여오고
열고, 참여자는 강의실 HTTP 로 낸다. 결과는 공모전 「내 제출」(HTTP)에서 본다. 둘 사이는
공유층(`core.contest_catalog`)의 신호만 지나고, 그 신호는 시도가 커밋된 뒤 나가므로
`django_capture_on_commit_callbacks(execute=True)` 로 흘린다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from classroom.models import ClassroomSubmission
from contests.models import Contest, ContestSubmission
from notifications.models import Notification, NotificationType
from storage.adapters.fake import FakeStorageAdapter
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    join_class,
    login,
    mine,
    open_problem,
    user_id,
    zip_bytes,
)
from tests.test_contest_classroom_import import _free_contest, _host, _patch
from tests.test_free_contest_hosting import (  # noqa: F401 — 픽스처 재사용
    CONTESTS_URL,
    _auth_header,
    category,
    landing_type,
)

pytestmark = pytest.mark.django_db

CONSENT_MESSAGE = "수상작의 소스는 개최자가 볼 수 있습니다 — 동의해야 제출할 수 있습니다."


@pytest.fixture(autouse=True)
def _no_scoring_broker(monkeypatch):
    """즉시 채점 큐잉은 이 시험의 관심이 아니다 — 브로커에 붙지 않게 막는다."""

    monkeypatch.setattr("classroom.api._enqueue_immediate_scoring", lambda submission_id: None)


@pytest.fixture
def world(client, category, landing_type):
    host = _host(client, "ce-host")
    contest = _free_contest(client, host, category, landing_type, title="할 일 웹앱")
    instructor = login(client, uid="ce-instructor")
    class_id = create_class(client, instructor["access"])
    imported = client.post(
        f"{CLASSES_URL}/{class_id}/problems/from-contest",
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert imported.status_code == 201, imported.content
    problem = imported.json()
    open_problem(client, instructor["access"], class_id, problem["id"])
    participant = login(client, uid="ce-participant")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return {
        "host": host,
        "contest": contest,
        "instructor": instructor,
        "class_id": class_id,
        "problem": problem,
        "participant": participant,
        "participant_id": user_id("ce-participant"),
    }


def _form(client, world, access=None):
    return client.get(
        f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem']['id']}/contest-entry",
        **auth_header(access or world["participant"]["access"]),
    )


def _requirement_ids(client, world) -> list[int]:
    response = _form(client, world)
    assert response.status_code == 200, response.content
    return [r["requirement_id"] for r in response.json()["requirements"]]


def _entry(requirement_ids, *, evidence="00:12", consent=True, replace=False, optional_assets=None):
    return {
        "source_access_consent": consent,
        "replace_existing": replace,
        "requirement_responses": [
            {
                "requirement_id": requirement_id,
                "is_met": True,
                "note": "구현했다",
                "evidence": [{"kind": "video_timestamp", "value": evidence}],
            }
            for requirement_id in requirement_ids
        ],
        "optional_assets": optional_assets or [],
    }


def _submit(client, world, *, entry=None, access=None, uploader_id=None, capture):
    uploader_id = uploader_id or world["participant_id"]
    object_key = f"classroom-submission:{world['problem']['id']}:{uploader_id}:source/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(object_key, zip_bytes({"app.js": "function add(todo) {}\n"}))
    data = {"submission_format": "source", "value": object_key, "content_type": "application/zip"}
    if entry is not None:
        data["contest_entry"] = entry
    with capture(execute=True):
        return client.post(
            f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem']['id']}/submissions",
            data=data,
            content_type="application/json",
            **auth_header(access or world["participant"]["access"]),
        )


def _latest_attempt(client, world) -> dict:
    """결과는 시도가 커밋된 뒤 신호로 돌아온다 — 운영에서는 같은 요청 안에서(시도 트랜잭션이
    끝나는 순간) 돌아와 응답에 실리지만, 시험의 커밋 콜백은 요청이 끝난 뒤 흐르므로 다시 읽는다."""

    return mine(client, world["participant"]["access"], world["class_id"], world["problem"]["id"])[
        "submissions"
    ][0]


def _my_contest_submission(client, world):
    return client.get(
        f"{CONTESTS_URL}/{world['contest']['id']}/submissions/me",
        **_auth_header(world["participant"]["access"]),
    )


# --- 켜고 낸다 ------------------------------------------------------------------


def test_an_attempt_entered_with_the_switch_on_becomes_my_contest_submission(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    entry = _entry(
        requirement_ids,
        optional_assets=[
            {"kind": "demo_url", "value": "https://todo.example.com"},
            {
                "kind": "screenshot",
                "value": f"{_form(client, world).json()['upload_target_refs']['screenshot']}/shot",
                "content_type": "image/png",
            },
        ],
    )

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 201, response.content

    mine_on_contest = _my_contest_submission(client, world)
    assert mine_on_contest.status_code == 200, mine_on_contest.content
    body = mine_on_contest.json()
    kinds = {a["kind"]: a["value"] for a in body["assets"]}
    # 시도의 소스는 공모전 업로드 대상으로 옮겨진다 — 강의실 업로드 대상을 가리키지 않는다.
    assert kinds["source"].startswith(
        f"submission:{world['contest']['id']}:{world['participant_id']}:source/"
    )
    assert kinds["demo_url"] == "https://todo.example.com"
    assert "screenshot" in kinds
    assert body["source_access_consent_at"] is not None
    responses = {r["requirement_id"]: r for r in body["requirement_responses"]}
    assert set(responses) == set(requirement_ids)
    assert responses[requirement_ids[0]]["evidence"][0]["value"] == "00:12"
    # 그 시도에도 결과가 남는다.
    assert _latest_attempt(client, world)["contest_entry"] == {"status": "entered", "reason": ""}


def test_the_contest_side_has_no_trace_of_the_class(client, world, django_capture_on_commit_callbacks):
    _submit(client, world, entry=_entry(_requirement_ids(client, world)), capture=django_capture_on_commit_callbacks)

    submission = ContestSubmission.objects.get(contest_id=world["contest"]["id"])
    field_names = {f.name for f in ContestSubmission._meta.get_fields()}
    assert not any("class" in name for name in field_names)
    host_view = client.get(f"/api/submissions/{submission.id}", **_auth_header(world["host"]["access"]))
    assert "class" not in host_view.content.decode().lower()


def test_an_attempt_with_the_switch_off_leaves_the_contest_submission_alone_and_the_newest_entry_wins(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    _submit(client, world, entry=_entry(requirement_ids, evidence="첫 시도"), capture=django_capture_on_commit_callbacks)
    first_source = {a["kind"]: a["value"] for a in _my_contest_submission(client, world).json()["assets"]}["source"]

    off = _submit(client, world, capture=django_capture_on_commit_callbacks)
    assert off.json()["contest_entry"] is None
    after_off = _my_contest_submission(client, world).json()
    assert {a["kind"]: a["value"] for a in after_off["assets"]}["source"] == first_source

    _submit(
        client,
        world,
        entry=_entry(requirement_ids, evidence="셋째 시도", replace=True),
        capture=django_capture_on_commit_callbacks,
    )
    after_third = _my_contest_submission(client, world).json()
    assert {a["kind"]: a["value"] for a in after_third["assets"]}["source"] != first_source
    assert after_third["requirement_responses"][0]["evidence"][0]["value"] == "셋째 시도"
    assert ContestSubmission.objects.filter(contest_id=world["contest"]["id"]).count() == 1


# --- 이미 낸 제출이 있으면 확인을 받는다 --------------------------------------------


def test_an_existing_direct_submission_is_not_replaced_without_confirmation(
    client, world, django_capture_on_commit_callbacks
):
    direct = client.post(
        f"{CONTESTS_URL}/{world['contest']['id']}/submissions",
        data={
            "assets": [{"kind": "repository", "value": "https://github.com/me/direct"}],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(world["participant"]["access"]),
    )
    assert direct.status_code == 201, direct.content
    requirement_ids = _requirement_ids(client, world)
    assert _form(client, world).json()["has_entry"] is True

    unconfirmed = _submit(client, world, entry=_entry(requirement_ids), capture=django_capture_on_commit_callbacks)

    assert unconfirmed.status_code == 409, unconfirmed.content
    assert "이 시도로 바뀝니다" in unconfirmed.json()["detail"]
    assert ClassroomSubmission.objects.count() == 0
    kinds = {a["kind"] for a in _my_contest_submission(client, world).json()["assets"]}
    assert kinds == {"repository"}

    confirmed = _submit(
        client, world, entry=_entry(requirement_ids, replace=True), capture=django_capture_on_commit_callbacks
    )

    assert confirmed.status_code == 201, confirmed.content
    assert _latest_attempt(client, world)["contest_entry"]["status"] == "entered"
    kinds = {a["kind"] for a in _my_contest_submission(client, world).json()["assets"]}
    assert kinds == {"source"}


def test_the_form_prefills_the_previous_entry_and_leaves_new_requirements_blank(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    _submit(client, world, entry=_entry(requirement_ids, evidence="01:00"), capture=django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        added = client.post(
            f"{CONTESTS_URL}/{world['contest']['id']}/requirements",
            data={"text": "할 일을 지울 수 있다", "grade": "required"},
            content_type="application/json",
            **_auth_header(world["host"]["access"]),
        )
    assert added.status_code == 200, added.content

    form = _form(client, world).json()

    assert form["has_entry"] is True
    previous = {r["text"]: r["previous"] for r in form["requirements"]}
    assert previous["할 일을 추가할 수 있다"]["evidence"] == [
        {"kind": "video_timestamp", "value": "01:00", "asset_index": None}
    ]
    assert previous["할 일을 지울 수 있다"] is None
    assert set(form["upload_target_refs"]) == {"demo_video", "screenshot"}


# --- 시도를 만들기 전에 막는다 ------------------------------------------------------


def test_missing_consent_is_refused_before_the_attempt_is_made(client, world, django_capture_on_commit_callbacks):
    response = _submit(
        client, world, entry=_entry(_requirement_ids(client, world), consent=False), capture=django_capture_on_commit_callbacks
    )

    assert response.status_code == 422
    assert response.json()["detail"] == CONSENT_MESSAGE
    assert ClassroomSubmission.objects.count() == 0


def test_badly_shaped_evidence_is_refused_before_the_attempt_is_made(
    client, world, django_capture_on_commit_callbacks
):
    entry = _entry(_requirement_ids(client, world))
    entry["requirement_responses"][0]["evidence"][0]["kind"] = "telepathy"

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert "근거 종류" in response.json()["detail"]
    assert ClassroomSubmission.objects.count() == 0


def test_a_requirement_from_another_contest_is_refused(client, world, django_capture_on_commit_callbacks):
    response = _submit(client, world, entry=_entry([999_999]), capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert ClassroomSubmission.objects.count() == 0


def test_source_or_repository_cannot_ride_along_as_optional_material(
    client, world, django_capture_on_commit_callbacks
):
    entry = _entry(
        _requirement_ids(client, world),
        optional_assets=[{"kind": "repository", "value": "https://github.com/me/extra"}],
    )

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert "선택 자료" in response.json()["detail"]


def test_the_instructors_own_attempt_with_the_switch_on_becomes_their_contest_submission(
    client, world, django_capture_on_commit_callbacks
):
    instructor = world["instructor"]
    instructor_id = user_id("ce-instructor")
    form = _form(client, world, access=instructor["access"])
    assert form.status_code == 200, form.content
    assert form.json()["accepts_entries"] is True
    requirement_ids = [r["requirement_id"] for r in form.json()["requirements"]]

    response = _submit(
        client,
        world,
        entry=_entry(requirement_ids),
        access=instructor["access"],
        uploader_id=instructor_id,
        capture=django_capture_on_commit_callbacks,
    )

    assert response.status_code == 201, response.content
    submission = ContestSubmission.objects.get(contest_id=world["contest"]["id"])
    assert submission.user_id == instructor_id
    attempt = mine(client, instructor["access"], world["class_id"], world["problem"]["id"])["submissions"][0]
    assert attempt["contest_entry"] == {"status": "entered", "reason": ""}


def test_the_instructors_own_attempt_with_the_switch_off_sends_nothing(
    client, world, django_capture_on_commit_callbacks
):
    instructor = world["instructor"]

    response = _submit(
        client,
        world,
        access=instructor["access"],
        uploader_id=user_id("ce-instructor"),
        capture=django_capture_on_commit_callbacks,
    )

    assert response.status_code == 201, response.content
    assert not ContestSubmission.objects.filter(contest_id=world["contest"]["id"]).exists()


def test_the_switch_disappears_when_the_host_withdraws_the_allowance(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    with django_capture_on_commit_callbacks(execute=True):
        _patch(client, world["host"], world["contest"]["id"], allows_classroom_import=False)

    assert _form(client, world).json()["accepts_entries"] is False
    response = _submit(client, world, entry=_entry(requirement_ids), capture=django_capture_on_commit_callbacks)
    assert response.status_code == 422
    # 끄고 내는 것은 그대로 된다 — 평범한 문제로 남는다.
    assert _submit(client, world, capture=django_capture_on_commit_callbacks).status_code == 201


# --- 경합: 공모전이 받을 때 거절한다 --------------------------------------------------


def test_a_contest_that_closes_in_between_rejects_and_the_attempt_stays_with_a_notice(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    object_key = f"classroom-submission:{world['problem']['id']}:{world['participant_id']}:source/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(object_key, zip_bytes({"app.js": "x"}))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = client.post(
            f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem']['id']}/submissions",
            data={
                "submission_format": "source",
                "value": object_key,
                "content_type": "application/zip",
                "contest_entry": _entry(requirement_ids),
            },
            content_type="application/json",
            **auth_header(world["participant"]["access"]),
        )
    assert response.status_code == 201, response.content
    # 시도는 커밋됐고, 공모전에 닿기 전에 마감이 지났다.
    Contest.objects.filter(pk=world["contest"]["id"]).update(deadline_at=timezone.now() - timedelta(seconds=1))
    for callback in callbacks:
        callback()

    attempt = _latest_attempt(client, world)
    assert attempt["contest_entry"]["status"] == "rejected"
    assert "출품을 받지 않습니다" in attempt["contest_entry"]["reason"]
    assert not ContestSubmission.objects.filter(contest_id=world["contest"]["id"]).exists()
    notice = Notification.objects.get(
        recipient__username="kakao:ce-participant",
        notification_type=NotificationType.CLASSROOM_CONTEST_ENTRY_REJECTED,
    )
    assert notice.context["submission_id"] == attempt["id"]


# --- 직접 제출과 같은 항목 (#921) ---------------------------------------------------

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_a_video_link_is_accepted_and_shows_up_like_a_direct_submission(
    client, world, django_capture_on_commit_callbacks
):
    entry = _entry(
        _requirement_ids(client, world),
        optional_assets=[{"kind": "video_link", "value": YOUTUBE, "label": "시연"}],
    )

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 201, response.content
    body = _my_contest_submission(client, world).json()
    links = [a for a in body["assets"] if a["kind"] == "video_link"]
    assert [a["value"] for a in links] == [YOUTUBE]
    assert links[0]["label"] == "시연"
    # 같은 SubmissionAsset 이라 직접 제출과 같은 직렬화 키로 나온다.
    assert set(links[0]) == set(next(a for a in body["assets"] if a["kind"] == "source"))
    assert ContestSubmission.objects.get().assets.filter(kind="video_link").count() == 1


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "https://user:pass@example.com/v", "ftp://example.com/v.mp4"]
)
def test_an_unsafe_video_link_is_refused_with_the_direct_submission_message(
    client, world, django_capture_on_commit_callbacks, url
):
    from submissions.video_link import VIDEO_LINK_SHAPE_MESSAGE

    entry = _entry(_requirement_ids(client, world), optional_assets=[{"kind": "video_link", "value": url}])

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert response.json()["detail"] == VIDEO_LINK_SHAPE_MESSAGE
    assert ClassroomSubmission.objects.count() == 0


def test_video_files_and_links_share_the_demo_video_limit(
    client, world, django_capture_on_commit_callbacks
):
    from policies.services import get_current_policy

    policy = get_current_policy()
    policy.max_demo_video_assets = 1
    policy.save(update_fields=["max_demo_video_assets"])
    video_ref = _form(client, world).json()["upload_target_refs"]["demo_video"]
    entry = _entry(
        _requirement_ids(client, world),
        optional_assets=[
            {"kind": "demo_video", "value": f"{video_ref}/v", "content_type": "video/mp4"},
            {"kind": "video_link", "value": YOUTUBE},
        ],
    )

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert "합쳐 최대" in response.json()["detail"]


def test_the_form_prefills_the_video_link_so_re_entering_keeps_it(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    entry = _entry(requirement_ids, optional_assets=[{"kind": "video_link", "value": YOUTUBE}])
    _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    form = _form(client, world).json()

    assert [(a["kind"], a["value"]) for a in form["optional_assets"]] == [("video_link", YOUTUBE)]


def test_an_evidence_pointing_at_an_optional_asset_is_linked_to_the_new_asset(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    entry = _entry(
        requirement_ids,
        optional_assets=[
            {"kind": "demo_url", "value": "https://todo.example.com"},
            {"kind": "video_link", "value": YOUTUBE},
        ],
    )
    entry["requirement_responses"][0]["evidence"][0]["asset_index"] = 1

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 201, response.content
    body = _my_contest_submission(client, world).json()
    link = next(a for a in body["assets"] if a["kind"] == "video_link")
    by_req = {r["requirement_id"]: r for r in body["requirement_responses"]}
    assert by_req[requirement_ids[0]]["evidence"][0]["asset_id"] == link["id"]
    if len(requirement_ids) > 1:
        assert by_req[requirement_ids[1]]["evidence"][0]["asset_id"] is None
    # 다시 열면 순번으로 미리 채워진다.
    previous = {r["requirement_id"]: r["previous"] for r in _form(client, world).json()["requirements"]}
    assert previous[requirement_ids[0]]["evidence"][0]["asset_index"] == 1


def test_an_evidence_pointing_outside_the_entry_assets_is_refused(
    client, world, django_capture_on_commit_callbacks
):
    entry = _entry(_requirement_ids(client, world))
    entry["requirement_responses"][0]["evidence"][0]["asset_index"] = 0

    response = _submit(client, world, entry=entry, capture=django_capture_on_commit_callbacks)

    assert response.status_code == 422
    assert "확인 위치" in response.json()["detail"]
    assert ClassroomSubmission.objects.count() == 0
