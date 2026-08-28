"""대형 저장소를 통째로 LLM에 보내지 않기 위한 채점 대상 파일 선별 전략 (#12).

ADR-0014의 소비: "대형 프로젝트의 소스는 채점 컨텍스트 비용이 크다. 채점 대상
파일을 선별하는 전략이 필요하다"를 여기서 만족시킨다.

전략:
1. 업로드된 소스가 zip 아카이브면 소스 확장자만, 흔한 벤더·빌드 디렉터리(node_modules,
   .git, dist, build, vendor 등)는 제외하고 연다.
2. 전체 선택량이 `MAX_SOURCE_BYTES`를 넘지 않도록 예산을 두고, 예산이 바닥나면 그
   자리에서 선별을 멈춘다(마지막 파일은 잘려서라도 담을 수 있는 만큼만 담는다).
3. 바이너리로 디코딩되지 않는 파일은 건너뛴다 — 텍스트 근거만 채점 대상이다.
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


def _is_selectable(path: str) -> bool:
    lower = path.lower()
    if any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS):
        return False
    return any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS)


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
                content_bytes = archive.read(info)[:budget]
                try:
                    text = content_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                files.append(SourceFile(path=info.filename, content=text))
                budget -= len(content_bytes)
            return files
    except zipfile.BadZipFile:
        pass

    try:
        text = raw[:max_bytes].decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [SourceFile(path="source", content=text)]
