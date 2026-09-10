"""`core.checks`의 재노출 (#287) — 원본은 `core.repository_adapters`와 함께
옮겨갔다.

부팅 가드 등록은 더 이상 여기가 하지 않는다(`core.apps.CoreConfig.ready()`가
한다) — 이 파일은 옛 경로(`repositories.checks.check_github_adapter_mode`)를
그대로 쓰는 호출부가 깨지지 않게만 한다.
"""

from __future__ import annotations

from core.checks import check_github_adapter_mode

__all__ = ["check_github_adapter_mode"]
