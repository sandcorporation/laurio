"""저장소 앱이 위 층에 묻는 자리 — 위 층 앱이 `AppConfig.ready()` 에서 올린다(#1102, `core.registry` 의 모양)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.registry import Slot

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from submissions.models import SubmissionAsset

#: `scoring.participation.still_to_score` — 아직 채점할 제출의 자산만 남긴다(Score 없음, 영구 실패 아님)
STILL_TO_SCORE: Slot[Callable[["QuerySet[SubmissionAsset]"], "QuerySet[SubmissionAsset]"]] = Slot(
    "아직 채점할 자산", "scoring.apps"
)
