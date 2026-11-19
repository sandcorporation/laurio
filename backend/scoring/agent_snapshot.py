"""공모전 에이전트 채점의 박제본 받기(#1000) — `core.agent_scoring.AgentJob.load_snapshot` 으로 넘긴다.

`RepositorySnapshot`(공모전 마감 박제본)은 공모전 몫이라 공유층(`core.agent_scoring`)이 아니라 여기 있다(#1036).
"""

from __future__ import annotations

import io
import zipfile

from contests.models import ContestSubmission
from core.agent_scoring import Snapshot, SnapshotUnavailable
from core.repository_adapters import get_github_adapter
from repositories.models import RepositorySnapshot
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset
from submissions.repository_pins import clone_repository_asset


def contest_snapshot(submission: ContestSubmission) -> Snapshot:
    """공모전 제출의 박제본 — 저장소 자산의 마지막 `RepositorySnapshot` 커밋(없으면 고정 커밋), 저장소가 없으면
    zip 소스 자료. 둘 다 없으면 `SnapshotUnavailable`(받는 쪽이 보류한다)."""

    repo_assets = list(
        submission.assets.filter(kind=SubmissionAsset.Kind.REPOSITORY).order_by("order", "id")
    )
    for asset in repo_assets:
        github = get_github_adapter()
        snap = RepositorySnapshot.objects.filter(asset=asset).order_by("-cloned_at").first()
        cloned = (
            github.clone(asset.value, commit_sha=snap.commit_sha)
            if snap is not None
            else clone_repository_asset(asset, github)
        )
        return Snapshot(zip_bytes=cloned.zip_bytes, commit_sha=cloned.commit_sha, asset_id=asset.id)
    storage = get_storage_adapter()
    for asset in submission.assets.filter(kind=SubmissionAsset.Kind.SOURCE).order_by("order", "id"):
        raw = storage.read_object(asset.value)
        if raw is not None and zipfile.is_zipfile(io.BytesIO(raw)):
            return Snapshot(zip_bytes=raw, commit_sha=None, asset_id=asset.id)
    raise SnapshotUnavailable("저장소 자산도 zip 소스 자료도 없다")
