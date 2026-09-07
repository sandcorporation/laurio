"""GitHub 저장소 어댑터 (#193, ADR-0007, ADR-0027).

PG·스토리지·LLM과 같은 원칙(ADR-0007): 실제 GitHub 연동을 인터페이스 뒤에 두고
환경별로 갈아끼운다. dev/CI는 `GITHUB_ADAPTER_MODE=fake`(기본값)로
`FakeGitHubAdapter`에 바인딩되어 네트워크 없이 결정적으로 동작한다.

어댑터가 하는 일은 둘뿐이다(ADR-0027):

1. `check_public(url)` — 저장소가 공개인지 판정한다. 마감 전 스캔
   (`repositories.services.REPOSITORY_VISIBILITY_SCAN`)이 이것을 반복해서
   부른다.
2. `clone(url)` — 기본 브랜치를 얕게 clone한 결과(zip 바이트 + 커밋 SHA)를
   돌려준다. 채점(`scoring.services`)이 성공한 회차에만 부른다 — 공개가
   확인된 저장소만 대상이고, clone 실패·비공개는 그 항목만 빼고 채점을
   진행한다(permanent로 표시하지 않는다).

**read-only 토큰을 받지 않는다.** 참가자의 GitHub 자격증명을 플랫폼이 보관하게
되는 것은 이 저장소가 지금 보관하는 어떤 것보다 새면 파급이 크다(ADR-0027).
`GITHUB_API_TOKEN`(선택)은 platform 자신의 자격증명이지 참가자의 것이 아니다 —
없어도 공개 저장소 조회·다운로드는 그대로 동작하고, 시간당 요청 한도만 낮아진다.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import requests
from django.conf import settings

from core.adapters import resolve_adapter

logger = logging.getLogger(__name__)


class GitHubAdapterError(Exception):
    """공개 여부 판정·clone이 실패했다 — 네트워크 오류·404·비공개·rate limit 등.

    호출자는 항상 이 실패를 "그 자산 하나만 빼고 진행"으로 다룬다(ADR-0027) —
    scoring.adapters.LLMAdapterPermanentError 같은 영구 실패 구분이 여기는 없다.
    저장소는 소스 제출을 대체하지 않으므로, 이 실패가 Submission 전체를
    막을 이유가 없다.
    """


class GitHubRepositoryNotFoundError(GitHubAdapterError):
    """GitHub이 404를 줬다 — 저장소가 없거나 비공개다(GitHub은 권한 없는 조회에도
    404를 준다).

    `check_public`이 이 예외만 "확정적으로 공개가 아니다"(False)로 다룬다(#193
    코드리뷰 지적) — 네트워크 순단·5xx·rate limit(403/429) 같은 다른 실패는
    "아직 확인 못 했다"이지 "비공개로 확인됐다"가 아니다. 그 둘을 뭉쳐 전부
    False로 쓰면, GitHub이 잠깐 흔들린 순간에 공개 저장소가 영구히(다음 스캔이
    다시 볼 때까지, 그리고 그 사이 채점이 먼저 지나가면 영영) 비공개로 오분류될
    수 있다. `submissions.models.SubmissionAsset.is_public`의 계약도 "null =
    아직 확인 안 함"이지 "확인했는데 실패함"이 아니다.
    """


@dataclass(frozen=True)
class ClonedRepository:
    """`clone()`의 결과 — 기본 브랜치 최신 커밋의 선별 가능한 파일들을 담은 zip과
    그 커밋의 SHA.

    `zip_bytes`는 `scoring.source_selection.select_source_files`가 업로드된
    소스 zip과 똑같이 다룬다 — 저장소도 소스와 같은 선별·예산 규율을 받는다는
    ADR-0027의 결정을 어댑터 경계에서부터 지킨다.
    """

    commit_sha: str
    zip_bytes: bytes


@runtime_checkable
class GitHubAdapter(Protocol):
    def check_public(self, url: str) -> bool: ...

    def clone(self, url: str) -> ClonedRepository: ...


# `submissions.models.GITHUB_REPO_URL_PATTERN`이 제출 시점에 이미 이 모양만
# 받아들인다 — 여기서는 그 전제 위에서 owner/repo만 뽑는다. 그래도 방어적으로
# 다시 검증한다: 이 값은 참가자가 쓴 URL이고, 이 함수를 부르는 시점(스캔·채점)은
# 제출 검증과 시간·경로가 다르다.
_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9._-]{1,100})/(?P<repo>[A-Za-z0-9._-]{1,100})/?$"
)


def _parse_github_url(url: str) -> tuple[str, str]:
    match = _GITHUB_URL_RE.match(url)
    if match is None:
        raise GitHubAdapterError(f"github.com 저장소 URL 형식이 아니다: {url!r}")
    return match.group("owner"), match.group("repo")


class FakeGitHubAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작한다.

    시나리오는 owner·repo 이름에 담는다(대소문자 무시) — 실제 GitHub API 응답을
    흉내내는 대신, 참가자가 낼 수 있는 값 그 자체로 시나리오를 고른다:

    - owner나 repo에 "private"이 들어가면 비공개다(`check_public` → False).
    - owner나 repo에 "checkerror"가 들어가면 `check_public()`이 (404가 아닌)
      `GitHubAdapterError`를 던진다 — 네트워크 순단·5xx·rate limit처럼 "아직
      확인 못 했다"와 "비공개로 확인됐다"가 달라야 하는 실패를 흉내낸다(#193
      코드리뷰 지적).
    - owner나 repo에 "cloneerror"가 들어가면 `clone()`이
      `GitHubAdapterError`를 던진다(네트워크 순단·rate limit 등을 흉내낸다).
    - 그 밖에는 공개이고, `clone()`은
      `settings.GITHUB_FAKE_REPO_FILES`에서 그 URL에 등록된 파일들(없으면
      기본 파일 하나)을 담은 zip과, URL에서 결정적으로 유도한 40자리 hex
      커밋 SHA를 돌려준다.
    """

    def check_public(self, url: str) -> bool:
        owner, repo = _parse_github_url(url)
        if "checkerror" in owner.lower() or "checkerror" in repo.lower():
            raise GitHubAdapterError(
                f"fake GitHub 어댑터가 공개 여부 확인에 실패했다(url={url}, 설정으로 "
                "강제된 실패 시나리오 — 404가 아니다)."
            )
        return "private" not in owner.lower() and "private" not in repo.lower()

    def clone(self, url: str) -> ClonedRepository:
        owner, repo = _parse_github_url(url)
        if "cloneerror" in owner.lower() or "cloneerror" in repo.lower():
            raise GitHubAdapterError(
                f"fake GitHub 어댑터가 clone에 실패했다(url={url}, 설정으로 강제된 "
                "실패 시나리오)."
            )

        files = getattr(settings, "GITHUB_FAKE_REPO_FILES", {}).get(url) or {
            "app.py": f"# fake clone of {url}\n"
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in files.items():
                zf.writestr(path, content)

        import hashlib

        commit_sha = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return ClonedRepository(commit_sha=commit_sha, zip_bytes=buf.getvalue())


_GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT_SECONDS = 15
# codeload 응답을 무한정 메모리에 올리지 않는다 — 300KB 채점 예산에 비해 넉넉한
# 상한이지만(select_source_files가 어차피 그 예산까지만 쓴다), 저장소 하나가
# 통째로 수백 MB일 수 있으므로 다운로드 자체에 상한을 둔다.
_MAX_CLONE_DOWNLOAD_BYTES = 20_000_000


class GitHubAPIAdapter:
    """GitHub REST API로 실제 공개 여부를 판정하고, codeload로 zip을 내려받는
    실물 어댑터 (#193, ADR-0007, ADR-0027).

    `git` CLI를 쓰지 않는다 — 컨테이너 이미지에 git 바이너리를 보장하지 않아도
    되고, 얕은 clone이 만드는 임시 디렉터리·프로세스 관리가 필요 없다. GitHub의
    zipball 다운로드(`codeload.github.com`)는 공개 저장소라면 인증 없이도
    동작한다.
    """

    def __init__(self, *, token: str | None = None, timeout: float = _REQUEST_TIMEOUT_SECONDS) -> None:
        self._token = token if token is not None else (getattr(settings, "GITHUB_API_TOKEN", "") or "")
        self._timeout = timeout

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _repo_info(self, owner: str, repo: str) -> dict:
        try:
            response = requests.get(
                f"{_GITHUB_API_BASE}/repos/{owner}/{repo}",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise GitHubAdapterError(
                f"GitHub 저장소 조회가 네트워크 오류로 실패했다({type(exc).__name__}, "
                f"owner={owner}, repo={repo})."
            ) from None

        if response.status_code == 404:
            # 존재하지 않거나 비공개(GitHub은 권한 없는 조회에 404를 준다) — 이건
            # 실패가 아니라 확정적 사실이다. `GitHubRepositoryNotFoundError`로
            # 구분해 `check_public`이 다른 실패(네트워크·5xx·rate limit)와
            # 다르게 다룰 수 있게 한다(#193 코드리뷰 지적).
            raise GitHubRepositoryNotFoundError(
                f"저장소를 찾을 수 없다(owner={owner}, repo={repo})."
            )
        if response.status_code != 200:
            raise GitHubAdapterError(
                f"GitHub 저장소 조회가 실패했다(status={response.status_code}, "
                f"owner={owner}, repo={repo})."
            )
        try:
            return response.json()
        except ValueError:
            raise GitHubAdapterError(
                f"GitHub 저장소 조회 응답이 JSON이 아니다(owner={owner}, repo={repo})."
            ) from None

    def check_public(self, url: str) -> bool:
        owner, repo = _parse_github_url(url)
        try:
            info = self._repo_info(owner, repo)
        except GitHubRepositoryNotFoundError:
            # 없거나 비공개 — 확정적으로 "공개가 아니다"다. 스캔이 이 값을
            # 그대로 SubmissionAsset.is_public에 쓴다.
            return False
        # 그 밖의 GitHubAdapterError(네트워크 순단·5xx·rate limit·JSON 파싱
        # 실패)는 여기서 삼키지 않고 그대로 올려 보낸다(#193 코드리뷰 지적) —
        # `repositories.services._check_repository_visibility`를 부르는
        # `core.scans.run_scan`이 이 행만 `failed`에 남기고 `is_public`을
        # 건드리지 않는다. 다음 스캔이 다시 본다(ADR-0003) — 이 실패를 False로
        # 오분류하면 공개 저장소가 순단 한 번에 영구 비공개로 잘못 확정될 수
        # 있다.
        return not bool(info.get("private", True))

    def clone(self, url: str) -> ClonedRepository:
        owner, repo = _parse_github_url(url)
        info = self._repo_info(owner, repo)
        default_branch = info.get("default_branch")
        if not default_branch:
            raise GitHubAdapterError(f"기본 브랜치를 확인할 수 없다(owner={owner}, repo={repo}).")

        try:
            branch_response = requests.get(
                f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{default_branch}",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise GitHubAdapterError(
                f"GitHub 브랜치 조회가 네트워크 오류로 실패했다({type(exc).__name__}, "
                f"owner={owner}, repo={repo})."
            ) from None
        if branch_response.status_code != 200:
            raise GitHubAdapterError(
                f"GitHub 브랜치 조회가 실패했다(status={branch_response.status_code}, "
                f"owner={owner}, repo={repo})."
            )
        try:
            commit_sha = branch_response.json()["commit"]["sha"]
        except (ValueError, KeyError, TypeError):
            raise GitHubAdapterError(
                f"GitHub 브랜치 응답에서 커밋 SHA를 읽을 수 없다(owner={owner}, repo={repo})."
            ) from None

        try:
            zip_response = requests.get(
                f"https://codeload.github.com/{owner}/{repo}/zip/{commit_sha}",
                timeout=self._timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise GitHubAdapterError(
                f"GitHub zip 다운로드가 네트워크 오류로 실패했다({type(exc).__name__}, "
                f"owner={owner}, repo={repo})."
            ) from None
        if zip_response.status_code != 200:
            raise GitHubAdapterError(
                f"GitHub zip 다운로드가 실패했다(status={zip_response.status_code}, "
                f"owner={owner}, repo={repo})."
            )

        chunks: list[bytes] = []
        total = 0
        for chunk in zip_response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > _MAX_CLONE_DOWNLOAD_BYTES:
                raise GitHubAdapterError(
                    f"저장소 zip이 다운로드 상한({_MAX_CLONE_DOWNLOAD_BYTES}바이트)을 "
                    f"넘었다(owner={owner}, repo={repo})."
                )
            chunks.append(chunk)

        return ClonedRepository(commit_sha=commit_sha, zip_bytes=b"".join(chunks))


def get_github_adapter() -> GitHubAdapter:
    return resolve_adapter(
        mode=settings.GITHUB_ADAPTER_MODE,
        fake_factory=FakeGitHubAdapter,
        not_implemented_hint=(
            "GITHUB_ADAPTER_MODE가 가리키는 dotted path를 import할 수 없다 — 실물 "
            "어댑터는 repositories.adapters.GitHubAPIAdapter다(#193). GitHubAdapter "
            "계약만 만족시키면 다른 dotted path도 쓸 수 있다(ADR-0007)."
        ),
    )
