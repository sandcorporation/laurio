"""대형 저장소를 통째로 LLM에 보내지 않기 위한 채점 대상 파일 선별 전략 (#12, #191, #287).

**공유층(`core`)에 산다(#287).** 원래 `scoring.source_selection`이었다 —
`scoring`은 공모전 가족이라(`tests/test_app_boundaries.py`), 강의실이 소스
제출을 채점하려면 이 모듈을 부를 수 있어야 했다. `core.llm_scoring.SourceFile`
(#274로 이미 공유층에 있다) 하나만 아는 완전 범용 코드였으므로 옮기는 것은
도구일 뿐 규칙을 어기지 않는다 — `core.llm_scoring`·`core.repository_adapters`와
같은 이동이다. `scoring.source_selection`은 재노출 shim으로 남는다.

ADR-0014의 소비: "대형 프로젝트의 소스는 채점 컨텍스트 비용이 크다. 채점 대상
파일을 선별하는 전략이 필요하다"를 여기서 만족시킨다.

전략:
1. 업로드된 소스가 zip 아카이브면 흔한 벤더·빌드 디렉터리(node_modules, .git, dist,
   build, vendor 등)와 **예산만 먹는 것으로 알려진 파일**(잠금 파일·압축된 번들·
   소스맵·이미지·아카이브 등)을 빼고 연다. 그 밖의 파일은 확장자와 무관하게 후보다
   — 「코드 확장자만」 고르던 허용 목록을 2026-10-02 에 차단 목록으로 뒤집었다.
   허용 목록은 `.txt`(Packet Tracer 장비 설정)·`Dockerfile`·확장자 없는
   `README` 를 조용히 버렸고, staging 의 `octocat/Hello-World` 는 그 때문에
   「채점할 파일 0개」가 됐다(ADR-0031). 바이너리는 3번이 따로 거른다.
2. 예산은 앱 코드부터 채운다(#986, `selection_tier`) — 앱 코드 → README → 그 밖의 텍스트 →
   마이그레이션·배포·설정. 「코드 아님」(시험·문서·스크래치·생성물·데이터 json)은 아예 뺀다
   (`excluded_kind`, 보탬 4). 경로 이름 순 하나로 채우던 때는 앞 글자 폴더(`.scratch/`·
   `deploy/`·`backend/.sqlx/`)가 예산을 다 써 앱 코드가 0파일인 제출이 0%를 받았다. 예산 밖으로
   빠진 양은 `SelectionOmission` 으로 돌려준다.
   전체 선택량이 `MAX_SOURCE_BYTES`를 넘지 않도록 예산을 두고, 예산이 바닥나면 그
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
5. 3번이 버리는 파일은 버리기 전에 등록된 변환 플러그인(`core.source_converters`,
   설정 `SOURCE_CONVERTERS`)에게 묻는다(#496). 플러그인이 「내 형식」이라며 낸
   텍스트는 같은 소스의 큐 앞에 끼워져 다른 파일과 같은 예산·라운드로빈을 받는다.
   형식을 확정한 뒤 실패하면 그 파일 자리에 「열 수 없는 ○○ 파일」 한 줄을 남긴다
   — 채점자가 「설정이 없다」로 오판하지 않게. 플러그인의 예외·시간 상한·입력
   크기 상한은 그 파일 하나로 끝나고 선별은 계속된다.

**소스가 여럿이면 라운드로빈으로 나눠 담는다(#191).** 제출작이 `SubmissionAsset`
목록을 담게 되면서(ADR-0027) 채점 입력도 목록이 됐다 — 순서대로 채우면 첫 소스가
예산을 다 먹고 둘째부터는 채점에서 통째로 빠진다. 매 라운드마다 그 라운드에 아직
남은 소스 수로 예산을 공평하게 나눠, 한 소스가 크더라도 다른 소스의 차례를
빼앗지 못하게 한다. 어느 소스가 그 라운드에서 쓰지 않은 몫은 버려지지 않고 같은
라운드의 다음 소스에게 넘어간다(파일 하나가 그 라운드의 몫보다 작을 수 있으므로).
"""

from __future__ import annotations

import collections
import concurrent.futures
import contextlib
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import Callable

from core.runtime_settings_port import repository_download_limit_bytes

from core.llm_scoring import SourceFile
from core.source_converters import (
    SourceConversionFailed,
    SourceConverter,
    registered_converters,
)

logger = logging.getLogger(__name__)

# LLM 컨텍스트 비용을 억제하는 예산. 정확한 토큰 수가 아니라 대략적인 바이트
# 상한이다. gpt-4o-mini(128K 토큰)를 기준으로 보수적으로 3~4바이트/토큰 환산해
# 요구사항·지시문·출력 여유를 뺀 실질 상한이 250~300KB 근처라 300_000으로 잡는다
# (#191). 지금은 완성도 검사·강의실 에이전트 채점의 기본 예산이다 — 한 번 호출 채점은 모델
# 컨텍스트에서 예산을 정하고(`core.model_context`), 넘치면 자르지 않고 보류한다(#986·#989). 이 값은 정책(`PlatformPolicy`)이 아니라 코드 상수로 남는다 — 모델 토큰
# 한도에 묶인 기술값이지 사업이 정하는 값이 아니다(ADR-0027).
MAX_SOURCE_BYTES = 300_000

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

#: 변환 플러그인에게 넘기는 파일 하나의 상한 — 그보다 큰 파일은 묻지 않고 버린다. 저장소 zip
#: 다운로드 상한(운영 설정 `REPOSITORY_DOWNLOAD_LIMIT_MB`)을 그대로 따른다(#1005): 그 이상은
#: 어차피 한 제출 안에 들어오지 않는다.

#: 변환 플러그인 하나가 파일 하나에 쓸 수 있는 시간. 넘기면 그 파일만 버리고 선별을
#: 계속한다 — 워커가 플러그인 하나에 붙잡히지 않게.
CONVERTER_TIMEOUT_SECONDS = 10.0

# UTF-8 멀티바이트 시퀀스는 최대 4바이트다 — 경계에서 최대 3바이트만 잘려나갈 수
# 있으므로, 그 범위 안에서만 재시도하면 "진짜 바이너리"와 "경계에서 잘린 텍스트"를
# 구분할 수 있다.
_MAX_UTF8_TRIM = 3


#: 「코드 아님」 제외 규칙(#986 보탬 4, 대장 #1438) — 구현을 증명하지 않는 것을 후보에서 뺀다.
#: 공모전 3 의 16건을 요구사항 22개와 대조해 정했다: 시험·문서는 「구현했다」는 주장일 뿐이고,
#: yml/yaml/toml/sql/conf/Dockerfile/compose·migrations 는 **남긴다**(미디어 서버 설정의 녹화·
#: 훅, 마이그레이션·스키마 SQL·compose 볼륨이 영구 저장·송출 요구사항의 근거다).
#: 디렉터리는 경로 조각 하나와 같으면 걸린다(소문자, 어느 깊이든).
EXCLUDED_DIR_NAMES: dict[str, frozenset[str]] = {
    "docs": frozenset({"docs"}),
    "scratch": frozenset({
        ".scratch", "experiments", "scratch", ".claude", ".agents", ".cursor", ".github", ".vscode", ".idea",
    }),
    "generated": frozenset({".sqlx", "generated"}),
    "tests": frozenset({"test", "tests", "__tests__", "e2e", "spec"}),
}

#: 끝이 이것이면 빼는 파일(소문자). `.txt` 는 **뺄 목록에 없다** — Packet Tracer 장비 설정
#: (`configs/R1.txt`)이 그 확장자라 빼면 네트워크 과제의 근거가 사라진다(ADR-0031, 2026-10-02 에
#: 허용 목록이 `.txt` 를 버려 「채점할 파일 0개」가 된 일).
EXCLUDED_KIND_SUFFIXES: dict[str, tuple[str, ...]] = {
    "docs": (".md", ".mdx", ".rst"),
    "generated": (".snap", ".svg", ".csv", ".lock", ".min.js", "schema.d.ts"),
    "data_json": (".json",),
}

#: 데이터 json 규칙의 예외 — 의존성·빌드 설정이라 남긴다.
KEPT_JSON_NAMES = frozenset({"package.json", "tsconfig.json", "composer.json"})

_TEST_FILE_PATTERN = re.compile(r"(\.test\.|\.spec\.|_test\.(go|py)$|^test_.*\.py$)")


def excluded_kind(path: str) -> str | None:
    """이 경로를 빼는 까닭(묶음 이름) — 남기면 None. 판정은 여기 한 자리다: 공모전·강의실 선별과
    강의실 문법 검사(`classroom.syntax_check`)가 모두 `is_excluded_path` 로 이것을 본다.

    묶음: `vendor`(벤더·빌드 폴더, 잠금 파일, 압축 번들·소스맵·바이너리) · `docs` · `scratch` ·
    `generated` · `tests` · `data_json`. 루트(깊이 ≤1 — GitHub zip 은 `<저장소>-<sha>/README.md`)의
    `README.md` 는 문서지만 남긴다."""

    lower = path.lower()
    if any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS):
        return "vendor"
    segments = [segment for segment in lower.split("/") if segment]
    if not segments:
        return None
    name = segments[-1]
    if name in EXCLUDED_FILE_NAMES or lower.endswith(EXCLUDED_SUFFIXES):
        return "vendor"
    directories = set(segments[:-1])
    for kind, names in EXCLUDED_DIR_NAMES.items():
        if directories & names:
            return kind
    if _TEST_FILE_PATTERN.search(name):
        return "tests"
    if name == "readme.md" and len(segments) <= 2:
        return None
    for kind, suffixes in EXCLUDED_KIND_SUFFIXES.items():
        if name.endswith(suffixes) and not (kind == "data_json" and name in KEPT_JSON_NAMES):
            return kind
    return None


def is_excluded_path(path: str) -> bool:
    """사람이 쓴 소스·구현 근거가 아니라고 알려진 경로인가(`excluded_kind`). 채점 선별과 문법 검사
    (`classroom.syntax_check`)가 같은 판정을 쓴다: 잠금 파일(`package-lock.json`)은 `.json` 이라
    문법 검사의 코드 확장자에도 걸리는데, 그쪽이 따로 거르지 않으면 생성물에 「구문 오류가
    있는가」를 AI 에게 묻고 그 본문을 프롬프트에 싣는다."""

    return excluded_kind(path) is not None


def _is_selectable(path: str) -> bool:
    return not is_excluded_path(path)


#: 코드로 치는 확장자(소문자) — 예산을 채우는 순서에서 맨 앞에 온다(#986, `selection_tier`).
CODE_SUFFIXES = (
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte",
    ".java", ".kt", ".kts", ".scala", ".go", ".rs", ".rb", ".php", ".cs", ".fs",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".m", ".mm", ".swift", ".dart",
    ".ex", ".exs", ".erl", ".clj", ".lua", ".r", ".jl", ".hs", ".ml",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".sql", ".sh", ".gd",
)

#: 이 폴더 아래의 코드는 앱 코드 다음 차례(2)다 — 남기지만(구현 근거) 앱 코드의 예산을 먼저 쓰지 않게.
SECONDARY_DIR_NAMES = frozenset({"migrations", "deploy", "infra", "examples", "fixtures"})


def selection_tier(path: str) -> int:
    """예산을 채우는 차례(작을수록 먼저, #986). 같은 차례 안에서는 경로 이름 순이라 결정적이다.

    0 앱 코드 → 1 README → 2 그 밖(설정·yml·sql·Dockerfile·마이그레이션·배포·숨은 폴더).
    「코드 아님」은 이 차례에 오기 전에 `excluded_kind` 가 뺀다. 예전에는 경로 이름 순 하나였다 —
    앞 글자 폴더가 크면 앱 코드가 예산 밖으로 밀렸다.
    """

    segments = [segment for segment in path.lower().split("/") if segment]
    if not segments:
        return 2
    name = segments[-1]
    directories = segments[:-1]
    if name.startswith("readme"):
        return 1
    if (
        name.endswith(CODE_SUFFIXES)
        and not SECONDARY_DIR_NAMES.intersection(directories)
        and not any(segment.startswith(".") for segment in directories)
    ):
        return 0
    return 2


def _decode_utf8_prefix(data: bytes) -> str | None:
    """budget 경계에서 멀티바이트 시퀀스가 잘렸을 수 있으니 끝에서 최대 3바이트까지
    떼어내며 재시도한다. 그래도 실패하면 진짜 바이너리로 보고 None을 돌려준다.

    **NUL 바이트가 있으면 디코딩하기 전에 바이너리로 본다**(2026-10-02, git 의
    판정과 같다). NUL 은 UTF-8 로 유효해서 디코딩만으로는 걸리지 않는데, 그대로
    프롬프트에 실리면 채점 결과(`prompt`)를 저장하는 순간 PostgreSQL 이 text 에
    NUL 을 받지 않아 `DataError` 로 채점 전체가 깨진다. 확장자 허용 목록이 있던
    동안은 맥 zip 의 `__MACOSX/._*` 같은 파일이 우연히 걸러져 이 길이 안 보였다."""

    if b"\x00" in data:
        return None
    for trim in range(0, _MAX_UTF8_TRIM + 1):
        chunk = data[: len(data) - trim] if trim else data
        try:
            return chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


@dataclass(frozen=True)
class _Candidate:
    """소스 하나 안에서 채점 대상이 될 수 있는 파일 하나 — 실제로 뽑힐 때까지는
    읽지 않는다(zip bomb 방어는 `reader`가 호출될 때 예산만큼만 스트리밍한다)."""

    path: str
    reader: Callable[[int], bytes]
    #: 원본 파일인가 — 변환 결과·「열 수 없는」 줄은 다시 플러그인에게 묻지 않는다.
    convertible: bool = True
    #: 풀었을 때의 크기(모르면 None) — 예산 밖으로 빠진 양을 셀 때만 쓴다(#986).
    size: int | None = None


def _text_candidate(path: str, text: str) -> _Candidate:
    encoded = text.encode("utf-8")
    return _Candidate(path=path, reader=lambda budget: encoded[:budget], convertible=False)


def _run_converter(converter: SourceConverter, raw: bytes, path: str):
    """시간 상한 안에서 플러그인 하나를 돌린다. 파이썬은 스레드를 죽일 수 없으므로
    상한을 넘긴 플러그인은 뒤에서 끝까지 돌지만, 선별은 기다리지 않고 넘어간다 —
    플러그인 쪽이 자기 작업을 묶어 둘 책임이 있다(압축 해제 상한 등)."""

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(converter.convert, raw, path=path)
        return future.result(timeout=CONVERTER_TIMEOUT_SECONDS)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _convert(candidate: _Candidate, converters: tuple[SourceConverter, ...]) -> list[_Candidate]:
    """UTF-8로 못 읽은 원본 파일 하나를 플러그인들에게 차례로 묻는다. 아무도
    맡지 않으면 빈 목록 — 예전처럼 그 파일은 버려진다."""

    limit = repository_download_limit_bytes()
    raw = candidate.reader(limit + 1)
    if len(raw) > limit:
        logger.warning("변환하기에 너무 큰 파일을 건너뛴다(path=%s).", candidate.path)
        return []

    for converter in converters:
        try:
            converted = _run_converter(converter, raw, candidate.path)
        except SourceConversionFailed as exc:
            logger.info("변환 실패(형식 확정 뒤, path=%s): %s", candidate.path, exc)
            return [
                _text_candidate(
                    candidate.path,
                    f"(열 수 없는 {converter.format_name} 파일 — 내용을 읽지 못했다)",
                )
            ]
        except concurrent.futures.TimeoutError:
            logger.warning(
                "변환 플러그인 %s 이 시간 상한을 넘겼다(path=%s).",
                type(converter).__name__,
                candidate.path,
            )
            return []
        except Exception:
            logger.exception(
                "변환 플러그인 %s 이 예외를 던졌다(path=%s).", type(converter).__name__, candidate.path
            )
            continue
        if converted is None:
            continue
        return [_text_candidate(f"{candidate.path}/{f.name}", f.content) for f in converted]
    return []


def _zip_candidates(raw: bytes, stack: contextlib.ExitStack) -> list[_Candidate]:
    archive = stack.enter_context(zipfile.ZipFile(io.BytesIO(raw)))
    candidates: list[_Candidate] = []
    # 앱 코드가 먼저다(#986, `selection_tier`) — 같은 차례 안에서는 경로 이름 순.
    for info in sorted(archive.infolist(), key=lambda i: (selection_tier(i.filename), i.filename)):
        if info.is_dir() or not _is_selectable(info.filename):
            continue

        def _reader(budget: int, *, info=info) -> bytes:
            # archive.read(info)는 멤버 전체를 먼저 압축 해제한다 — 예산과 무관하게
            # zip bomb 하나가 메모리를 다 먹을 수 있다. archive.open()이 돌려주는
            # 스트림에서 예산만큼만 read()하면 그만큼만 압축 해제된다.
            with archive.open(info) as member:
                return member.read(budget)

        candidates.append(_Candidate(path=info.filename, reader=_reader, size=info.file_size))
    return candidates


def _source_candidates(raw: bytes, stack: contextlib.ExitStack) -> list[_Candidate]:
    if not raw:
        return []
    try:
        return _zip_candidates(raw, stack)
    except zipfile.BadZipFile:
        return [_Candidate(path="source", reader=lambda budget: raw[:budget], size=len(raw))]


@dataclass(frozen=True)
class SelectionOmission:
    """예산 때문에 프롬프트에 다 싣지 못한 것(#986) — 통째로 빠진 파일과 중간에서 잘린 파일.
    `code_*` 는 그중 앱 코드(`selection_tier` 0)만 센다. 바이트는 풀었을 때의 크기 기준이다."""

    omitted_files: int = 0
    omitted_bytes: int = 0
    omitted_code_files: int = 0
    truncated_files: int = 0
    truncated_code_files: int = 0

    @property
    def any(self) -> bool:
        """무엇이든 빠지거나 잘렸는가 — 공모전 보류 기준(#986 보탬 4). 「코드 아님」은 후보에 오기 전에
        빠지므로 여기 남은 것은 전부 구현 근거다."""

        return bool(self.omitted_files or self.truncated_files)


def select_source_files(
    sources: list[tuple[int, str, bytes]], *, max_bytes: int = MAX_SOURCE_BYTES
) -> list[SourceFile]:
    """`select_source_files_with_omission` 의 고른 파일만."""

    return select_source_files_with_omission(sources, max_bytes=max_bytes)[0]


def select_source_files_with_omission(
    sources: list[tuple[int, str, bytes]], *, max_bytes: int = MAX_SOURCE_BYTES
) -> tuple[list[SourceFile], SelectionOmission]:
    """여러 소스(각각 `(자산 id, 자산 라벨, 원본 바이트)`)를 예산 안에서 라운드로빈으로
    고른다.

    `sources`가 비어 있으면 빈 목록을 돌려준다. 소스 하나짜리 입력에서도 동작은
    이전과 같다 — 예산 전체를 그 하나가 쓴다.

    **자산 id는 정체성, 라벨은 표시일 뿐이다(#191 코드리뷰 지적).** 라벨은
    참가자가 자유 텍스트로 쓰는 값이라 서로 다른 자산이 같은 라벨을 가질 수
    있고(`SubmissionAsset.label`에는 유니크 제약이 없다), 라벨이 비었을 때의
    폴백 표시(`scoring.services._asset_label`)도 참가자가 그대로 타이핑하면
    충돌한다. 그래서 "이 파일이 어느 자산에서 왔는가"는 `SourceFile.asset_id`로만
    판단해야 한다 — 호출자가 `Score.scored_assets`를 채울 때 라벨 문자열로
    되짚어 찾지 않게 하기 위해서다.
    """

    files: list[SourceFile] = []
    budget = max_bytes
    converters = registered_converters()
    truncated = 0
    truncated_code = 0

    with contextlib.ExitStack() as stack:
        queues: list[tuple[int, str, collections.deque[_Candidate]]] = []
        for asset_id, label, raw in sources:
            candidates = _source_candidates(raw, stack)
            if candidates:
                queues.append((asset_id, label, collections.deque(candidates)))

        while queues and budget > 0:
            round_queues = queues
            round_size = len(round_queues)
            next_queues: list[tuple[int, str, collections.deque[_Candidate]]] = []

            for index, (asset_id, label, queue) in enumerate(round_queues):
                if budget <= 0:
                    continue

                # 이 라운드에서 아직 처리되지 않은 소스 수(자기 자신 포함)로 남은
                # 예산을 공평하게 나눈다 — 앞선 소스가 크더라도 뒤 소스의 차례를
                # 통째로 빼앗지 못하게 한다(#191). 어느 소스가 실제로 덜 쓰면 그
                # 차이는 `budget` 갱신을 통해 같은 라운드의 다음 소스에게 자연히
                # 넘어간다. 라운드 안에서의 순서(`index`)만으로 나머지 수를 구하므로
                # 별도의 감소 카운터가 필요 없다.
                share = max(budget // (round_size - index), 1)

                if not queue:
                    continue  # 이 소스는 다 소진됐다 — 이번 라운드부터 회전에서 뺀다.
                candidate = queue.popleft()

                content_bytes = candidate.reader(min(share, budget))
                text = _decode_utf8_prefix(content_bytes)
                if text is None and candidate.convertible and converters:
                    # 변환 결과를 이 소스의 큐 앞에 끼운다 — 이번 차례는 묻는 데
                    # 썼으니, 결과는 다음 라운드부터 다른 파일과 같은 몫을 받는다.
                    queue.extendleft(reversed(_convert(candidate, converters)))
                elif text is not None:
                    files.append(
                        SourceFile(
                            path=candidate.path,
                            content=text,
                            asset_id=asset_id,
                            asset_label=label,
                        )
                    )
                    budget -= len(content_bytes)
                    if candidate.size is not None and len(content_bytes) < candidate.size:
                        truncated += 1
                        if candidate.convertible and selection_tier(candidate.path) == 0:
                            truncated_code += 1

                next_queues.append((asset_id, label, queue))

            queues = next_queues

        left = [candidate for _asset_id, _label, queue in queues for candidate in queue]

    omission = SelectionOmission(
        omitted_files=len(left),
        omitted_bytes=sum(c.size or 0 for c in left),
        omitted_code_files=sum(1 for c in left if c.convertible and selection_tier(c.path) == 0),
        truncated_files=truncated,
        truncated_code_files=truncated_code,
    )
    return files, omission
