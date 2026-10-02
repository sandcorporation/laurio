"""제출 파일을 채점용 텍스트로 바꾸는 변환 플러그인 (#496, #495).

소스 선별(`core.source_selection`)은 UTF-8로 읽을 수 없는 파일을 원래 버렸다 —
그런 형식(Packet Tracer `.pkt` 같은 압축·암호화된 바이너리)을 낸 제출은 채점이
오류 없이 끝나면서 채점자가 빈 소스를 받는다. 이 꾸러미는 그 자리에 끼우는
플러그인의 계약과 등록부다. 공모전과 강의실이 선별을 함께 쓰므로 공유층에 산다
(기능 앱에 두면 `tests/test_app_boundaries.py` 때문에 한쪽이 못 쓴다).

**계약.** 플러그인은 `format_name`(사람이 읽는 형식 이름, 「열 수 없는 ○○ 파일」
줄에 쓰인다)과 `convert(raw, *, path)`를 갖는다. `convert`는

- 내 형식이 아니면 `None`,
- 내 형식이면 텍스트 파일 목록(`ConvertedFile`),
- 내 형식으로 **확정한 뒤** 실패하면 `SourceConversionFailed`

를 낸다. 판정은 내용으로 확정한다 — `path`는 힌트일 뿐이다(단일 파일 업로드는
선별 안에서 이름이 `source`다). 그 밖의 예외는 플러그인의 버그로 보고 그
플러그인만 건너뛴다.

**목록은 설정이 고른다** — `SOURCE_CONVERTERS`(dotted path 목록). 어댑터 바인딩
(`*_ADAPTER_MODE`)과 같은 관용구이고, 쓸 수 없는 경로는 부팅 검사
(`check_source_converters`)가 거절한다 — 첫 채점에서야 죽지 않게.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.core.checks import Error
from django.utils.module_loading import import_string


@dataclass(frozen=True)
class ConvertedFile:
    """변환 결과 파일 하나 — 선별은 `<원본 경로>/<name>`으로 싣는다."""

    name: str
    content: str


class SourceConversionFailed(Exception):
    """내 형식으로 확정했지만 변환하지 못했다 — 채점자가 「설정이 없다」로
    오판하지 않도록 선별이 프롬프트에 그 사실을 한 줄 남긴다."""


@runtime_checkable
class SourceConverter(Protocol):
    format_name: str

    def convert(self, raw: bytes, *, path: str) -> list[ConvertedFile] | None: ...


@functools.lru_cache(maxsize=8)
def _load(paths: tuple[str, ...]) -> tuple[SourceConverter, ...]:
    return tuple(import_string(path)() for path in paths)


def registered_converters() -> tuple[SourceConverter, ...]:
    """설정에 적힌 순서대로 — 앞의 플러그인이 먼저 「내 형식인가」를 판정한다."""

    return _load(tuple(getattr(settings, "SOURCE_CONVERTERS", ())))


def check_source_converters(app_configs: Any, **kwargs: Any) -> list[Error]:
    """`SOURCE_CONVERTERS`의 경로마다 임포트·인스턴스화·계약을 확인한다.

    `core.adapters.check_adapter_mode`와 달리 dev에서도 본다 — 어댑터는 dev가
    fake로 돌지만, 이 목록은 dev·CI에서도 실물이 돌기 때문이다. 오타 하나가
    「그 형식은 조용히 버려진다」로 끝나면 아무도 모른다.
    """

    errors: list[Error] = []
    for path in getattr(settings, "SOURCE_CONVERTERS", ()):
        try:
            instance = import_string(path)()
        except Exception as exc:  # noqa: BLE001 — ImportError·생성자 실패 모두 같은 거절이다
            errors.append(
                Error(
                    f"SOURCE_CONVERTERS 의 {path!r} 를 불러올 수 없다 ({type(exc).__name__}: {exc}).",
                    hint="변환 플러그인 클래스의 dotted path(\"module.ClassName\")여야 한다.",
                    id="core.E004",
                )
            )
            continue
        if not isinstance(instance, SourceConverter):
            errors.append(
                Error(
                    f"SOURCE_CONVERTERS 의 {path!r} 가 변환 플러그인 계약"
                    "(format_name·convert)을 갖추지 않았다.",
                    id="core.E005",
                )
            )
    return errors
