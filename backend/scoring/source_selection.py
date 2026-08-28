"""대형 저장소를 통째로 LLM에 보내지 않기 위한 채점 대상 파일 선별 전략 (#12).

ADR-0014의 소비: "대형 프로젝트의 소스는 채점 컨텍스트 비용이 크다. 채점 대상
파일을 선별하는 전략이 필요하다"를 여기서 만족시킨다.

전략:
1. 업로드된 소스가 zip 아카이브면 소스 확장자만, 흔한 벤더·빌드 디렉터리(node_modules,
   .git, dist, build, vendor 등)는 제외하고 연다.
2. 전체 선택량이 `MAX_SOURCE_BYTES`를 넘지 않도록 예산을 두고, 예산이 바닥나면 그
   자리에서 선별을 멈춘다(마지막 파일은 잘려서라도 담을 수 있는 만큼만 담는다).
   압축 해제 자체도 예산만큼만 한다(`ZipExtFile.read(budget)`로 스트리밍 read) —
   `archive.read(info)`로 멤버 전체를 먼저 압축 해제한 뒤 슬라이스하면, 압축률이
   극단적인 zip bomb 하나가 예산 확인 전에 메모리를 다 먹어버린다.
3. 바이너리로 디코딩되지 않는 파일은 건너뛴다 — 텍스트 근거만 채점 대상이다. 단,
   예산 경계에서 멀티바이트 UTF-8 시퀀스가 잘려 디코딩이 실패하는 경우는 파일이
   바이너리라서가 아니라 우리가 중간에서 끊었기 때문이므로, 끝에서 최대 3바이트까지
   떼어내며 재시도해 유효한 접두부는 살린다.
4. zip이 아니면(단일 텍스트 파일처럼 온 경우) 원문을 예산까지만 담는다 — 실제
   업로드는 아카이브가 보통이지만, 이 분기가 있어야 선별 전략이 입력 형태 하나에
   의존해 깨지지 않는다.
"""

from __future__ import annotations

import io
import zipfile

from .adapters import SourceFile

# LLM 컨텍스트 비용을 억제하는 예산. 정확한 토큰 수가 아니라 대략적인 바이트
# 상한이다 — 실제 어댑터가 붙으면 모델별 토큰 한도에 맞춰 조정하면 된다.
MAX_SOURCE_BYTES = 200_000

ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts", ".go", ".rb",
    ".php", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".cs", ".m",
    ".html", ".css", ".scss", ".vue", ".svelte", ".json", ".yaml", ".yml", ".md",
    ".sql", ".sh",
}

EXCLUDED_DIR_FRAGMENTS = (
    "node_modules/", ".git/", "dist/", "build/", "vendor/", "__pycache__/",
    ".venv/", "venv/", "target/", ".next/", "coverage/", ".gradle/", ".idea/",
)

# UTF-8 멀티바이트 시퀀스는 최대 4바이트다 — 경계에서 최대 3바이트만 잘려나갈 수
# 있으므로, 그 범위 안에서만 재시도하면 "진짜 바이너리"와 "경계에서 잘린 텍스트"를
# 구분할 수 있다.
_MAX_UTF8_TRIM = 3


def _is_selectable(path: str) -> bool:
    lower = path.lower()
    if any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS):
        return False
    return any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS)


def _decode_utf8_prefix(data: bytes) -> str | None:
    """budget 경계에서 멀티바이트 시퀀스가 잘렸을 수 있으니 끝에서 최대 3바이트까지
    떼어내며 재시도한다. 그래도 실패하면 진짜 바이너리로 보고 None을 돌려준다."""

    for trim in range(0, _MAX_UTF8_TRIM + 1):
        chunk = data[: len(data) - trim] if trim else data
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def select_source_files(raw: bytes, *, max_bytes: int = MAX_SOURCE_BYTES) -> list[SourceFile]:
    if not raw:
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            files: list[SourceFile] = []
            budget = max_bytes
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                if budget <= 0:
                    break
                if info.is_dir() or not _is_selectable(info.filename):
                    continue
                # archive.read(info)는 멤버 전체를 먼저 압축 해제한다 — 예산과
                # 무관하게 zip bomb 하나가 메모리를 다 먹을 수 있다. archive.open()이
                # 돌려주는 스트림에서 예산만큼만 read()하면 그만큼만 압축 해제된다.
                with archive.open(info) as member:
                    content_bytes = member.read(budget)
                text = _decode_utf8_prefix(content_bytes)
                if text is None:
                    continue
                files.append(SourceFile(path=info.filename, content=text))
                budget -= len(content_bytes)
            return files
    except zipfile.BadZipFile:
        pass

    text = _decode_utf8_prefix(raw[:max_bytes])
    if text is None:
        return []
    return [SourceFile(path="source", content=text)]
