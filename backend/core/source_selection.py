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

**소스가 여럿이면 라운드로빈으로 나눠 담는다(#191).** 제출작이 `SubmissionAsset`
목록을 담게 되면서(ADR-0027) 채점 입력도 목록이 됐다 — 순서대로 채우면 첫 소스가
예산을 다 먹고 둘째부터는 채점에서 통째로 빠진다. 매 라운드마다 그 라운드에 아직
남은 소스 수로 예산을 공평하게 나눠, 한 소스가 크더라도 다른 소스의 차례를
빼앗지 못하게 한다. 어느 소스가 그 라운드에서 쓰지 않은 몫은 버려지지 않고 같은
라운드의 다음 소스에게 넘어간다(파일 하나가 그 라운드의 몫보다 작을 수 있으므로).
"""

from __future__ import annotations

import contextlib
import io
import zipfile
from dataclasses import dataclass
from typing import Callable, Iterator

from core.llm_scoring import SourceFile

# LLM 컨텍스트 비용을 억제하는 예산. 정확한 토큰 수가 아니라 대략적인 바이트
# 상한이다. gpt-4o-mini(128K 토큰)를 기준으로 보수적으로 3~4바이트/토큰 환산해
# 요구사항·지시문·출력 여유를 뺀 실질 상한이 250~300KB 근처라 300_000으로 잡는다
# (#191) — 이 값을 넘기면 컨텍스트 초과가 `LLMAdapterPermanentError`로 잡혀 그
# Submission이 이후 스캔에서 통째로 빠지므로, 소스를 많이 낸 참가자일수록 손해를
# 본다. 이 값은 정책(`PlatformPolicy`)이 아니라 코드 상수로 남는다 — 모델 토큰
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

# UTF-8 멀티바이트 시퀀스는 최대 4바이트다 — 경계에서 최대 3바이트만 잘려나갈 수
# 있으므로, 그 범위 안에서만 재시도하면 "진짜 바이너리"와 "경계에서 잘린 텍스트"를
# 구분할 수 있다.
_MAX_UTF8_TRIM = 3


def is_excluded_path(path: str) -> bool:
    """사람이 쓴 소스가 아니라고 알려진 경로인가 — 벤더·빌드 디렉터리, 잠금
    파일, 압축 번들·소스맵·바이너리. 채점 선별과 문법 검사(`classroom.
    syntax_check`)가 같은 판정을 쓴다: 잠금 파일(`package-lock.json`)은
    `.json` 이라 문법 검사의 코드 확장자에도 걸리는데, 그쪽이 따로 거르지
    않으면 생성물에 「구문 오류가 있는가」를 AI 에게 묻고 그 본문을 프롬프트에
    싣는다."""

    lower = path.lower()
    if any(fragment in lower for fragment in EXCLUDED_DIR_FRAGMENTS):
        return True
    if lower.rsplit("/", 1)[-1] in EXCLUDED_FILE_NAMES:
        return True
    return lower.endswith(EXCLUDED_SUFFIXES)


def _is_selectable(path: str) -> bool:
    return not is_excluded_path(path)


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


def _zip_candidates(raw: bytes, stack: contextlib.ExitStack) -> list[_Candidate]:
    archive = stack.enter_context(zipfile.ZipFile(io.BytesIO(raw)))
    candidates: list[_Candidate] = []
    for info in sorted(archive.infolist(), key=lambda i: i.filename):
        if info.is_dir() or not _is_selectable(info.filename):
            continue

        def _reader(budget: int, *, info=info) -> bytes:
            # archive.read(info)는 멤버 전체를 먼저 압축 해제한다 — 예산과 무관하게
            # zip bomb 하나가 메모리를 다 먹을 수 있다. archive.open()이 돌려주는
            # 스트림에서 예산만큼만 read()하면 그만큼만 압축 해제된다.
            with archive.open(info) as member:
                return member.read(budget)

        candidates.append(_Candidate(path=info.filename, reader=_reader))
    return candidates


def _source_candidates(raw: bytes, stack: contextlib.ExitStack) -> list[_Candidate]:
    if not raw:
        return []
    try:
        return _zip_candidates(raw, stack)
    except zipfile.BadZipFile:
        return [_Candidate(path="source", reader=lambda budget: raw[:budget])]


def select_source_files(
    sources: list[tuple[int, str, bytes]], *, max_bytes: int = MAX_SOURCE_BYTES
) -> list[SourceFile]:
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

    with contextlib.ExitStack() as stack:
        queues: list[tuple[int, str, Iterator[_Candidate]]] = []
        for asset_id, label, raw in sources:
            candidates = _source_candidates(raw, stack)
            if candidates:
                queues.append((asset_id, label, iter(candidates)))

        while queues and budget > 0:
            round_queues = queues
            round_size = len(round_queues)
            next_queues: list[tuple[int, str, Iterator[_Candidate]]] = []

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

                candidate = next(queue, None)
                if candidate is None:
                    continue  # 이 소스는 다 소진됐다 — 이번 라운드부터 회전에서 뺀다.

                content_bytes = candidate.reader(min(share, budget))
                text = _decode_utf8_prefix(content_bytes)
                if text is not None:
                    files.append(
                        SourceFile(
                            path=candidate.path,
                            content=text,
                            asset_id=asset_id,
                            asset_label=label,
                        )
                    )
                    budget -= len(content_bytes)

                next_queues.append((asset_id, label, queue))

            queues = next_queues

    return files
