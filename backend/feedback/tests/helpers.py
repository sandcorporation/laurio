"""feedback 시험이 나눠 쓰는 HTTP 도우미 — 시임은 HTTP 다(ORM 으로 상태를 만들지 않는다)."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from storage.adapters.fake import FakeStorageAdapter

ORIGIN = "http://testserver"
PW = "operator-pw-9942-xkcd-feedback"
PERMISSIONS_URL = "/api/operator/feedback-permissions"
REPORTS_URL = "/api/feedback/reports"
UPLOAD_URL = "/api/feedback/screenshot-upload-url"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64


def operator_client(username: str, *, superuser: bool = True) -> Client:
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


class Reporter:
    """로그인한 사용자 하나 — 요청마다 Bearer 를 싣는다."""

    def __init__(self, uid: str) -> None:
        email = f"{uid}@example.com"
        response = Client().post(
            "/api/auth/social/kakao/login",
            data={"access_token": f"{uid}:{email}"},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        self.user = get_user_model().objects.get(email=email)
        self._headers = {"HTTP_AUTHORIZATION": f"Bearer {response.json()['access']}"}
        self.client = Client()

    def get(self, url: str):
        return self.client.get(url, **self._headers)

    def post(self, url: str, data: dict):
        return self.client.post(url, data=data, content_type="application/json", **self._headers)

    def upload_screenshot(self, content: bytes = PNG, content_type: str = "image/png") -> str:
        response = self.post(UPLOAD_URL, {"content_type": content_type})
        assert response.status_code == 200, response.content
        key = response.json()["object_key"]
        FakeStorageAdapter().write_object(key, content, content_type=content_type)
        return key

    def report(self, **overrides):
        data = {
            "kind": "bug",
            "body": "제출 버튼이 눌리지 않아요",
            "app": "contest",
            "page_url": "https://codemit.kr/contests/1",
            "user_agent": "Mozilla/5.0 시험",
            "screen_width": 1440,
            "screen_height": 900,
        }
        data.update(overrides)
        return self.post(REPORTS_URL, data)


def set_permission(operator: Client, user_id: int, *, granted: bool, reason: str = "제보 테스터"):
    return operator.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": granted, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def granted_reporter(uid: str, operator: Client) -> Reporter:
    reporter = Reporter(uid)
    response = set_permission(operator, reporter.user.pk, granted=True)
    assert response.status_code == 200, response.content
    return reporter
