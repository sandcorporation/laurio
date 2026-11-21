"""문법 검사가 쓰는 tree-sitter 문법을 캐시에 받아 둔다(#409 후속, #1205).

**이 파일은 Django 도 다른 앱 코드도 가져오지 않는다.** `docker/backend.Dockerfile` 이 backend
소스 전체를 복사하기 *앞* 층에서 이 파일 하나만 복사해 직접 돌리므로(`python grammar_prefetch.py`),
문법 받기 층의 캐시 키가 이 파일과 의존성뿐이다 — backend 의 다른 파일이 바뀌어도 층이 CACHED 로
남아 GitHub 에서 문법을 다시 받지 않는다. 가져올 것을 더하면 그 이점이 사라지니 표준 라이브러리와
`tree_sitter_language_pack` 밖으로 나가지 않는다(구조 시험이 지킨다).
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

#: 이미지를 굽거나 CI 를 준비할 때 미리 받아 두는 문법 — 채점 중에는 내려받지 않는다.
#: `classroom.syntax_check.TREE_SITTER_LANGUAGE_BY_EXTENSION` 이 쓰는 언어와 같아야 한다
#: (시험이 맞춰 본다). 언어를 더하거나 빼면 이 파일이 바뀌어 받기 층만 다시 구워진다.
TREE_SITTER_LANGUAGES: tuple[str, ...] = (
    "c",
    "cpp",
    "go",
    "java",
    "javascript",
    "kotlin",
    "ruby",
    "tsx",
    "typescript",
)

#: 받기 재시도 — 첫 시도 뒤 간격을 두 배씩 늘려 두 번 더(총 3회).
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 2.0


def _fetch_with_retry(
    language: str,
    get_parser: Callable[[str], object],
    *,
    attempts: int,
    backoff: float,
    sleep: Callable[[float], None],
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            get_parser(language)
            return
        except Exception as error:  # noqa: BLE001 — DownloadError 외에 네트워크 예외 종류가 라이브러리 안에서 갈린다
            if attempt == attempts:
                raise
            delay = backoff * (2 ** (attempt - 1))
            print(
                f"문법 {language} 받기 실패({attempt}/{attempts}): {error} — {delay:g}초 뒤 다시",
                file=sys.stderr,
            )
            sleep(delay)


def prefetch_tree_sitter_grammars(
    *,
    attempts: int = DOWNLOAD_ATTEMPTS,
    backoff: float = DOWNLOAD_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """`TREE_SITTER_LANGUAGES` 의 문법을 캐시(`XDG_CACHE_HOME` 기준)에 받아 둔다.

    **tree-sitter-language-pack 은 문법을 설치 때가 아니라 처음 쓸 때 인터넷에서
    받는다**(2026-09-15 확인). 그대로 두면 새 컨테이너의 첫 채점이 GitHub 에서 문법을
    받느라 파싱 시간 제한에 걸리고, CI 처럼 캐시가 없는 곳에서는 판정이 통째로
    어긋났다. 그래서 백엔드 이미지를 구울 때(docker/backend.Dockerfile)와 CI 테스트
    전에 이 함수로 받아 두고, 채점 중에는 받지 않는다(`_TREE_SITTER_PARSE_SCRIPT`).
    받기가 끊기면 언어마다 짧게 다시 시도한다(#1205)."""

    from tree_sitter_language_pack import downloaded_languages, get_parser

    # `download()` 는 캐시가 빈 곳에서 개수만 돌려주고 실제로 받지 않았다(1.20.0, 새
    # 컨테이너에서 확인) — `get_parser()` 는 문법 묶음을 받아 캐시에 둔다. 그래서
    # 언어마다 파서를 한 번 만들어 받게 하고, 아래에서 캐시에 실제로 있는지 확인한다.
    for language in TREE_SITTER_LANGUAGES:
        _fetch_with_retry(language, get_parser, attempts=attempts, backoff=backoff, sleep=sleep)
    missing = sorted(set(TREE_SITTER_LANGUAGES) - set(downloaded_languages()))
    if missing:
        raise RuntimeError(f"tree-sitter 문법을 받지 못했다: {', '.join(missing)}")
    return list(TREE_SITTER_LANGUAGES)


if __name__ == "__main__":
    prepared = prefetch_tree_sitter_grammars()
    print(f"tree-sitter 문법 {len(prepared)}개 준비: {', '.join(prepared)}")
