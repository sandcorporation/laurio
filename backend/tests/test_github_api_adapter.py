"""`repositories.adapters.GitHubAPIAdapter` 단위 테스트 (#193, ADR-0007).

`tests/test_openai_scoring_adapter.py`와 같은 예외 — 이 파일도 HTTP를 거치지
않는다. `GitHubAPIAdapter`는 Laurio 자신의 API가 아니라 GitHub 벤더 연동
URL 조립·파싱 로직이다(어느 django-ninja 라우터에도 매여 있지 않다). 네트워크도
치지 않는다 — `requests.get`을 몽키패치해 벤더 응답을 흉내낸다.
"""

from __future__ import annotations

from repositories.adapters import GitHubAPIAdapter


class _FakeResponse:
    def __init__(self, *, status_code=200, json_body=None, chunks=None):
        self.status_code = status_code
        self._json_body = json_body
        self._chunks = chunks or []

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
