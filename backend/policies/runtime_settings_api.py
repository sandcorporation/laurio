"""운영 설정 운영자 API (#922, ADR-0075).

- `GET /operator/runtime-settings` — 설정마다 출처(db·env·none)·설정됨·끝 4자리·변경 시각·변경자.
  일반 등급도 본다. 비밀 값은 나가지 않는다.
- `GET /operator/runtime-settings/changes` — 변경 이력(비밀은 끝 4자리 표시만).
- `POST /operator/runtime-settings/{key}` — 저장. 비운 입력은 기존 값을 그대로 둔다. 상위 등급만.
- `POST /operator/runtime-settings/{key}/clear` — DB 값을 지운다(env 로 돌아간다). 상위 등급만.
- `POST /operator/runtime-settings/{key}/confirm` — 스위치의 「이대로 둔다」(#1221). 다음 변경까지 스위치 경보에서 뺀다.
  상위 등급만.
- `POST /operator/runtime-settings/{key}/test` — 연결 시험. 입력값이 있으면 그것으로, 없으면 지금
  쓰이는 값으로. 결과(ok·invalid_key·unavailable)만 돌려준다. 상위 등급만.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from core.agent_refusal_alert import last_account_refusal
from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from .models import RuntimeSettingChange
from .runtime_settings import (
    SPECS,
    RuntimeSettingError,
    SettingView,
    clear_setting,
    describe_settings,
    probe_setting,
    save_setting,
)
from .switch_watch import SwitchWatch, confirm_switch, watches
from .schemas import (
    AccountRefusalOut,
    ErrorOut,
    RuntimeSettingChangeOut,
    RuntimeSettingOut,
    RuntimeSettingProbeIn,
    RuntimeSettingProbeOut,
    RuntimeSettingSaveOut,
    RuntimeSettingsOut,
    RuntimeSettingValueIn,
)

runtime_settings_router = Router(tags=["operator", "runtime-settings"], auth=OperatorAuth())

_SUPERUSER = SuperuserOperatorAuth()
_HISTORY_LIMIT = 200


def _out(view: SettingView, watch: SwitchWatch | None = None) -> RuntimeSettingOut:
    return RuntimeSettingOut(
        key=view.key,
        label=view.label,
        kind=view.kind,
        source=view.source,
        configured=view.configured,
        value=view.value,
        default=view.default,
        last4=view.last4,
        updated_at=view.updated_at,
        updated_by=view.updated_by,
        choices=list(view.choices) or None,
        changed_at=watch.changed_at if watch else None,
        confirmed_at=watch.confirmed_at if watch else None,
        confirmed_by=watch.confirmed_by if watch else None,
        needs_confirm=watch.needs_confirm if watch else False,
    )


def _view_of(key: str) -> RuntimeSettingOut:
    return next(v for v in _outs() if v.key == key)


def _outs() -> list[RuntimeSettingOut]:
    switches = watches()
    return [_out(v, switches.get(v.key)) for v in describe_settings()]


def _error_status(exc: RuntimeSettingError) -> int:
    return {"unknown_setting": 404, "conflict": 409}.get(exc.code, 422)


@runtime_settings_router.get("/runtime-settings", response={200: RuntimeSettingsOut})
def list_runtime_settings(request: HttpRequest):
    refusal = last_account_refusal()
    return 200, RuntimeSettingsOut(
        settings=_outs(),
        last_account_refusal=AccountRefusalOut(**refusal) if refusal else None,
    )


@runtime_settings_router.get(
    "/runtime-settings/changes", response={200: list[RuntimeSettingChangeOut]}
)
def list_runtime_setting_changes(request: HttpRequest):
    changes = RuntimeSettingChange.objects.select_related("operator")[:_HISTORY_LIMIT]
    return 200, [
        RuntimeSettingChangeOut(
            id=c.id,
            key=c.key,
            label=SPECS[c.key].label if c.key in SPECS else c.key,
            action=c.action,
            before=c.before,
            after=c.after,
            operator_username=c.operator.username,
            changed_at=c.changed_at,
        )
        for c in changes
    ]


@runtime_settings_router.post(
    "/runtime-settings/{key}",
    response={200: RuntimeSettingSaveOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    auth=_SUPERUSER,
)
def save_runtime_setting(request: HttpRequest, key: str, payload: RuntimeSettingValueIn):
    try:
        changed = save_setting(key, payload.value, operator=request.auth)
    except RuntimeSettingError as exc:
        return _error_status(exc), ErrorOut(detail=exc.detail, code=exc.code)
    return 200, RuntimeSettingSaveOut(changed=changed, setting=_view_of(key))


@runtime_settings_router.post(
    "/runtime-settings/{key}/clear",
    response={200: RuntimeSettingSaveOut, 404: ErrorOut},
    auth=_SUPERUSER,
)
def clear_runtime_setting(request: HttpRequest, key: str):
    try:
        changed = clear_setting(key, operator=request.auth)
    except RuntimeSettingError as exc:
        return _error_status(exc), ErrorOut(detail=exc.detail, code=exc.code)
    return 200, RuntimeSettingSaveOut(changed=changed, setting=_view_of(key))


@runtime_settings_router.post(
    "/runtime-settings/{key}/confirm",
    response={200: RuntimeSettingSaveOut, 404: ErrorOut, 422: ErrorOut},
    auth=_SUPERUSER,
)
def confirm_runtime_setting(request: HttpRequest, key: str):
    try:
        changed = confirm_switch(key, operator=request.auth)
    except RuntimeSettingError as exc:
        return _error_status(exc), ErrorOut(detail=exc.detail, code=exc.code)
    return 200, RuntimeSettingSaveOut(changed=changed, setting=_view_of(key))


@runtime_settings_router.post(
    "/runtime-settings/{key}/test",
    response={200: RuntimeSettingProbeOut, 404: ErrorOut, 422: ErrorOut},
    auth=_SUPERUSER,
)
def probe_runtime_setting(request: HttpRequest, key: str, payload: RuntimeSettingProbeIn):
    try:
        result = probe_setting(key, payload.value)
    except RuntimeSettingError as exc:
        return _error_status(exc), ErrorOut(detail=exc.detail, code=exc.code)
    return 200, RuntimeSettingProbeOut(result=result)
