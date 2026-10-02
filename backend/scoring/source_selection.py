"""`core.source_selection`의 재노출 (#287).

**원본은 `core.source_selection`에 있다.** 채점 대상 파일 선별 전략은
`core.llm_scoring.SourceFile` 하나만 아는 완전 범용 코드였는데 `scoring`은
공모전 가족이라(`tests/test_app_boundaries.py`, ADR-0037) 강의실이 소스
제출을 채점하려면 이 모듈이 공유층에 있어야 했다 — 그래서 옮겼다
(`core.llm_scoring`을 옮긴 #274와 같은 패턴).

이 파일이 계속 남아 있는 이유는 재노출이다: 기존 임포트 경로
(`scoring.source_selection.MAX_SOURCE_BYTES` 등, `tests/test_scoring.py`가
쓴다)를 이 이동 때문에 고치지 않기 위해서다. 새 호출자(강의실 포함)는 여기가
아니라 `core.source_selection`을 직접 부른다.
"""

from __future__ import annotations

from core.source_selection import (
    EXCLUDED_DIR_FRAGMENTS,
    EXCLUDED_FILE_NAMES,
    EXCLUDED_SUFFIXES,
    MAX_SOURCE_BYTES,
    select_source_files,
)

__all__ = [
    "EXCLUDED_DIR_FRAGMENTS",
    "EXCLUDED_FILE_NAMES",
    "EXCLUDED_SUFFIXES",
    "MAX_SOURCE_BYTES",
    "select_source_files",
]
