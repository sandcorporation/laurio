"""`core.repository_adapters`의 재노출 (#287).

**원본은 `core.repository_adapters`에 있다.** GitHub 저장소 어댑터는
`core.adapters`와 `submissions.models`(둘 다 공유층) 하나만 아는 완전 범용
코드였는데 `repositories`는 공모전 가족이라(`tests/test_app_boundaries.py`,
ADR-0037) 강의실이 저장소 형식 문제를 채점하려면 이 모듈이 공유층에 있어야
했다 — 그래서 옮겼다(`core.llm_scoring`을 옮긴 #274와 같은 패턴).

이 파일이 계속 남아 있는 이유는 재노출이다: `GITHUB_ADAPTER_MODE`가 가리키는
dotted path(`repositories.adapters.GitHubAPIAdapter`)와
`docker/*.env.example`을 이 이동 때문에 고치지 않기 위해서다(#274의
`scoring.adapters`와 같은 판단). 새 호출자(강의실 포함)는 여기가 아니라
`core.repository_adapters`를 직접 부른다.

`requests`도 함께 재노출한다 — 기존 테스트(`tests/test_github_api_adapter.py`)가
`monkeypatch.setattr("requests.get", ...)`로 전역 `requests` 모듈을 직접
패치하므로 실제로는 필요 없지만, `scoring.adapters`와 같은 재노출 계약을
맞춰 둔다.
"""

from __future__ import annotations

import requests

from core.repository_adapters import (
    ClonedRepository,
    FakeGitHubAdapter,
    GitHubAdapter,
    GitHubAdapterError,
    GitHubAPIAdapter,
    GitHubRepositoryNotFoundError,
    get_github_adapter,
)

__all__ = [
    "requests",
    "ClonedRepository",
    "FakeGitHubAdapter",
    "GitHubAdapter",
    "GitHubAdapterError",
    "GitHubAPIAdapter",
    "GitHubRepositoryNotFoundError",
    "get_github_adapter",
]
