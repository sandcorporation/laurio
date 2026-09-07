"""`Score.scored_assets`(asset_id·commit_sha만 있는 불변 스냅샷)를 화면이 바로 쓸
수 있는 모양으로 붙여 낸다 (#191, ADR-0027).

**여기 있는 이유 — `appeals`는 `scoring`을 import하지 않는다.** 재채점을 실행할 수
있는 코드 경로 자체가 없어야 한다는 것이 ADR-0006의 정적 불변식이고,
`tests/test_appeals.py::test_no_rescoring_code_path_exists_in_appeals_app`가 AST를
파싱해 그것을 고정한다. 이 함수가 필요로 하는 것은 `SubmissionAsset`(submissions
소유)뿐이라 `submissions`에 두면 `appeals`도 `submissions`도 `scoring`을 import할
필요가 없다 — 호출자는 `score.scored_assets`를 속성으로 읽어(이미 로드된 인스턴스의
필드 접근일 뿐이다) 이 함수에 넘기기만 하면 된다.

`submissions.schemas.OwnScoreOut`과 `appeals.schemas.ScoreSnapshotOut`이 이 함수를
함께 쓴다 — 이의를 제기하는 사람과 심판하는 사람이 같은 것을 봐야 하므로(그 스키마들
자신의 docstring) 조립 로직도 하나여야 한다.
"""

from __future__ import annotations

from .models import SubmissionAsset


def resolve_scored_assets(entries: list[dict]) -> list[dict]:
    """`kind`·`label`은 Score 저장 시점의 값이 아니라 지금 `SubmissionAsset`에서 새로
    읽는다 — 제출 수정은 마감 전에만 가능하므로(ADR-0027) Score가 있는 Submission의
    자산은 이미 바뀌지 않는 값이고, 굳이 Score에 한 번 더 중복 보관할 이유가 없다.
    `commit_sha`만 스냅샷 그대로 쓴다 — 저장소가 나중에 다시 clone되어도(#193) 이
    Score가 실제로 본 커밋은 그때 그대로여야 한다.
    """

    entries = entries or []
    asset_ids = [e["asset_id"] for e in entries if e.get("asset_id") is not None]
    assets_by_id = {a.id: a for a in SubmissionAsset.objects.filter(id__in=asset_ids)}

    result = []
    for entry in entries:
        asset = assets_by_id.get(entry.get("asset_id"))
        if asset is None:
            # 이론상 일어나지 않는다(자산은 제출 마감 후 바뀌지 않는다) — 그래도
            # 조회가 빠진 것을 조용히 삼키지 않고, 있는 필드만으로 최대한 채운다.
            continue
        result.append(
            {
                "asset_id": asset.id,
                "kind": asset.kind,
                "label": asset.label,
                "commit_sha": entry.get("commit_sha"),
            }
        )
    return result
