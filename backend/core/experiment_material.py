"""채점 방식 실험의 재료 사본(#1262) — 운영 강의실 제출을 가명으로 꺼낸 파일 하나의 꼴과 그 파일을 다루는 규칙.

운영에서 `classroom` 의 `export_experiment_material` 이 쓰고, 개발 환경에서 `scoring` 의 `compare_scoring_methods
--material` 이 읽는다. 두 앱은 서로 import 하지 못하므로(강의실 ↮ 공모전, ADR-0037) 꼴은 공유층인 여기 둔다.

- **담는 것**: 운영 채점이 읽은 소스 바이트(저장소는 고정 커밋의 zip), 문제 지문·채점 지침, 체크리스트 항목(id·라벨·
  등급·숨김·점수), 운영 판정(항목 id·충족·근거)과 model_version.
- **담지 않는 것**: 학생·강사 이름, 계정·멤버 id, 이메일, 클래스 이름, 제출 시각, 운영 제출 id, 자산 라벨(참가자가 쓴
  자유 글). 제출은 가명 id(`pseudonym`)로만 남는다.
- 파일은 tar.gz 하나 — `manifest.json`(가져온 날짜·실험 이름·건수·체크섬)과 제출마다 `items/<가명>.json`·`.src`.
  권한은 0600 이다.
- 사본은 저장소 밖에 둔다(기본 `~/.cache/codemit-work/experiment-material/<이름>/`, 0700). 저장소 안·/tmp 아래면
  읽지 않는다. 가져온 지 7일이 넘으면 미리 보기·보고표가 경고한다.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from core.registry import Slot

FORMAT = 1
STALE_AFTER = timedelta(days=7)
#: 사본의 기본 자리 — 저장소 밖, 사용자만 읽는다.
DEFAULT_ROOT = Path.home() / ".cache" / "codemit-work" / "experiment-material"
#: 사본을 두지 않는 임시 자리(재부팅·다른 사용자에게 열림). 시험이 바꿔 끼운다.
TEMP_ROOTS: tuple[Path, ...] = (Path("/tmp"), Path("/private/tmp"))
_MANIFEST = "manifest.json"


class MaterialError(Exception):
    """사본을 쓰거나 읽을 수 없다 — 명령이 그대로 찍고 멈춘다."""


@dataclass(frozen=True)
class ChecklistEntry:
    id: int
    label: str
    grade: str  # "required" | "optional" (가산은 운영 채점이 읽지 않아 담지 않는다)
    hidden: bool
    points: int


@dataclass(frozen=True)
class ProductionVerdict:
    checklist_item_id: int
    is_met: bool
    reasoning: str


@dataclass(frozen=True)
class ProblemText:
    title: str
    description: str
    grading_strictness: str
    grading_guideline_text: str
    syntax_check_enabled: bool
    reasoning_effort: str | None  # 운영 채점이 쓴 추론 강도(문제 설정)
    marked_reasoning: bool


@dataclass(frozen=True)
class Item:
    """제출 하나 — 가명 id 와 운영 채점이 본 것."""

    material_id: str
    asset_kind: str  # "source" | "repository"
    source: bytes
    problem: ProblemText
    checklist: tuple[ChecklistEntry, ...]
    verdicts: tuple[ProductionVerdict, ...]
    model_version: str

    @property
    def key(self) -> int:
        """가명을 정수로 — 실행 토큰·보고표처럼 정수 id 를 받는 자리에 쓴다(운영 제출 id 와 섞이지 않게 48비트)."""

        return int(self.material_id, 16)

    def production_score(self) -> float:
        """운영 점수 = 필수 충족 비율(%). 필수가 없으면 100(공모전 `_percentage` 와 같다)."""

        required = {c.id for c in self.checklist if c.grade == "required"}
        if not required:
            return 100.0
        met = sum(1 for v in self.verdicts if v.checklist_item_id in required and v.is_met)
        return round(met / len(required) * 100, 2)


@dataclass(frozen=True)
class Manifest:
    format: int
    name: str
    exported_at: datetime
    count: int
    checksum: str  # 항목 파일들의 sha256(이름 순)

    def is_stale(self, now: datetime) -> bool:
        return now - self.exported_at > STALE_AFTER


@dataclass(frozen=True)
class MaterialSet:
    manifest: Manifest
    items: tuple[Item, ...]
    path: Path


def pseudonym(name: str, submission_id: int) -> str:
    """실험 이름을 솔트로 한 가명 — 같은 실험 이름이면 같은 제출이 같은 가명이고, 이름이 다르면 이어 붙일 수 없다."""

    return hashlib.sha256(f"{name}:{submission_id}".encode()).hexdigest()[:12]


def stale_warning(manifest: Manifest, now: datetime) -> str | None:
    if not manifest.is_stale(now):
        return None
    days = (now - manifest.exported_at).days
    return f"경고: 재료 {manifest.name} 은 가져온 지 {days}일 — 7일이 넘었다. 다 쓴 사본은 --purge-material 로 지운다."


# ── 쓰기 ─────────────────────────────────────────────────────────────────────────────────────────────


def _item_json(item: Item) -> bytes:
    body = {
        "material_id": item.material_id,
        "asset_kind": item.asset_kind,
        "problem": item.problem.__dict__,
        "checklist": [c.__dict__ for c in item.checklist],
        "verdicts": [v.__dict__ for v in item.verdicts],
        "model_version": item.model_version,
    }
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode()


def _checksum(members: Sequence[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for member_name, data in sorted(members):
        digest.update(member_name.encode() + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()


def write(out: Path, *, name: str, exported_at: datetime, items: Sequence[Item]) -> int:
    """사본 파일을 0600 으로 새로 쓴다(있으면 거절). 돌려주는 것은 파일 크기(바이트)."""

    members: list[tuple[str, bytes]] = []
    for item in items:
        members.append((f"items/{item.material_id}.json", _item_json(item)))
        members.append((f"items/{item.material_id}.src", item.source))
    manifest = {
        "format": FORMAT, "name": name, "exported_at": exported_at.isoformat(), "count": len(items),
        "checksum": _checksum(members),
    }
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise MaterialError(f"{out} 이 이미 있다 — 덮어쓰지 않는다") from exc
    os.fchmod(fd, 0o600)  # umask 와 상관없이
    with os.fdopen(fd, "wb") as fh, tarfile.open(fileobj=fh, mode="w:gz") as tar:
        for member_name, data in [(_MANIFEST, json.dumps(manifest, ensure_ascii=False).encode()), *members]:
            info = tarfile.TarInfo(member_name)
            info.size = len(data)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
    return out.stat().st_size


# ── 자리 ─────────────────────────────────────────────────────────────────────────────────────────────


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def check_location(path: Path, *, repo_root: Path) -> None:
    """사본이 저장소 안이나 임시 자리 아래면 거절한다 — 커밋·남의 눈에 닿을 수 있다."""

    candidates = {path.absolute(), path.resolve()}
    if any(_inside(p, repo_root.resolve()) for p in candidates):
        raise MaterialError(f"사본이 저장소 안에 있다 — 저장소 밖({DEFAULT_ROOT})으로 옮긴다")
    for root in TEMP_ROOTS:
        if any(_inside(p, root) or _inside(p, root.resolve()) for p in candidates):
            raise MaterialError(f"사본이 임시 자리({root}) 아래에 있다 — {DEFAULT_ROOT} 아래로 옮긴다")


def _validated_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in {".", ".."} or name.startswith("."):
        raise MaterialError(f"재료 이름이 아니다: {name!r}")
    return name


def purge(name: str, *, root: Path | None = None) -> bool:
    """`<root>/<이름>/` 을 통째로 지운다. 없었으면 거짓."""

    target = (root or DEFAULT_ROOT) / _validated_name(name)
    if not target.exists():
        return False
    shutil.rmtree(target)
    return True


# ── 읽기 ─────────────────────────────────────────────────────────────────────────────────────────────


def _str(value: object, key: str) -> str:
    if not isinstance(value, str):
        raise MaterialError(f"사본 항목의 {key} 가 글이 아니다")
    return value


def _parse_item(raw: dict[str, object], source: bytes) -> Item:
    problem = raw.get("problem")
    checklist = raw.get("checklist")
    verdicts = raw.get("verdicts")
    if not isinstance(problem, dict) or not isinstance(checklist, list) or not isinstance(verdicts, list):
        raise MaterialError("사본 항목의 꼴이 다르다")
    try:
        return Item(
            material_id=_str(raw.get("material_id"), "material_id"),
            asset_kind=_str(raw.get("asset_kind"), "asset_kind"),
            source=source,
            problem=ProblemText(**problem),
            checklist=tuple(ChecklistEntry(**c) for c in checklist),
            verdicts=tuple(ProductionVerdict(**v) for v in verdicts),
            model_version=_str(raw.get("model_version"), "model_version"),
        )
    except TypeError as exc:
        raise MaterialError(f"사본 항목의 꼴이 다르다: {exc}") from exc


def load(path: Path, *, repo_root: Path) -> MaterialSet:
    """사본 하나를 읽는다 — 자리 규칙·체크섬을 보고, 파일 0600·폴더 0700 으로 좁힌다(scp 가 넓게 만든다)."""

    check_location(path, repo_root=repo_root)
    if not path.is_file():
        raise MaterialError(f"사본 파일이 없다: {path}")
    os.chmod(path, 0o600)
    os.chmod(path.parent, 0o700)
    members: dict[str, bytes] = {}
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            for info in tar.getmembers():
                if not info.isfile():
                    continue
                fh = tar.extractfile(info)
                if fh is not None:
                    members[info.name] = fh.read()
    except (tarfile.TarError, OSError) as exc:
        raise MaterialError(f"사본을 열 수 없다: {exc}") from exc
    if _MANIFEST not in members:
        raise MaterialError("사본에 manifest.json 이 없다")
    meta = json.loads(members.pop(_MANIFEST))
    if not isinstance(meta, dict) or meta.get("format") != FORMAT:
        raise MaterialError("사본 형식이 다르다")
    if _checksum(list(members.items())) != meta.get("checksum"):
        raise MaterialError("사본 체크섬이 manifest 와 다르다 — 옮기다 깨졌다")
    manifest = Manifest(
        format=FORMAT, name=_str(meta.get("name"), "name"), exported_at=datetime.fromisoformat(_str(meta.get("exported_at"), "exported_at")),
        count=int(meta.get("count") or 0), checksum=str(meta["checksum"]),
    )
    items = []
    for member_name in sorted(members):
        if member_name.endswith(".json"):
            raw = json.loads(members[member_name])
            if not isinstance(raw, dict):
                raise MaterialError("사본 항목의 꼴이 다르다")
            items.append(_parse_item(raw, members.get(member_name[: -len(".json")] + ".src", b"")))
    if len(items) != manifest.count:
        raise MaterialError(f"사본 건수가 manifest({manifest.count})와 다르다({len(items)})")
    return MaterialSet(manifest, tuple(items), path)


# ── 강의실 채점 한 번 호출(실험 줄 `classroom_call`) ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassroomCallResult:
    """강의실 운영 채점과 같은 프롬프트·한 번 호출의 결과. `verdicts` 는 체크리스트 항목만(문법 검사 항목은 뺀다)."""

    status: str  # "scored" | "held"
    verdicts: tuple[ProductionVerdict, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    model_version: str = ""
    problem: str = ""
    prompt: str = ""


class ClassroomExperimentCall(Protocol):
    """`item` 을 `model` 로 한 번 채점한다. `api_key` 가 None 이면 흉내 어댑터, 아니면 그 키로 실제 벤더에 나간다."""

    def __call__(self, item: Item, *, model: str, api_key: str | None) -> ClassroomCallResult: ...


CLASSROOM_EXPERIMENT_CALL: Slot[ClassroomExperimentCall] = Slot("강의실 채점 한 번 호출(실험)", "classroom.apps")
