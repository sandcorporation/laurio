"""「벤더·빌드」 경로 판정 — 사람이 쓰지 않은 것(의존성·빌드 산출물·VCS 기록·잠금 파일·바이너리).

선별(`core.source_selection.excluded_kind` 의 `vendor` 묶음)과 에이전트 실행기(`agent-grader`
의 박제본 풀기 — 폴더 조각만, #1300)가 이 파일 하나를 같이 쓴다. 실행기 이미지(`docker/agent-grader.Dockerfile`)에
옆 파일로 복사되므로 **표준 라이브러리만** 쓴다.
"""

from __future__ import annotations

#: 이름 그대로 빼는 파일(소문자로 비교한다) — 사람이 쓰지 않은 잠금 파일이다. 수백 KB 가 흔하고,
#: 선별은 경로 이름 순서로 예산을 채우므로 이것 하나가 코드의 차례를 통째로
#: 빼앗는다.
EXCLUDED_FILE_NAMES = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "npm-shrinkwrap.json",
    "bun.lockb", "uv.lock", "poetry.lock", "pipfile.lock", "cargo.lock",
    "gemfile.lock", "composer.lock", "go.sum", "gradle.lockfile",
    # 맥 Finder 가 디렉터리마다 남기는 메타데이터 — 사람이 쓴 것이 아니다.
    ".ds_store",
})

#: 끝이 이것이면 빼는 파일. 압축된 번들과 소스맵은 텍스트지만 읽을 수 없는
#: 기계 산출물이고, 나머지는 바이너리다 — 바이너리는 디코딩이 어차피 거르지만
#: 이름으로 먼저 빼면 예산만큼 읽어 보지도 않는다(우연히 UTF-8 로 읽히는
#: 바이너리가 프롬프트에 섞이는 것도 막는다).
EXCLUDED_SUFFIXES = (
    ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".jar", ".war", ".class", ".pyc", ".o", ".a", ".so", ".dll", ".exe", ".dylib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav",
    ".sqlite", ".sqlite3", ".db",
)

EXCLUDED_DIR_FRAGMENTS = (
    "node_modules/", ".git/", "dist/", "build/", "vendor/", "__pycache__/", "__macosx/",
    ".venv/", "venv/", "target/", ".next/", "coverage/", ".gradle/", ".idea/",
)


def is_vendor_dir_path(path: str) -> bool:
    """벤더·빌드·VCS 폴더(`EXCLUDED_DIR_FRAGMENTS`) 아래면 참 — 에이전트 실행기는 이것만 풀지 않는다(#1300)."""

    lower = path.lower()
    return any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS)


def is_vendor_path(path: str) -> bool:
    """벤더·빌드 폴더 아래이거나, 잠금 파일·압축 번들·소스맵·바이너리면 참(선별의 `vendor` 묶음)."""

    if is_vendor_dir_path(path):
        return True
    lower = path.lower()
    name = next((segment for segment in reversed(lower.split("/")) if segment), "")
    return bool(name) and (name in EXCLUDED_FILE_NAMES or lower.endswith(EXCLUDED_SUFFIXES))
