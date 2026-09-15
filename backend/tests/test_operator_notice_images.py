"""운영팀 알림 이미지 첨부 — 받는 사람만 본다 (#419, CONTEXT.md 「운영자 알림」).

presigned 업로드는 **비공개 버킷**으로 가야 한다 — FakeStorageAdapter는 버킷마다
다른 base_url을 쓰므로(`images_base_url`에 "public-images"가 들어간다), 발급된
주소에 그 문자열이 없는 것으로 비공개 버킷을 확인한다(`tests/test_contest_images.py`
가 공개 버킷을 확인하는 것과 반대 방향).
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

RECIPIENTS_URL = "/api/operator/notifications/operator-notices/recipients"
SEND_URL = "/api/operator/notifications/operator-notices"
UPLOAD_URL_URL = "/api/operator/notifications/operator-notices/image-upload-url"
ME_URL = "/api/notifications/me"

OPERATOR_ORIGIN = "http://testserver"
PUBLIC_IMAGES_MARKER = "public-images"


def _operator_client(username="notice-img-op"):
    call_command("create_operator", username, password="operator-pw-9134-xyz")
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _login_recipient(client, uid="img-recipient", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _request_upload_url(operator, content_type="image/png"):
    return operator.post(
        UPLOAD_URL_URL,
        data={"content_type": content_type},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )


def _send(operator, *, recipient_id, image_object_key="", title="기프티콘", body=""):
    return operator.post(
        SEND_URL,
        data={
            "recipient_id": recipient_id,
            "title": title,
            "body": body,
            "image_object_key": image_object_key,
        },
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )


def test_upload_url_is_issued_for_private_bucket_with_size_condition(client, db):
    operator = _operator_client()

    response = _request_upload_url(operator)

    assert response.status_code == 200, response.content
    body = response.json()
    assert PUBLIC_IMAGES_MARKER not in body["upload_url"]
    assert body["object_key"].startswith("operator-notice-image:")
    # 상한이 있는 업로드는 presigned POST로 발급된다(ADR-0032/0035) — 서명된
    # 정책 필드(fields)가 실려야 크기 상한이 실제로 강제된다.
    assert body["method"] == "POST"
    assert body["fields"]


def test_upload_url_rejects_disallowed_content_type(client, db):
    operator = _operator_client()

    response = _request_upload_url(operator, content_type="image/gif")

    assert response.status_code == 422, response.content


def test_anonymous_cannot_request_upload_url(client, db):
    response = client.post(
        UPLOAD_URL_URL,
        data={"content_type": "image/png"},
        content_type="application/json",
    )
    assert response.status_code in (401, 403)


def test_list_response_has_image_flag_only_no_signed_url(client, db):
    session = _login_recipient(client)
    recipient_id = get_user_model().objects.get(email="img-recipient@example.com").id
    operator = _operator_client()

    object_key = _request_upload_url(operator).json()["object_key"]
    sent = _send(operator, recipient_id=recipient_id, image_object_key=object_key)
    assert sent.status_code == 200, sent.content
    assert sent.json()["has_image"] is True

    listing = client.get(ME_URL, **_auth_header(session["access"])).json()
    assert len(listing) == 1
    row = listing[0]
    assert row["has_image"] is True
    assert "image_object_key" not in row
    assert "download_url" not in row
    assert object_key not in str(row)


def test_notice_without_image_has_image_false(client, db):
    session = _login_recipient(client, uid="img-recipient-2")
    recipient_id = get_user_model().objects.get(email="img-recipient-2@example.com").id
    operator = _operator_client(username="notice-img-op-2")

    _send(operator, recipient_id=recipient_id)

    row = client.get(ME_URL, **_auth_header(session["access"])).json()[0]
    assert row["has_image"] is False


def test_recipient_gets_download_url_other_user_and_anonymous_are_rejected(client, db):
    session = _login_recipient(client, uid="img-recipient-3")
    recipient_id = get_user_model().objects.get(email="img-recipient-3@example.com").id
    operator = _operator_client(username="notice-img-op-3")

    object_key = _request_upload_url(operator).json()["object_key"]
    sent = _send(operator, recipient_id=recipient_id, image_object_key=object_key).json()
    notification_id = sent["notification_id"]
    download_url_path = f"/api/notifications/{notification_id}/image-download"

    ok = client.post(download_url_path, **_auth_header(session["access"]))
    assert ok.status_code == 200, ok.content
    assert PUBLIC_IMAGES_MARKER not in ok.json()["download_url"]
    assert "expires_at" in ok.json()

    other_session = _login_recipient(client, uid="img-recipient-3-other")
    other = client.post(download_url_path, **_auth_header(other_session["access"]))
    assert other.status_code == 404

    anonymous = client.post(download_url_path)
    assert anonymous.status_code in (401, 403)


def test_download_url_is_short_lived(client, db):
    session = _login_recipient(client, uid="img-recipient-4")
    recipient_id = get_user_model().objects.get(email="img-recipient-4@example.com").id
    operator = _operator_client(username="notice-img-op-4")

    object_key = _request_upload_url(operator).json()["object_key"]
    sent = _send(operator, recipient_id=recipient_id, image_object_key=object_key).json()

    before = datetime.now(timezone.utc)
    response = client.post(
        f"/api/notifications/{sent['notification_id']}/image-download",
        **_auth_header(session["access"]),
    )
    expires_at = datetime.fromisoformat(response.json()["expires_at"])

    assert (expires_at - before).total_seconds() <= settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS + 5


def test_sender_operator_can_reopen_image_other_operator_cannot(client, db):
    session_recipient_id_setup = _login_recipient(client, uid="img-recipient-5")
    recipient_id = get_user_model().objects.get(email="img-recipient-5@example.com").id
    operator = _operator_client(username="notice-img-op-5")

    object_key = _request_upload_url(operator).json()["object_key"]
    sent = _send(operator, recipient_id=recipient_id, image_object_key=object_key).json()
    notification_id = sent["notification_id"]

    own = operator.get(
        f"/api/operator/notifications/operator-notices/{notification_id}/image-download"
    )
    assert own.status_code == 200, own.content
    assert PUBLIC_IMAGES_MARKER not in own.json()["download_url"]

    other_operator = _operator_client(username="notice-img-op-5-other")
    other = other_operator.get(
        f"/api/operator/notifications/operator-notices/{notification_id}/image-download"
    )
    assert other.status_code == 404
    assert session_recipient_id_setup  # 세션 자체를 쓰지 않지만 로그인이 성공했는지 확인.


def test_cannot_send_with_another_operators_uploaded_image_key(client, db):
    session = _login_recipient(client, uid="img-recipient-6")
    recipient_id = get_user_model().objects.get(email="img-recipient-6@example.com").id
    operator_a = _operator_client(username="notice-img-op-6a")
    operator_b = _operator_client(username="notice-img-op-6b")

    object_key = _request_upload_url(operator_a).json()["object_key"]

    response = _send(operator_b, recipient_id=recipient_id, image_object_key=object_key)

    assert response.status_code == 422, response.content
    assert session  # 세션 자체를 쓰지 않지만 로그인이 성공했는지 확인.
