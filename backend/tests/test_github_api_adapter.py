"""`repositories.adapters.GitHubAPIAdapter` 단위 테스트 (#193, ADR-0007).

`tests/test_openai_scoring_adapter.py`와 같은 예외 — 이 파일도 HTTP를 거치지
않는다. `GitHubAPIAdapter`는 Codemit 자신의 API가 아니라 GitHub 벤더 연동
URL 조립·파싱 로직이다(어느 django-ninja 라우터에도 매여 있지 않다). 네트워크도
치지 않는다 — `requests.get`을 몽키패치해 벤더 응답을 흉내낸다.
"""

from __future__ import annotations

import pytest

from repositories.adapters import GitHubAPIAdapter, GitHubAdapterError


class _FakeResponse:
    def __init__(self, *, status_code=200, json_body=None, chunks=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body
        self._chunks = chunks or []
        self.headers = headers or {}

    def json(self):
        return self._json_body

    def iter_content(self, chunk_size=65536):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_clone_percent_encodes_branch_names_that_contain_a_slash(monkeypatch):
    """GitHub 브랜치 이름에는 슬래시가 유효하다("release/2024") — 인코딩하지
    않으면 브랜치 조회 URL이 `.../branches/release/2024`가 되어 GitHub이 그
    경로를 브랜치 이름으로 풀지 않는다. 매 재시도가 같은 깨진 URL을 만드므로,
    공개 저장소인데도 영원히 clone되지 못한다(#193 코드리뷰 지적) — 이 값은
    `submissions.models.GITHUB_REPO_URL_PATTERN`이 제약하는 owner/repo와 달리
    GitHub API 응답에서 그대로 온 값이라 우리가 형식을 통제할 수 없다.
    """

    requested_branch_urls: list[str] = []

    def fake_get(url, *args, **kwargs):
        if url == "https://api.github.com/repos/acme/widgets":
            return _FakeResponse(
                status_code=200,
                json_body={"default_branch": "release/2024", "private": False},
            )
        if "/branches/" in url:
            requested_branch_urls.append(url)
            return _FakeResponse(
                status_code=200, json_body={"commit": {"sha": "a" * 40}}
            )
        if url.startswith("https://codeload.github.com/"):
            return _FakeResponse(status_code=200, chunks=[b"PK\x03\x04fake-zip"])
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("requests.get", fake_get)

    adapter = GitHubAPIAdapter(token="")
    result = adapter.clone("https://github.com/acme/widgets")

    assert requested_branch_urls == [
        "https://api.github.com/repos/acme/widgets/branches/release%2F2024"
    ]
    assert result.commit_sha == "a" * 40
    assert result.zip_bytes == b"PK\x03\x04fake-zip"


def _public_repo_get(requested_urls: list[str]):
    """`acme/widgets` 하나만 있는 GitHub — 그 밖의 경로는 실물처럼 404다."""

    def fake_get(url, *args, **kwargs):
        requested_urls.append(url)
        if url == "https://api.github.com/repos/acme/widgets":
            return _FakeResponse(
                status_code=200, json_body={"default_branch": "main", "private": False}
            )
        if url == "https://api.github.com/repos/acme/widgets/branches/main":
            return _FakeResponse(status_code=200, json_body={"commit": {"sha": "b" * 40}})
        if url.startswith("https://codeload.github.com/acme/widgets/"):
            return _FakeResponse(status_code=200, chunks=[b"PK\x03\x04fake-zip"])
        return _FakeResponse(status_code=404)

    return fake_get


def test_a_dot_git_suffix_on_the_repository_url_is_not_part_of_the_repository_name(monkeypatch):
    """`git clone`에 쓰는 모양(`https://github.com/acme/widgets.git`)을 그대로 내는
    참여자가 많다 — GitHub REST API는 `/repos/acme/widgets.git`에 404를 주므로,
    끝의 `.git`을 떼지 않으면 공개 저장소가 「비공개」로 확정되고 강의실 채점이
    실패 상한까지 재시도하다 자동 미달로 끝난다(#537 — prod 21건). GitHub은
    `.git`으로 끝나는 저장소 이름을 허용하지 않으므로 떼어도 다른 저장소를
    가리키게 되지 않는다.
    """

    for url in ("https://github.com/acme/widgets.git", "https://github.com/acme/widgets.git/"):
        requested_urls: list[str] = []
        monkeypatch.setattr("requests.get", _public_repo_get(requested_urls))
        adapter = GitHubAPIAdapter(token="")

        assert adapter.check_public(url) is True
        result = adapter.clone(url)

        assert result.commit_sha == "b" * 40
        assert result.zip_bytes == b"PK\x03\x04fake-zip"
        assert not [u for u in requested_urls if "widgets.git" in u]


def test_a_repository_name_that_is_only_dot_git_is_rejected_rather_than_emptied(monkeypatch):
    """`.git`을 떼고 나면 이름이 비는 URL은 저장소가 아니다 — `/repos/acme/`를
    치게 두지 않고 형식 오류로 거절한다(#537)."""

    monkeypatch.setattr("requests.get", _public_repo_get([]))

    with pytest.raises(GitHubAdapterError):
        GitHubAPIAdapter(token="").check_public("https://github.com/acme/.git")


def _etag_aware_repo_get(requested_headers: list[dict], *, etag: str, private: bool):
    """`acme/widgets` 하나 — 보낸 `If-None-Match` 가 지금 ETag 와 같으면 실물처럼
    본문 없는 304 를 준다."""

    def fake_get(url, *args, headers=None, **kwargs):
        assert url == "https://api.github.com/repos/acme/widgets", url
        requested_headers.append(dict(headers or {}))
        if (headers or {}).get("If-None-Match") == etag:
            return _FakeResponse(status_code=304, headers={"ETag": etag})
        return _FakeResponse(
            status_code=200,
            json_body={"default_branch": "main", "private": private},
            headers={"ETag": etag},
        )

    return fake_get


def test_visibility_check_returns_the_etag_and_sends_it_back_as_if_none_match(monkeypatch):
    """GitHub 은 `Authorization` 을 붙인 조건부 요청이 304 를 받으면 그 호출을 시간당
    한도에 세지 않는다(#490). 첫 조회는 조건 없이 가고 응답의 ETag 를 돌려주며, 그
    ETag 를 넘긴 다음 조회는 `If-None-Match` 로 간다 — 304 면 「지난 확인 그대로」다
    (`is_public` 이 None, ETag 는 그대로)."""

    requested_headers: list[dict] = []
    monkeypatch.setattr(
        "requests.get", _etag_aware_repo_get(requested_headers, etag='"abc123"', private=False)
    )
    adapter = GitHubAPIAdapter(token="")

    first = adapter.check_visibility("https://github.com/acme/widgets")
    assert (first.is_public, first.etag, first.unchanged) == (True, '"abc123"', False)
    assert "If-None-Match" not in requested_headers[0]

    second = adapter.check_visibility("https://github.com/acme/widgets", etag=first.etag)
    assert requested_headers[1]["If-None-Match"] == '"abc123"'
    assert (second.is_public, second.etag, second.unchanged) == (None, '"abc123"', True)


def test_visibility_check_with_a_stale_etag_gets_the_new_value_and_the_new_etag(monkeypatch):
    """저장소가 비공개로 바뀌면 표현이 바뀌어 ETag 도 바뀐다 — 옛 ETag 를 보낸 조회는
    200 과 새 값·새 ETag 를 받고, 그 값을 그대로 쓴다. 비공개는 404 라 ETag 가 없다."""

    requested_headers: list[dict] = []
    monkeypatch.setattr(
        "requests.get", _etag_aware_repo_get(requested_headers, etag='"new"', private=True)
    )
    adapter = GitHubAPIAdapter(token="")

    result = adapter.check_visibility("https://github.com/acme/widgets", etag='"old"')

    assert requested_headers[0]["If-None-Match"] == '"old"'
    assert (result.is_public, result.etag, result.unchanged) == (False, '"new"', False)

    monkeypatch.setattr("requests.get", _public_repo_get([]))
    missing = adapter.check_visibility("https://github.com/acme/gone", etag='"old"')
    assert (missing.is_public, missing.etag, missing.unchanged) == (False, None, False)


def test_check_public_never_sends_a_conditional_request(monkeypatch):
    """강의실 채점이 채점 시점에 부르는 `check_public` 은 저장할 ETag 가 없다 — 조건
    없이 가고 bool 만 돌려준다(304 가 생길 수 없다)."""

    requested_headers: list[dict] = []
    monkeypatch.setattr(
        "requests.get", _etag_aware_repo_get(requested_headers, etag='"abc123"', private=False)
    )

    assert GitHubAPIAdapter(token="").check_public("https://github.com/acme/widgets") is True
    assert "If-None-Match" not in requested_headers[0]
