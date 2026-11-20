"""제출이 받는 GitHub 저장소 URL 의 모양 — 제출 검증(`submissions.models`)과 다운로드(`core.repository_adapters`)가 같이 쓴다(#1086).
"""

from __future__ import annotations

import re

# `kind=repository`의 `value`가 받는 유일한 모양. 임의의 git URL을 받으면 플랫폼
# 서버가 참가자가 지정한 주소로 나가게 되어(SSRF) 내부 네트워크 탐색 경로가 생긴다
# — 저장소를 실제로 clone하는 것은 #193이지만, 그때 받아들일 수 있는 값만 지금부터
# 저장한다. GitLab·Bitbucket은 어댑터 구현을 하나 더하는 일이라 나중에 열어도 늦지
# 않다(ADR-0027).
GITHUB_REPO_URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}/?$"
)
