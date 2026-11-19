"""저장소 다운로드 상한이 운영 설정이다(#1005) — 화면에서 저장한 값이 같은 프로세스의 다음 다운로드부터 먹고,
범위 밖 값은 저장이 거절된다."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client

from policies.runtime_settings import refresh_settings, repository_download_limit_bytes
from repositories.adapters import GitHubAdapterError, GitHubAPIAdapter

OPERATOR_URL = "/api/operator/runtime-settings"
OPERATOR_PW = "operator-pw-limit-1005-zzz"
KEY = "REPOSITORY_DOWNLOAD_LIMIT_MB"
ORIGIN = "http://testserver"


class _Response:
    def __init__(self, *, status_code=200, json_body=None, chunks=()):
        self.status_code = status_code
        self._json = json_body
        self._chunks = list(chunks)
        self.headers = {}

    def json(self):
        return self._json

    def iter_content(self, chunk_size=65536):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _clone(monkeypatch, chunks):
    def fake_get(url, *args, **kwargs):
        if url == "https://api.github.com/repos/acme/widgets":
            return _Response(json_body={"default_branch": "main", "private": False})
        if "/branches/" in url:
            return _Response(json_body={"commit": {"sha": "c" * 40}})
        return _Response(chunks=chunks)

    monkeypatch.setattr("requests.get", fake_get)
    return GitHubAPIAdapter(token="").clone("https://github.com/acme/widgets")


@pytest.fixture
def operator(db):
    call_command("create_operator", "limit_super", password=OPERATOR_PW, superuser=True)
    client = Client()
    login = client.post(
        "/api/operator/login",
        data={"username": "limit_super", "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert login.status_code == 200
    return client


def _save(client, value, callbacks):
    with callbacks(execute=True):
        return client.post(
            f"{OPERATOR_URL}/{KEY}", data={"value": value}, content_type="application/json", HTTP_ORIGIN=ORIGIN
        )


def test_the_screen_lists_the_limit_with_its_range_in_the_label_and_default_100(operator):
    rows = {s["key"]: s for s in operator.get(OPERATOR_URL, HTTP_ORIGIN=ORIGIN).json()["settings"]}
    row = rows[KEY]
    assert (row["kind"], row["default"], row["source"]) == ("float", "100", "none")
    assert "1~200" in row["label"]


def test_a_saved_value_applies_to_the_next_download_without_a_restart(
    operator, monkeypatch, django_capture_on_commit_callbacks
):
    assert _save(operator, "1", django_capture_on_commit_callbacks).status_code == 200
    refresh_settings()
    assert repository_download_limit_bytes() == 1_000_000
    with pytest.raises(GitHubAdapterError, match="다운로드 상한"):
        _clone(monkeypatch, [b"x" * 600_000, b"y" * 600_000])

    assert _save(operator, "2", django_capture_on_commit_callbacks).status_code == 200
    refresh_settings()
    assert len(_clone(monkeypatch, [b"x" * 600_000, b"y" * 600_000]).zip_bytes) == 1_200_000


@pytest.mark.parametrize("value", ["0", "0.5", "201", "-5", "nope"])
def test_a_value_outside_the_range_is_refused_with_the_reason(
    operator, django_capture_on_commit_callbacks, value
):
    response = _save(operator, value, django_capture_on_commit_callbacks)
    assert response.status_code in (400, 422)
    refresh_settings()
    assert repository_download_limit_bytes() == 100_000_000
