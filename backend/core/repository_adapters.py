"""GitHub 저장소 어댑터 (#193, #287, ADR-0007, ADR-0027).

**공유층(`core`)에 산다(#287).** 원래 `repositories.adapters`였다 — `repositories`는
공모전 가족이라(`tests/test_app_boundaries.py`), 강의실이 저장소 형식 문제를
채점하려면 이 모듈을 부를 수 있어야 했고 그러려면 경계 규칙 A(강의실 ↮ 공모전,
예외 없음)를 넘지 않는 자리에 있어야 했다. 이 모듈은 처음부터 `core.adapters`와
`submissions.models.GITHUB_REPO_URL_PATTERN`(둘 다 공유층) 하나만 아는 완전
범용 코드였다 — `core.llm_scoring`(#274)이 그랬던 것과 같은 이동이다.

**`repositories.adapters`는 그대로 남아 이 모듈을 재노출한다.** `GITHUB_ADAPTER_MODE`가
가리키는 dotted path(`repositories.adapters.GitHubAPIAdapter`)와
`docker/*.env.example`은 이 티켓에서 손대지 않는다 — #274가 정확히 같은 이유로
`scoring.adapters`에 shim을 남긴 것과 같은 패턴이다. 새 호출자(강의실 포함)는 이
모듈(`core.repository_adapters`)을 직접 부른다.

**공모전 전용은 그대로 `repositories` 앱에 남는다** — 저장소 스냅샷 모델
(`repositories.models`), 도달가능성 재확인 스캔(`repositories.services`,
ADR-0030)은 이 이동의 대상이 아니다. 그건 공모전의 정책이지 GitHub과 말하는
도구가 아니다.

PG·스토리지·LLM과 같은 원칙(ADR-0007): 실제 GitHub 연동을 인터페이스 뒤에 두고
환경별로 갈아끼운다. dev/CI는 `GITHUB_ADAPTER_MODE=fake`(기본값)로
`FakeGitHubAdapter`에 바인딩되어 네트워크 없이 결정적으로 동작한다.

어댑터가 하는 일은 둘뿐이다(ADR-0027):

1. `check_public(url)` — 저장소가 공개인지 판정한다. 마감 전 스캔
   (`repositories.services.REPOSITORY_VISIBILITY_SCAN`)이 이것을 반복해서
   부른다.
2. `clone(url)` — 기본 브랜치를 얕게 clone한 결과(zip 바이트 + 커밋 SHA)를
   돌려준다. 채점(`scoring.services`, `classroom.scoring`)이 성공한 회차에만
   부른다 — 공개가 확인된 저장소만 대상이고, clone 실패·비공개는 그 항목만
   빼고 채점을 진행한다(permanent로 표시하지 않는다).

**read-only 토큰을 받지 않는다.** 참가자의 GitHub 자격증명을 플랫폼이 보관하게
되는 것은 이 저장소가 지금 보관하는 어떤 것보다 새면 파급이 크다(ADR-0027).
`GITHUB_API_TOKEN`(선택)은 platform 자신의 자격증명이지 참가자의 것이 아니다 —
없어도 공개 저장소 조회·다운로드는 그대로 동작하고, 시간당 요청 한도만 낮아진다.
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import quote

import requests
from django.conf import settings

from core.adapters import resolve_adapter
from submissions.models import GITHUB_REPO_URL_PATTERN

logger = logging.getLogger(__name__)


class GitHubAdapterError(Exception):
    """공개 여부 판정·clone이 실패했다 — 네트워크 오류·404·비공개·rate limit 등.

    호출자는 항상 이 실패를 "그 자산 하나만 빼고 진행"으로 다룬다(ADR-0027) —
    core.llm_scoring.LLMAdapterPermanentError 같은 영구 실패 구분이 여기는
    없다. 저장소는 소스 제출을 대체하지 않으므로, 이 실패가 Submission 전체를
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


@dataclass(frozen=True)
class RepositoryVisibility:
    """`check_visibility()` 의 결과 (#490).

    `unchanged` 가 참이면 GitHub 이 304 를 줬다 — 저장소의 표현이 지난 확인 때와 같으니
    호출자는 지난 `is_public` 을 그대로 쓴다(`is_public` 은 None). `etag` 는 다음 확인에
    `If-None-Match` 로 보낼 값이고, 404(없거나 비공개)에는 없다.
    """

    is_public: bool | None
    etag: str | None

    @property
    def unchanged(self) -> bool:
        return self.is_public is None


@runtime_checkable
class GitHubAdapter(Protocol):
    def check_public(self, url: str) -> bool: ...

    def check_visibility(self, url: str, *, etag: str | None = None) -> RepositoryVisibility: ...

    def clone(self, url: str) -> ClonedRepository: ...


def _parse_github_url(url: str) -> tuple[str, str]:
    """`submissions.models.GITHUB_REPO_URL_PATTERN`이 제출 시점에 이미 이 모양만
    받아들인다 — "GitHub 저장소 URL은 이렇게 생겼다"의 정의를 여기서 다시
    타이핑하지 않고 그 패턴을 그대로 재사용한다(#193 코드리뷰 지적). 두 벌로
    적으면 형식이 넓어질 때(예: 더 긴 저장소 이름) 한쪽만 고쳐져 제출 시점에
    받아들이는 URL과 clone이 파싱하는 URL이 갈릴 수 있다.

    그래도 여기서 다시 검증한다 — 이 값은 참가자가 쓴 URL이고, 이 함수를 부르는
    시점(스캔·채점)은 제출 검증과 시간·경로가 다르다. `GITHUB_REPO_URL_PATTERN`은
    이름 있는 그룹이 없으므로, 형식만 확인한 뒤 이미 검증된 접두사를 잘라내
    owner/repo를 나눈다.
    """

    if not GITHUB_REPO_URL_PATTERN.match(url):
        raise GitHubAdapterError(f"github.com 저장소 URL 형식이 아니다: {url!r}")
    owner, repo = url[len("https://github.com/") :].rstrip("/").split("/", 1)
    # `git clone`에 쓰는 모양(`.../repo.git`)을 그대로 내는 참여자가 많다 — REST
    # API는 `/repos/owner/repo.git`에 404를 주므로 떼지 않으면 공개 저장소가
    # 비공개로 확정된다(#537). GitHub은 `.git`으로 끝나는 저장소 이름을 허용하지
    # 않아 떼어도 다른 저장소를 가리키지 않는다.
    repo = repo.removesuffix(".git")
    if not repo:
        raise GitHubAdapterError(f"github.com 저장소 URL 형식이 아니다: {url!r}")
    return owner, repo


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

    def check_visibility(self, url: str, *, etag: str | None = None) -> RepositoryVisibility:
        # 흉내 GitHub 에는 ETag 가 없다 — 언제나 조건 없는 조회처럼 답한다.
        return RepositoryVisibility(is_public=self.check_public(url), etag=None)

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

    def _request(
        self,
        url: str,
        *,
        what: str,
        owner: str,
        repo: str,
        stream: bool = False,
        etag: str | None = None,
    ) -> requests.Response:
        """GitHub 호출 셋(저장소 조회·브랜치 조회·zip 다운로드)이 공유하는 네트워크
        오류 처리 — 상태 코드별 처리는 호출부마다 다르므로 응답 그대로 돌려준다
        (#193 코드리뷰 지적: 세 호출이 같은 `try/except requests.RequestException`을
        메시지 문자열만 바꿔 반복하고 있었다)."""

        headers = self._headers()
        if etag:
            # 조건부 요청(#490) — 표현이 그대로면 GitHub 이 본문 없는 304 를 주고, 인증한
            # 조건부 요청의 304 는 시간당 한도에 세지 않는다.
            headers["If-None-Match"] = etag
        try:
            return requests.get(url, headers=headers, timeout=self._timeout, stream=stream)
        except requests.RequestException as exc:
            raise GitHubAdapterError(
                f"{what}이(가) 네트워크 오류로 실패했다({type(exc).__name__}, "
                f"owner={owner}, repo={repo})."
            ) from None

    def _repo_info(self, owner: str, repo: str) -> dict:
        info, _etag = self._repo_info_conditional(owner, repo, etag=None)
        if info is None:  # etag 를 안 보냈으니 304 는 올 수 없다
            raise GitHubAdapterError(f"GitHub 저장소 조회가 본문 없이 끝났다(owner={owner}, repo={repo}).")
        return info

    def _repo_info_conditional(
        self, owner: str, repo: str, *, etag: str | None
    ) -> tuple[dict | None, str | None]:
        """저장소 조회 — `(본문, ETag)`. `etag` 를 보냈고 304 를 받으면 본문이 None 이다."""

        response = self._request(
            f"{_GITHUB_API_BASE}/repos/{owner}/{repo}",
            what="GitHub 저장소 조회",
            owner=owner,
            repo=repo,
            etag=etag,
        )

        if etag and response.status_code == 304:
            return None, etag
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
            return response.json(), response.headers.get("ETag") or None
        except ValueError:
            raise GitHubAdapterError(
                f"GitHub 저장소 조회 응답이 JSON이 아니다(owner={owner}, repo={repo})."
            ) from None

    def check_public(self, url: str) -> bool:
        result = self.check_visibility(url)
        if result.is_public is None:  # etag 없이는 304 가 없다
            raise GitHubAdapterError(f"GitHub 저장소 조회가 본문 없이 끝났다(url={url}).")
        return result.is_public

    def check_visibility(self, url: str, *, etag: str | None = None) -> RepositoryVisibility:
        owner, repo = _parse_github_url(url)
        try:
            info, new_etag = self._repo_info_conditional(owner, repo, etag=etag)
        except GitHubRepositoryNotFoundError:
            # 없거나 비공개 — 확정적으로 "공개가 아니다"다. 스캔이 이 값을
            # 그대로 SubmissionAsset.is_public에 쓴다. 404 에는 ETag 가 없다.
            return RepositoryVisibility(is_public=False, etag=None)
        if info is None:
            return RepositoryVisibility(is_public=None, etag=new_etag)
        # 그 밖의 GitHubAdapterError(네트워크 순단·5xx·rate limit·JSON 파싱
        # 실패)는 여기서 삼키지 않고 그대로 올려 보낸다(#193 코드리뷰 지적) —
        # `repositories.services._check_repository_visibility`를 부르는
        # `core.scans.run_scan`이 이 행만 `failed`에 남기고 `is_public`을
        # 건드리지 않는다. 다음 스캔이 다시 본다(ADR-0003) — 이 실패를 False로
        # 오분류하면 공개 저장소가 순단 한 번에 영구 비공개로 잘못 확정될 수
        # 있다.
        return RepositoryVisibility(is_public=not bool(info.get("private", True)), etag=new_etag)

    def clone(self, url: str) -> ClonedRepository:
        owner, repo = _parse_github_url(url)
        info = self._repo_info(owner, repo)
        default_branch = info.get("default_branch")
        if not default_branch:
            raise GitHubAdapterError(f"기본 브랜치를 확인할 수 없다(owner={owner}, repo={repo}).")

        # `default_branch`는 owner/repo와 달리 우리 정규식이 제약한 입력이 아니라
        # GitHub API 응답에서 그대로 온 값이다 — "release/2024"처럼 슬래시가
        # 유효한 브랜치 이름이 있다(#193 코드리뷰 지적). 인코딩하지 않으면 URL이
        # `.../branches/release/2024`가 되어 GitHub이 그 경로를 브랜치 이름으로
        # 풀지 않고, 매 시도가 같은 깨진 URL을 만들어 공개 저장소인데도 영원히
        # clone되지 못한다(non-200 → GitHubAdapterError → 그 자산만 조용히
        # 버려진다).
        branch_response = self._request(
            f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/branches/{quote(default_branch, safe='')}",
            what="GitHub 브랜치 조회",
            owner=owner,
            repo=repo,
        )
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

        # `with`로 감싼다 — non-200 분기에서도, 아래 반복 도중 다운로드 상한에
        # 걸려 예외를 던질 때도 스트리밍 연결이 열린 채 남으면 안 된다(#193
        # 코드리뷰 지적). GC가 나중에 거둘 때까지 소켓·커넥션 풀 슬롯이 샌다 —
        # 상한을 넘는 저장소나 codeload 딸꾹질이 반복되면 스캔이 도는 동안
        # 조금씩 마른다.
        with self._request(
            f"https://codeload.github.com/{owner}/{repo}/zip/{commit_sha}",
            what="GitHub zip 다운로드",
            owner=owner,
            repo=repo,
            stream=True,
        ) as zip_response:
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
