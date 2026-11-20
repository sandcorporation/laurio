"""수신자 화면이 벤더 오류와 내부 참조를 그대로 보여주던 것을 고친다(#244).

`NotificationDispatch.failure_reason`은 애초에 운영자용으로 쓰인 자유서술이라
ADR 번호(`adapters_aligo.py`의 "ADR-0009" 인용)·내부 사업 상태("사전심사 대기
중")·과금 기준("과금은 LMS 기준")·벤더 원문 오류("aligo-rejected(code=-101)")가
섞여 있다. ADR-0009는 채널별 발송 이력 자체는 그대로 보존·노출하라고 요구하지만
(연락받은 적 없다는 항의의 방어선), 그 문구의 "청중"까지 사용자로 정한 적은
없다.

이 프로젝트의 유일한 테스트 시임은 HTTP다(CLAUDE.md) — 그래서 여기서도
`/api/notifications/me`(수신자 본인, jwt_auth)와 `/api/internal/notifications`
(운영자/내부 도구, InternalAuth)를 실제로 쳐서 두 청중이 받는 값이 갈리는지
확인한다. `NotificationDispatch`를 ORM으로 직접 만드는 것은 `tests/
test_notifications.py`의 재선점 테스트들과 같은 성격의 픽스처 준비일 뿐이다 —
실제 검증은 두 GET 요청의 JSON 바디로 한다.

이 테스트는 새 Notification을 실제 발송 로직(quiet-hours 포함)에 태우지 않고
완성된 상태의 행을 직접 만들어 확인하므로, 벽시계가 야간(21~08시, ADR-0010)
이어도 결과가 갈리지 않는다 — 시간을 시임으로 쓰지 않는다(ADR-0003).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from notifications.models import Notification, NotificationDispatch, NotificationType

KST = ZoneInfo("Asia/Seoul")

ME_URL = "/api/notifications/me"
INTERNAL_DETAIL_URL_TMPL = "/api/internal/notifications/{id}"

# 실제 staging 사고(티켓 본문)에 나온 네 가지 누출을 그대로 재현한다 — 내부 문서
# 번호, 내부 사업 상태, 내부 과금 기준, 벤더 원문 오류.
_LEAKY_REASONS = {
    "alimtalk": "알림톡 템플릿 사전심사 대기 중 — SMS/LMS로 대체발송한다(ADR-0009)",
    "sms": (
        "메시지가 SMS 한도를 넘어 LMS로 승격되어 발송됨(과금은 LMS 기준) — "
        "aligo-rejected(code=-101): 인증오류입니다.-IP"
    ),
    "lms": "aligo-rejected(code=-101): 인증오류입니다.-IP",
}

_LEAKED_FRAGMENTS = [
    "ADR-0009",
    "사전심사",
    "과금은",
    "LMS 기준",
    "aligo-rejected",
    "code=-101",
    "인증오류",
]


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid: str):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(pair: dict) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"}


def _user_id_from_me(client, pair) -> int:
    response = client.get("/api/accounts/me", **_auth_header(pair))
    assert response.status_code == 200
    return response.json()["id"]


def _make_all_channels_exhausted_notification(user) -> Notification:
    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.RESULT_NOTICE,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.FAILED,
        created_at=stuck_at,
    )
    for channel, reason in _LEAKY_REASONS.items():
        NotificationDispatch.objects.create(
            notification=notification,
            channel=channel,
            status=NotificationDispatch.Status.FAILED,
            attempted_at=stuck_at,
            failure_reason=reason,
        )
    return notification


@pytest.mark.django_db
def test_recipient_facing_list_does_not_leak_vendor_or_internal_text(client):
    pair = _login(client, "leak-recipient")
    user_id = _user_id_from_me(client, pair)
    user = get_user_model().objects.get(pk=user_id)

    _make_all_channels_exhausted_notification(user)

    body = client.get(ME_URL, **_auth_header(pair)).json()["items"]
    assert len(body) == 1
    dispatches = body[0]["dispatches"]
    assert len(dispatches) == 3

    for dispatch in dispatches:
        reason = dispatch["failure_reason"]
        # AC: 사유를 모르는 실패도 이력에 남는다 — 빈칸이 아니다.
        assert reason
        for fragment in _LEAKED_FRAGMENTS:
            assert fragment not in reason, f"{fragment!r} leaked into {reason!r}"


@pytest.mark.django_db
def test_recipient_facing_list_still_shows_channel_status_and_attempt_time(client):
    """AC: 채널별 시도 시각과 결과는 계속 보인다 — ADR-0009의 이력 자체는 안
    지운다. 사라지는 것은 원문 사유 하나뿐이다."""

    pair = _login(client, "leak-recipient-timeline")
    user_id = _user_id_from_me(client, pair)
    user = get_user_model().objects.get(pk=user_id)

    notification = _make_all_channels_exhausted_notification(user)

    body = client.get(ME_URL, **_auth_header(pair)).json()["items"]
    dispatches = {d["channel"]: d for d in body[0]["dispatches"]}

    assert set(dispatches) == {"alimtalk", "sms", "lms"}
    for channel, dispatch in dispatches.items():
        assert dispatch["status"] == "failed"
        assert dispatch["attempted_at"] == notification.dispatches.get(channel=channel).attempted_at.isoformat()


@pytest.mark.django_db
def test_operator_facing_internal_endpoint_still_returns_raw_reason(client):
    """AC: 운영자는 여전히 원문을 본다 — 내부 엔드포인트는 이 티켓이 손대지
    않는다."""

    user = get_user_model().objects.create_user(username="leak-operator-target")
    notification = _make_all_channels_exhausted_notification(user)

    response = client.get(
        INTERNAL_DETAIL_URL_TMPL.format(id=notification.id), **_internal_headers()
    )
    assert response.status_code == 200, response.content
    body = response.json()

    reasons = {d["channel"]: d["failure_reason"] for d in body["dispatches"]}
    assert reasons == _LEAKY_REASONS


@pytest.mark.django_db
def test_recipient_facing_reason_is_generated_from_one_place_per_status(client):
    """AC: 사용자용 문구가 한 자리에서 만들어진다 — 같은 status는 같은 채널
    이더라도 원문 내용과 무관하게 항상 같은 문구로 나온다(원문을 들여다보지
    않는다는 뜻)."""

    pair = _login(client, "leak-recipient-uniform")
    user_id = _user_id_from_me(client, pair)
    user = get_user_model().objects.get(pk=user_id)

    stuck_at = datetime(2026, 1, 10, 14, 0, tzinfo=KST)
    notification = Notification.objects.create(
        recipient=user,
        notification_type=NotificationType.RESULT_NOTICE,
        is_transactional=True,
        is_promotional=False,
        status=Notification.Status.FAILED,
        created_at=stuck_at,
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="sms",
        status=NotificationDispatch.Status.FAILED,
        attempted_at=stuck_at,
        failure_reason="이 문구는 완전히 다른, 처음 보는 내부 문장이다",
    )
    NotificationDispatch.objects.create(
        notification=notification,
        channel="lms",
        status=NotificationDispatch.Status.FAILED,
        attempted_at=stuck_at,
        failure_reason=_LEAKY_REASONS["lms"],
    )

    body = client.get(ME_URL, **_auth_header(pair)).json()["items"]
    reasons_by_channel = {d["channel"]: d["failure_reason"] for d in body[0]["dispatches"]}
    assert reasons_by_channel["sms"] == reasons_by_channel["lms"]
