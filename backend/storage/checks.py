"""부팅 시점 설정 검증.

STORAGE_BACKEND·STORAGE_TARGET_RESOLVER 는 dotted path(또는 별칭) 문자열이라
오탈자가 있어도 Python 임포트가 실제로 시도되기 전까지는 아무 신호가 없다.
그대로 두면 첫 요청이 들어올 때 ImportError -> 500으로 처음 드러난다. `manage.py
check`(CI가 이미 돌린다)와 `manage.py migrate`/`runserver` 기동 시 이 검사가 먼저
돌아 배포 자체를 막는다.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error
from django.utils.module_loading import import_string

from .adapters import _BACKENDS


def check_storage_backend_is_importable(app_configs: Any, **kwargs: Any) -> list[Error]:
    errors: list[Error] = []

    backend = getattr(settings, "STORAGE_BACKEND", "") or "fake"
    backend_path = _BACKENDS.get(backend, backend)
    try:
        import_string(backend_path)
    except ImportError as exc:
        errors.append(
            Error(
                f"STORAGE_BACKEND={backend!r} 를 임포트할 수 없다 ({exc}).",
                hint='storage.adapters._BACKENDS 의 별칭("fake"/"s3")이거나 '
                "'module.ClassName' 형태의 dotted path 여야 한다.",
                id="storage.E001",
            )
        )

    resolver_path = getattr(settings, "STORAGE_TARGET_RESOLVER", "")
    if resolver_path:
        try:
            import_string(resolver_path)
        except ImportError as exc:
            errors.append(
                Error(
                    f"STORAGE_TARGET_RESOLVER={resolver_path!r} 를 임포트할 수 없다 ({exc}).",
                    hint="storage.policy.TargetStateResolver 를 구현한 클래스의 dotted path 여야 한다.",
                    id="storage.E002",
                )
            )

    return errors
