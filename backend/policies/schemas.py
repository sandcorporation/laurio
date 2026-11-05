"""정책 API 스키마 (#76).

`PolicyChangeOut.before`/`after`는 `dict[str, int]`다 — 그 PATCH가 실제로 바꾼
필드만 담으므로 키 집합이 요청마다 다르다. 고정된 스키마로 펼치면(개별 필드로
나열하면) 다음 티켓(#78·#79)이 `PlatformPolicy`에 필드를 더할 때마다 이 스키마도
같이 늘려야 한다 — dict로 두면 그 결합이 없다.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field


class PolicyOut(Schema):
    platform_fee_bps: int
    withholding_tax_bps: int
    withholding_necessary_expense_bps: int
    withholding_minor_income_exempt_won: int
    # #190 — 제출 자산 개수 상한.
    max_source_assets: int
    max_demo_video_assets: int
    max_demo_url_assets: int
    max_repository_assets: int
    max_scoring_input_assets: int
    # #234 — Contest 하나에 붙일 수 있는 ContestImage 개수 상한.
    max_contest_images: int
    # #263(ADR-0035) — 자리만 만든다. #261·#262·#264가 각자 읽어 쓴다.
    max_source_asset_bytes: int
    max_demo_video_asset_bytes: int
    max_screenshot_asset_bytes: int
    max_build_asset_bytes: int
    demo_video_retention_grace_days: int
    max_screenshot_assets: int
    # 낙관적 동시성 제어에 쓰는 값 — PATCH의 `expected_version`에 그대로
    # 되돌려 보내야 한다.
    version: int
    updated_at: datetime


class PolicyUpdateIn(Schema):
    # 전부 선택값이다 — 부분 변경(예: 수수료율만)을 허용한다. None인 필드는
    # 건드리지 않는다.
    platform_fee_bps: int | None = Field(default=None, ge=0)
    withholding_tax_bps: int | None = Field(default=None, ge=0)
    withholding_necessary_expense_bps: int | None = Field(default=None, ge=0)
    withholding_minor_income_exempt_won: int | None = Field(default=None, ge=0)
    # #190 — 자산 상한은 1 미만이면 제출 자체가 불가능해진다(소스가 필수다).
    max_source_assets: int | None = Field(default=None, ge=1)
    max_demo_video_assets: int | None = Field(default=None, ge=1)
    max_demo_url_assets: int | None = Field(default=None, ge=1)
    max_repository_assets: int | None = Field(default=None, ge=1)
    max_scoring_input_assets: int | None = Field(default=None, ge=1)
    # #234
    max_contest_images: int | None = Field(default=None, ge=1)
    # #263(ADR-0035) — 자리만 만든다. 바이트 상한은 0 미만이 말이 안 되므로
    # ge=1, 유예일수는 0(즉시 파기)이 유효한 값이라 ge=0이다.
    max_source_asset_bytes: int | None = Field(default=None, ge=1)
    max_demo_video_asset_bytes: int | None = Field(default=None, ge=1)
    max_screenshot_asset_bytes: int | None = Field(default=None, ge=1)
    max_build_asset_bytes: int | None = Field(default=None, ge=1)
    demo_video_retention_grace_days: int | None = Field(default=None, ge=0)
    max_screenshot_assets: int | None = Field(default=None, ge=1)
    # 돈을 움직이는 판단에 근거가 없으면 감사 기록으로서 값이 없다
    # (AppealRuling.note와 같은 규율).
    reason: str
    # GET에서 읽은 PolicyOut.version을 그대로 되돌려 보낸다. 다른 변경이 먼저
    # 반영되었으면 409(PolicyConflictError)다.
    expected_version: int


class PolicyChangeOut(Schema):
    id: int
    operator_username: str
    reason: str
    before: dict[str, int]
    after: dict[str, int]
    changed_at: datetime


class ErrorOut(Schema):
    detail: str
    # 화면이 문구가 아니라 안정적인 식별자로 분기할 수 있게 한다
    # (accounts.operator_api.ErrorOut과 같은 관용구, #47).
    code: str = "error"


# --- 운영 설정(#922, ADR-0075) -------------------------------------------------
# 비밀 값은 어느 응답 스키마에도 자리가 없다 — `configured`·`last4`·출처·변경 시각·변경자만.


class RuntimeSettingOut(Schema):
    key: str
    label: str
    kind: str
    source: str
    configured: bool
    # 비밀이 아닌 설정의 지금 값. 비밀이면 언제나 null 이다.
    value: str | None
    # 출처가 없을 때 어댑터가 쓰는 기본값(비밀은 null).
    default: str | None
    # 비밀의 끝 4자리(짧은 키면 빈 문자열). 비밀이 아니면 null.
    last4: str | None
    updated_at: datetime | None
    updated_by: str | None


class RuntimeSettingsOut(Schema):
    settings: list[RuntimeSettingOut]


class RuntimeSettingChangeOut(Schema):
    id: int
    key: str
    label: str
    action: str
    before: str
    after: str
    operator_username: str
    changed_at: datetime


# 입력은 제약 없는 문자열로 받는다 — 검증 실패 응답(422)이 입력 원문을 되돌려 싣지 않도록
# 길이·모양 검사는 서비스(`policies.runtime_settings`)가 원문 없는 문구로 한다.
class RuntimeSettingValueIn(Schema):
    value: str = ""


class RuntimeSettingProbeIn(Schema):
    value: str = ""


class RuntimeSettingSaveOut(Schema):
    changed: bool
    setting: RuntimeSettingOut


class RuntimeSettingProbeOut(Schema):
    result: str
