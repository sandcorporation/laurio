from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema

from .models import BuildAsset

# 실제 스토어 배포는 Handover 범위 밖이다(#14 AC) — 모든 Handover 응답에 이 안내를
# 명시적으로 실어, API를 보는 쪽이 "빌드 자산을 올렸으니 배포까지 끝났다"고 오해하지
# 않게 한다.
STORE_DEPLOYMENT_OUT_OF_SCOPE_NOTE = (
    "Handover는 소스 접근 개방과 빌드 자산 인수까지다. 실제 스토어 배포는 Handover "
    "범위 밖이며 Developer가 별도로 진행해야 한다."
)


class HandoverOut(Schema):
    contest_id: int
    award_id: int
    status: str
    release_deadline_at: datetime
    released_via: str | None = None
    released_at: datetime | None = None
    note: str = STORE_DEPLOYMENT_OUT_OF_SCOPE_NOTE


class BuildAssetIn(Schema):
    kind: str
    object_key: str = Field(max_length=600)
    label: str = ""


class BuildAssetOut(Schema):
    id: int
    submission_id: int
    kind: str
    object_key: str
    label: str
    created_at: datetime


_BUILD_ASSET_KINDS = {choice for choice, _label in BuildAsset.Kind.choices}


class ErrorOut(Schema):
    detail: str
