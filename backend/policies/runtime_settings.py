"""운영 설정(Runtime setting) — Operator 화면에서 넣고 바꾸면 재시작 없이 반영되는 값 (#922, ADR-0075).

**읽기 우선순위.** DB(`RuntimeSetting`)에 행이 있으면 그 값, 없으면 지금까지처럼 환경변수다.
배포 직후 표가 비어 있으면 운영 동작은 한 글자도 바뀌지 않는다.

**캐시와 무효화.** 프로세스(gunicorn 워커·celery·grader·events)마다 DB 값을 메모리에 쥐고,
읽을 때마다 공용 Redis 의 버전 번호 하나만 본다. 프로세스가 쥔 버전과 같으면 메모리 값을 쓰고,
다르면 DB 에서 다시 읽는다. 저장·지우기는 트랜잭션이 커밋된 뒤(`on_commit`) 버전을 올린다.
`CACHES["default"]`(LocMem)는 워커마다 갈려 쓰지 않는다.

- Redis 를 못 읽으면 `FALLBACK_TTL_SECONDS` 동안은 쥔 값을 쓰고 그 뒤 DB 를 다시 본다 — 요청은
  깨지지 않는다. 실패한 Redis 를 그 동안 다시 두드리지도 않는다.
- Redis 가 읽혀도 `MAX_AGE_SECONDS` 가 지나면 DB 를 다시 본다 — 버전을 올리던 순간 Redis 가
  잠깐 끊겼거나 Redis 가 비워져 버전이 되돌아간 경우의 상한이다.
- DB 를 못 읽으면(표가 아직 없음·연결 실패) 쥔 값, 그것도 없으면 env 로 물러난다.

**비밀.** 비밀 값은 `core.crypto`(`VERIFICATION_ENCRYPTION_KEY`)로 암호화해 저장하고, 화면·이력·
로그에는 끝 4자리 표시만 나간다. 이 모듈은 값을 로그에 쓰지 않는다 — 키 이름만 쓴다.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db import IntegrityError, transaction

from core.adapters import is_fake_adapter_binding
from core.clock import Clock
from core.crypto import DecryptionError, decrypt, encrypt

logger = logging.getLogger(__name__)

Source = Literal["db", "env", "none"]
Kind = Literal["secret", "text", "float"]
ProbeResult = Literal["ok", "invalid_key", "unavailable"]

FALLBACK_TTL_SECONDS = 30.0
MAX_AGE_SECONDS = 60.0
MASK = "••••"


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    kind: Kind
    #: 출처가 없을 때 어댑터가 쓰는 값(화면 표시용). 어댑터 상수와 같은지는 시험이 본다.
    default: str | None = None
    max_length: int = 100
    min_value: float | None = None
    max_value: float | None = None


#: 화면으로 옮긴 설정. 무엇을 넣고 무엇을 뺐는지와 그 이유는 ADR-0075 에 있다.
SPECS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        SettingSpec("OPEN_AI_API_KEY", "OpenAI API 키", "secret", max_length=500),
        SettingSpec("LLM_OPENAI_MODEL", "OpenAI 모델", "text", default="gpt-4o-mini", max_length=100),
        SettingSpec(
            "LLM_OPENAI_TEMPERATURE",
            "채점 temperature",
            "float",
            default="0",
            min_value=0.0,
            max_value=2.0,
        ),
        SettingSpec(
            "LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE",
            "요구사항 대화 temperature",
            "float",
            default="0.7",
            min_value=0.0,
            max_value=2.0,
        ),
    )
}


@dataclass(frozen=True)
class StoredSetting:
    value: str
    last4: str
    updated_at: datetime
    updated_by: str


# --- 버전 저장소 --------------------------------------------------------------


class VersionStore(Protocol):
    def current(self) -> int: ...

    def bump(self) -> None: ...


class RedisVersionStore:
    """공용 Redis 의 정수 하나. 연결·응답 상한을 짧게 둬 Redis 장애가 요청을 붙잡지 않는다."""

    KEY = "codemit:runtime-settings:version"

    def __init__(self, url: str, *, timeout: float = 0.3) -> None:
        self._url = url
        self._timeout = timeout
        self._client: object | None = None

    def _redis(self):  # -> redis.Redis — 타입 스텁 없이 쓰는 외부 클라이언트
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(
                self._url, socket_timeout=self._timeout, socket_connect_timeout=self._timeout
            )
        return self._client

    def current(self) -> int:
        raw = self._redis().get(self.KEY)
        return int(raw) if raw else 0

    def bump(self) -> None:
        self._redis().incr(self.KEY)


class MemoryVersionStore:
    """프로세스 안 흉내 — pytest 에는 Redis 가 없다. 같은 인스턴스를 나눠 쥔 읽기들이 「다른 프로세스」다."""

    def __init__(self) -> None:
        self._value = 0
        self.fail = False

    def current(self) -> int:
        if self.fail:
            raise ConnectionError("version store unavailable")
        return self._value

    def bump(self) -> None:
        if self.fail:
            raise ConnectionError("version store unavailable")
        self._value += 1


# --- 읽기 ---------------------------------------------------------------------


def _load_from_db() -> dict[str, StoredSetting]:
    from .models import RuntimeSetting

    loaded: dict[str, StoredSetting] = {}
    with transaction.atomic():
        rows = list(RuntimeSetting.objects.select_related("updated_by"))
    for row in rows:
        spec = SPECS.get(row.key)
        if spec is None:
            continue
        if spec.kind == "secret":
            try:
                value = decrypt(row.stored)
            except DecryptionError:
                logger.error("runtime setting %s: stored value cannot be decrypted", row.key)
                continue
        else:
            value = row.stored
        loaded[row.key] = StoredSetting(
            value=value,
            last4=row.last4,
            updated_at=row.updated_at,
            updated_by=row.updated_by.username,
        )
    return loaded


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class RuntimeSettingsReader:
    """한 프로세스의 운영 설정 캐시. 모듈 기본 인스턴스 하나를 쓰고, 시험은 「다른 프로세스」로 하나 더 만든다."""

    def __init__(
        self,
        store: VersionStore,
        *,
        loader: Callable[[], dict[str, StoredSetting]] = _load_from_db,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._loader = loader
        self._clock = clock
        self._lock = threading.Lock()
        self._values: dict[str, StoredSetting] | None = None
        self._version: int | None = None
        self._loaded_at = 0.0
        self._store_failed_at: float | None = None

    def _current_version(self, now: float) -> int | None:
        if self._store_failed_at is not None and now - self._store_failed_at < FALLBACK_TTL_SECONDS:
            return None
        try:
            version = self._store.current()
        except Exception:  # noqa: BLE001 - Redis 가 무엇을 던지든 요청은 DB 로 물러난다
            logger.warning("runtime settings: version store unavailable, falling back to TTL")
            self._store_failed_at = now
            return None
        self._store_failed_at = None
        return version

    def snapshot(self) -> dict[str, StoredSetting]:
        with self._lock:
            now = self._clock()
            version = self._current_version(now)
            fresh = self._values is not None and now - self._loaded_at < (
                MAX_AGE_SECONDS if version is not None else FALLBACK_TTL_SECONDS
            )
            if fresh and version is not None and version == self._version:
                return self._values  # type: ignore[return-value]
            if fresh and version is None:
                return self._values  # type: ignore[return-value]
            if _in_event_loop():
                # 비동기 문맥에서는 ORM 을 부를 수 없다 — 쥔 값, 없으면 env 로.
                return self._values or {}
            try:
                values = self._loader()
            except Exception:  # noqa: BLE001 - 표가 아직 없거나 DB 가 끊겨도 요청은 env 로 돈다
                # info 다 — DB 가 정말 끊겼다면 요청 쪽이 먼저 오류를 낸다. 이 물러남은 설계된 길이다.
                logger.info("runtime settings: database read failed, using previous values or env")
                return self._values or {}
            self._values = values
            self._version = version
            self._loaded_at = now
            return values


_store: VersionStore | None = None
_reader: RuntimeSettingsReader | None = None
_init_lock = threading.Lock()


def version_store() -> VersionStore:
    global _store
    with _init_lock:
        if _store is None:
            if settings.RUNTIME_SETTINGS_VERSION_STORE == "memory":
                _store = MemoryVersionStore()
            else:
                _store = RedisVersionStore(settings.RUNTIME_SETTINGS_REDIS_URL)
        return _store


def _default_reader() -> RuntimeSettingsReader:
    global _reader
    store = version_store()
    with _init_lock:
        if _reader is None:
            _reader = RuntimeSettingsReader(store)
        return _reader


def reset_for_tests() -> None:
    """시험 사이에 프로세스 캐시와 흉내 버전 저장소를 비운다(DB 는 시험마다 되감긴다)."""

    global _store, _reader
    with _init_lock:
        _store = None
        _reader = None


def setting_value(key: str, *, reader: RuntimeSettingsReader | None = None) -> str | None:
    """설정 하나의 지금 값 — DB 에 있으면 DB, 없으면 환경변수, 둘 다 없으면 `None`."""

    if key not in SPECS:
        raise KeyError(key)
    stored = (reader or _default_reader()).snapshot().get(key)
    if stored is not None:
        return stored.value
    return os.environ.get(key) or None


# --- 화면에 보일 모양 ----------------------------------------------------------


def last4_of(value: str) -> str:
    """끝 4자리. 짧은 값은 절반 넘게 드러나므로 아무것도 보이지 않는다."""

    return value[-4:] if len(value) >= 12 else ""


def masked(last4: str) -> str:
    return f"{MASK}{last4}"


@dataclass(frozen=True)
class SettingView:
    key: str
    label: str
    kind: Kind
    source: Source
    configured: bool
    value: str | None
    default: str | None
    last4: str | None
    updated_at: datetime | None
    updated_by: str | None


def describe_settings() -> list[SettingView]:
    """화면용 — 언제나 DB 를 바로 읽는다(캐시를 거치지 않는다). 비밀 값은 담지 않는다."""

    stored = _load_from_db()
    views: list[SettingView] = []
    for spec in SPECS.values():
        row = stored.get(spec.key)
        env_value = os.environ.get(spec.key) or None
        if row is not None:
            source: Source = "db"
            value: str | None = row.value
            last4 = row.last4
        elif env_value is not None:
            source = "env"
            value = env_value
            last4 = last4_of(env_value)
        else:
            source = "none"
            value = None
            last4 = ""
        secret = spec.kind == "secret"
        views.append(
            SettingView(
                key=spec.key,
                label=spec.label,
                kind=spec.kind,
                source=source,
                configured=value is not None,
                value=None if secret else value,
                default=spec.default,
                last4=(last4 if value is not None else None) if secret else None,
                updated_at=row.updated_at if row else None,
                updated_by=row.updated_by if row else None,
            )
        )
    return views


# --- 쓰기 ---------------------------------------------------------------------


class RuntimeSettingError(Exception):
    """화면에 그대로 보여도 되는 문구만 담는다 — 입력값을 문구에 넣지 않는다."""

    def __init__(self, detail: str, code: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code


_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]+$")


def _normalize(spec: SettingSpec, raw: str) -> str:
    value = raw.strip()
    if len(value) > spec.max_length:
        raise RuntimeSettingError(f"{spec.max_length}자를 넘을 수 없습니다.", "too_long")
    if spec.kind == "secret":
        if any(ch.isspace() for ch in value) or not value.isascii() or not value.isprintable():
            raise RuntimeSettingError("공백이나 영문·숫자·기호 밖의 글자가 들어 있습니다.", "invalid_value")
        return value
    if spec.kind == "text":
        if not _MODEL_PATTERN.match(value):
            raise RuntimeSettingError("영문·숫자·「. _ : / -」만 쓸 수 있습니다.", "invalid_value")
        return value
    try:
        number = float(value)
    except ValueError:
        raise RuntimeSettingError("숫자가 아닙니다.", "invalid_value") from None
    if not math.isfinite(number) or (
        spec.min_value is not None and number < spec.min_value
    ) or (spec.max_value is not None and number > spec.max_value):
        raise RuntimeSettingError(
            f"{spec.min_value:g}~{spec.max_value:g} 사이여야 합니다.", "out_of_range"
        )
    return format(number, "g")


def _display(spec: SettingSpec, value: str, last4: str) -> str:
    return masked(last4) if spec.kind == "secret" else value


def _bump_after_commit() -> None:
    def bump() -> None:
        try:
            version_store().bump()
        except Exception:  # noqa: BLE001 - 버전을 못 올려도 저장은 끝났다; 읽기가 MAX_AGE 로 따라잡는다
            logger.warning("runtime settings: version bump failed, processes catch up within max age")

    transaction.on_commit(bump)


def _spec(key: str) -> SettingSpec:
    spec = SPECS.get(key)
    if spec is None:
        raise RuntimeSettingError("없는 설정입니다.", "unknown_setting")
    return spec


def save_setting(key: str, raw: str, *, operator: AbstractBaseUser) -> bool:
    """값을 저장한다. 비운 입력은 아무것도 바꾸지 않는다(`False`) — 지우기는 `clear_setting`."""

    from .models import RuntimeSetting, RuntimeSettingChange

    spec = _spec(key)
    if not raw.strip():
        return False
    value = _normalize(spec, raw)
    secret = spec.kind == "secret"
    last4 = last4_of(value) if secret else ""
    now = Clock.now()
    try:
        with transaction.atomic():
            existing = RuntimeSetting.objects.select_for_update().filter(key=key).first()
            if existing is not None:
                before = (
                    masked(existing.last4) if secret else existing.stored
                )
                if not secret and existing.stored == value:
                    return False
            else:
                before = ""
            RuntimeSetting.objects.update_or_create(
                key=key,
                defaults={
                    "stored": encrypt(value) if secret else value,
                    "last4": last4,
                    "updated_at": now,
                    "updated_by": operator,
                },
            )
            RuntimeSettingChange.objects.create(
                operator=operator,
                key=key,
                action=RuntimeSettingChange.Action.SET,
                before=before,
                after=_display(spec, value, last4),
                changed_at=now,
            )
            _bump_after_commit()
    except IntegrityError:
        raise RuntimeSettingError("동시에 저장되었습니다. 다시 시도하세요.", "conflict") from None
    logger.info("runtime setting %s saved by operator %s", key, getattr(operator, "pk", None))
    return True


def clear_setting(key: str, *, operator: AbstractBaseUser) -> bool:
    """DB 값을 지운다 — 그 뒤로는 환경변수 값을 쓴다. 지울 것이 없으면 `False`."""

    from .models import RuntimeSetting, RuntimeSettingChange

    spec = _spec(key)
    with transaction.atomic():
        existing = RuntimeSetting.objects.select_for_update().filter(key=key).first()
        if existing is None:
            return False
        before = masked(existing.last4) if spec.kind == "secret" else existing.stored
        existing.delete()
        RuntimeSettingChange.objects.create(
            operator=operator,
            key=key,
            action=RuntimeSettingChange.Action.CLEAR,
            before=before,
            after="",
            changed_at=Clock.now(),
        )
        _bump_after_commit()
    logger.info("runtime setting %s cleared by operator %s", key, getattr(operator, "pk", None))
    return True


# --- 연결 시험 -----------------------------------------------------------------


def probe_setting(key: str, raw: str | None) -> ProbeResult:
    """키로 가벼운 호출 하나를 해 본다. `raw` 가 비면 지금 쓰이는 값(DB→env)으로 한다."""

    spec = _spec(key)
    if key != "OPEN_AI_API_KEY":
        raise RuntimeSettingError("연결 시험이 없는 설정입니다.", "not_probeable")
    candidate = _normalize(spec, raw) if raw and raw.strip() else _current_for_probe(key)
    if not candidate:
        raise RuntimeSettingError("시험할 키가 없습니다.", "not_configured")
    from core.llm_scoring import fake_probe_openai_key, probe_openai_key

    probe = (
        fake_probe_openai_key
        if is_fake_adapter_binding(settings.LLM_ADAPTER_MODE)
        else probe_openai_key
    )
    result = probe(candidate)
    logger.info("runtime setting %s probe result=%s", key, result)
    return result


def _current_for_probe(key: str) -> str | None:
    stored = _load_from_db().get(key)
    if stored is not None:
        return stored.value
    return os.environ.get(key) or None
