"""브랜치·커밋으로 낸 저장소 자산의 **고정 커밋** (#777, ADR-0065).

제출 때는 GitHub 을 부르지 않는다(ADR-0027) — 그래서 브랜치 URL 은 「어느 커밋인가」를
모른 채 저장되고, **처음 성공한 확인**(공모전은 `repository-visibility` 스캔, 강의실은 첫
채점)이 그 브랜치 HEAD 의 SHA 를 `SubmissionAsset.repository_commit_sha` 에 박는다. 그 뒤
모든 채점·재채점은 박힌 SHA 만 본다 — 참가자가 push 해도 바뀌지 않는다. 짧은 커밋 SHA 도
같은 길로 40자로 확정된다. 저장소 URL(ref 없음) 제출은 고정하지 않는다 — 스캔 시점 기본
브랜치 최신을 보는 지금 규칙 그대로다.

**박는 것은 조건부 UPDATE 다** — 스캔과 채점이 겹쳐 돌아 둘 다 「아직 안 박혔다」를 보고
각자 ref 를 풀면, 먼저 쓴 쪽이 이기고 늦은 쪽은 DB 의 값을 다시 읽어 그것을 쓴다. 두 값이
달라도(그 사이 push) 자산 하나에 SHA 는 하나만 남는다.

공모전 가족(`scoring`)과 강의실(`classroom`)이 둘 다 부르므로 공유층(`submissions`)에 있다.
"""

from __future__ import annotations

from core.repository_adapters import ClonedRepository, GitHubAdapter

from .models import SubmissionAsset

_FULL_SHA_LENGTH = 40


def is_pinned(asset: SubmissionAsset) -> bool:
    return len(asset.repository_commit_sha) == _FULL_SHA_LENGTH


def requested_ref(asset: SubmissionAsset) -> str:
    """참가자가 낸 ref — 브랜치 이름 또는 (짧을 수 있는) 커밋 SHA. 저장소 URL 제출은 빈 문자열."""

    return asset.repository_ref or asset.repository_commit_sha


def resolve_pinned_commit(asset: SubmissionAsset, adapter: GitHubAdapter) -> str | None:
    """이 자산의 채점 대상 커밋 — 저장소 URL 제출이면 None(기본 브랜치 최신), 아니면 40자 SHA.

    아직 안 박혔으면 ref 를 풀어 박는다. `GitHubRefNotFoundError`(없는 브랜치·커밋)와 그 밖의
    `GitHubAdapterError` 는 그대로 올린다 — 호출부가 그 둘을 다르게 다룬다.
    """

    wanted = requested_ref(asset)
    if not wanted:
        return None
    if is_pinned(asset):
        return asset.repository_commit_sha

    sha = adapter.resolve_ref(asset.value, wanted)
    pinned = SubmissionAsset.objects.filter(
        pk=asset.pk, repository_commit_sha=asset.repository_commit_sha
    ).update(repository_commit_sha=sha, repository_ref_found=True)
    if not pinned:
        # 다른 프로세스가 먼저 박았다 — 그 값을 쓴다.
        asset.refresh_from_db(fields=["repository_commit_sha", "repository_ref_found"])
        return asset.repository_commit_sha
    asset.repository_commit_sha = sha
    asset.repository_ref_found = True
    return sha


def clone_repository_asset(asset: SubmissionAsset, adapter: GitHubAdapter) -> ClonedRepository:
    """자산이 가리키는 커밋의 zip — 브랜치·커밋 제출은 고정 커밋을(없으면 지금 박고), 저장소
    URL 제출은 기본 브랜치 최신을 받는다."""

    return adapter.clone(asset.value, commit_sha=resolve_pinned_commit(asset, adapter))
