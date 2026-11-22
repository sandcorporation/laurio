"""기계 판정(#1283, 스펙 #1282, CONTEXT.md 「기계 판정」) — 체크리스트 항목에 붙은 기계 확인 규칙을 코드가
소스 트리에서 직접 확인한다. staged 채점 갈래(`classroom.scoring`, 운영 설정 `CLASSROOM_SCORING_PIPELINE`)만 쓴다.

규칙 꼴은 셋이다(정적 꼴만 — 빌드·시험 실행은 하지 않는다):

- `path_exists` — 경로·glob 에 맞는 파일이 있다.
- `file_contains` — 경로 glob 에 맞는 파일 안에 고정 문자열(`text`) 또는 정규식(`pattern`)이 있다.
- `config_value` — JSON·YAML·TOML·.env 파일에서 키(점으로 이은 경로) = 값.

**트리는 채점이 읽은 원본과 같은 바이트다**(`classroom.scoring._read_raw_source`). 다만 프롬프트 선별
(`core.source_selection`)의 예산·「코드 아님」 제외는 따르지 않는다 — 규칙은 강사가 경로를 콕 집어 쓰므로
`tests/`·`docs/` 를 빼면 「시험 폴더가 있다」 같은 규칙이 늘 미충족이 된다. 벤더·빌드 폴더(`node_modules/` 등,
`excluded_kind == "vendor"`)만 뺀다. zip 목록은 압축을 풀지 않고 읽으므로 경로 판정에는 크기 한도가 없다.

**판정은 셋이다**: 충족·미충족·판정 불가. 판정 불가(파일을 못 읽음 — 너무 큼·바이너리·파싱 실패, 정규식 시간
초과)는 부르는 쪽이 판단 항목처럼 모델에게 넘긴다. 미충족은 확인할 것을 **모두** 읽었는데 없을 때만이다.

**경로 glob**: `*` 은 한 경로 조각 안, `**` 는 여러 조각, `?` 는 글자 하나. 앞에서 몇 조각을 건너뛰어도
맞는다 — GitHub 저장소 zip 은 `<저장소>-<sha>/` 아래에 풀리므로 `src/app.py` 가 `repo-1a2b/src/app.py` 에 맞는다.

**정규식은 자식 프로세스에서 시간 한도 안에 돈다** — 파이썬 `re` 에는 시간 한도가 없고 스레드는 죽일 수 없다.
강사가 쓴 규칙이라도 파국적 되추적(`(a+)+$`) 하나가 grader 를 붙잡지 않게 한다. 길이는 저장할 때
(`classroom.schemas.MachineRuleIn`) 막는다.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, NotRequired, TypedDict

from core.source_selection import excluded_kind

#: 규칙 꼴 — 저장 스키마(`classroom.schemas`)와 MCP 입력이 같은 이름을 쓴다.
KIND_PATH_EXISTS = "path_exists"
KIND_FILE_CONTAINS = "file_contains"
KIND_CONFIG_VALUE = "config_value"
RULE_KINDS = (KIND_PATH_EXISTS, KIND_FILE_CONTAINS, KIND_CONFIG_VALUE)

#: 경로 glob·문자열·키·값 하나의 길이 상한(저장 스키마가 쓴다).
MAX_RULE_FIELD_CHARS = 200
#: 정규식 길이 상한.
MAX_PATTERN_CHARS = 200
#: 내용을 읽는 파일 하나의 상한(풀었을 때) — 넘으면 그 파일은 「판정 불가」다.
MAX_FILE_BYTES = 1_000_000
#: 정규식 하나가 쓸 수 있는 시간(초). 넘으면 「판정 불가」.
REGEX_TIMEOUT_SECONDS = 2.0

Verdict = Literal["met", "unmet", "undetermined"]
MET: Verdict = "met"
UNMET: Verdict = "unmet"
UNDETERMINED: Verdict = "undetermined"


class MachineRule(TypedDict):
    """`ChecklistItem.machine_rule` 에 저장된 모양 — 저장 스키마가 검증한 것만 들어온다."""

    kind: str
    path: str
    text: NotRequired[str | None]
    pattern: NotRequired[str | None]
    key: NotRequired[str]
    value: NotRequired[str]


@dataclass(frozen=True)
class MachineVerdict:
    verdict: Verdict
    #: 근거 — `경로` 또는 `경로:줄`. 미충족·판정 불가는 비어 있을 수 있다.
    evidence: tuple[str, ...]
    #: 참여자·강사 화면에 그대로 나가는 근거 문장(한국어).
    reasoning: str

    @property
    def decided(self) -> bool:
        return self.verdict != UNDETERMINED


@dataclass(frozen=True)
class _Entry:
    path: str
    size: int


class MachineTree:
    """채점 원본 바이트 위의 파일 트리 — 목록은 바로, 내용은 물을 때만(크기 상한 안에서) 읽는다."""

    def __init__(self, raw: bytes) -> None:
        self._archive: zipfile.ZipFile | None = None
        self._raw = raw
        entries: list[_Entry] = []
        try:
            self._archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            if raw:
                entries.append(_Entry(path="source", size=len(raw)))
        else:
            for info in self._archive.infolist():
                if info.is_dir() or excluded_kind(info.filename) == "vendor":
                    continue
                entries.append(_Entry(path=info.filename, size=info.file_size))
        self.entries: tuple[_Entry, ...] = tuple(sorted(entries, key=lambda e: e.path))
        self._texts: dict[str, str | None] = {}

    def matching(self, glob: str) -> list[_Entry]:
        regex = glob_regex(glob)
        return [e for e in self.entries if regex.match(e.path)]

    def text(self, entry: _Entry) -> str | None:
        """파일 내용(UTF-8) — 상한을 넘거나 바이너리·깨진 UTF-8 이면 None(「판정 불가」)."""

        if entry.path in self._texts:
            return self._texts[entry.path]
        text: str | None = None
        if entry.size <= MAX_FILE_BYTES:
            data = self._read(entry)
            if data is not None and len(data) <= MAX_FILE_BYTES and b"\x00" not in data:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = None
        self._texts[entry.path] = text
        return text

    def _read(self, entry: _Entry) -> bytes | None:
        if self._archive is None:
            return self._raw
        try:
            with self._archive.open(entry.path) as member:
                # 선언된 크기를 믿지 않는다 — 상한보다 한 바이트 더 읽어 넘침을 안다(zip bomb).
                return member.read(MAX_FILE_BYTES + 1)
        except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError):
            return None


def glob_regex(glob: str) -> re.Pattern[str]:
    """경로 glob → 정규식. 앞의 조각을 몇 개 건너뛰어도 맞는다(모듈 머리말)."""

    pattern = glob.strip().lstrip("/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:[^/]+/)*")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile(r"(?:.*/)?" + "".join(out) + r"\Z", re.DOTALL)


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _quote(value: str) -> str:
    return f"`{value}`"


# --- 정규식(자식 프로세스) --------------------------------------------------------

_REGEX_CHILD = r"""
import json, re, sys
data = json.loads(sys.stdin.read())
regex = re.compile(data["pattern"], re.MULTILINE)
for path, content in data["files"]:
    m = regex.search(content)
    if m:
        print(json.dumps([path, content.count("\n", 0, m.start()) + 1]))
        break
else:
    print("null")
"""


class _RegexTimeout(Exception):
    pass


def _regex_search(pattern: str, files: list[tuple[str, str]]) -> tuple[str, int] | None:
    """처음 맞는 (경로, 줄) — 없으면 None. 시간 한도를 넘거나 자식이 실패하면 `_RegexTimeout`."""

    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _REGEX_CHILD],
            input=json.dumps({"pattern": pattern, "files": files}).encode("utf-8"),
            capture_output=True,
            timeout=REGEX_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _RegexTimeout from exc
    if done.returncode != 0:
        raise _RegexTimeout
    found = json.loads(done.stdout.decode("utf-8") or "null")
    if found is None:
        return None
    return str(found[0]), int(found[1])


# --- 설정 파일 -------------------------------------------------------------------

#: 설정 값으로 읽은 것의 모양 — 파서가 주는 그대로.
type ConfigValue = str | int | float | bool | None | list[ConfigValue] | dict[str, ConfigValue]


class _ConfigUnreadable(Exception):
    pass


def _parse_config(path: str, text: str) -> dict[str, ConfigValue]:
    name = path.lower().rsplit("/", 1)[-1]
    try:
        if name.endswith(".json"):
            parsed = json.loads(text)
        elif name.endswith((".yaml", ".yml")):
            import yaml  # uvicorn[standard] 가 끌어오는 의존성 — 없으면 판정 불가

            parsed = yaml.safe_load(text)
        elif name.endswith(".toml"):
            parsed = tomllib.loads(text)
        elif name == ".env" or name.startswith(".env.") or name.endswith(".env"):
            parsed = _parse_dotenv(text)
        else:
            raise _ConfigUnreadable(path)
    except _ConfigUnreadable:
        raise
    except Exception as exc:  # 파서마다 예외가 다르다(json·yaml·toml) — 모두 「못 읽음」이다.
        raise _ConfigUnreadable(path) from exc
    if not isinstance(parsed, dict):
        raise _ConfigUnreadable(path)
    return parsed


def _parse_dotenv(text: str) -> dict[str, ConfigValue]:
    values: dict[str, ConfigValue] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


_MISSING = object()


def _lookup(config: dict[str, ConfigValue], key: str) -> ConfigValue | object:
    if key in config:
        return config[key]
    node: ConfigValue | object = config
    for part in key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _as_text(value: ConfigValue | object) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


# --- 판정 ------------------------------------------------------------------------


def judge(rule: MachineRule, tree: MachineTree) -> MachineVerdict:
    """규칙 하나를 트리에서 확인한다. 순수 함수다(정규식 자식 프로세스만 밖으로 나간다)."""

    kind = rule["kind"]
    if kind == KIND_PATH_EXISTS:
        return _judge_path_exists(rule, tree)
    if kind == KIND_FILE_CONTAINS:
        return _judge_file_contains(rule, tree)
    if kind == KIND_CONFIG_VALUE:
        return _judge_config_value(rule, tree)
    return MachineVerdict(UNDETERMINED, (), f"기계 판정 — 알 수 없는 규칙 꼴({kind})이라 판정하지 못했다.")


def _judge_path_exists(rule: MachineRule, tree: MachineTree) -> MachineVerdict:
    found = tree.matching(rule["path"])
    if found:
        return MachineVerdict(
            MET, (found[0].path,), f"기계 판정 — 경로 {_quote(rule['path'])} 에 맞는 파일 {_quote(found[0].path)} 이 있다."
        )
    return MachineVerdict(UNMET, (), f"기계 판정 — 경로 {_quote(rule['path'])} 에 맞는 파일이 소스에 없다.")


def _judge_file_contains(rule: MachineRule, tree: MachineTree) -> MachineVerdict:
    candidates = tree.matching(rule["path"])
    if not candidates:
        return MachineVerdict(UNMET, (), f"기계 판정 — 경로 {_quote(rule['path'])} 에 맞는 파일이 소스에 없다.")
    readable: list[tuple[str, str]] = []
    unreadable = 0
    for entry in candidates:
        text = tree.text(entry)
        if text is None:
            unreadable += 1
        else:
            readable.append((entry.path, text))
    needle = rule.get("text")
    pattern = rule.get("pattern")
    what = _quote(needle) if needle else f"정규식 {_quote(pattern or '')}"
    hit: tuple[str, int] | None = None
    if needle:
        for path, text in readable:
            index = text.find(needle)
            if index >= 0:
                hit = (path, _line_of(text, index))
                break
    elif pattern:
        try:
            hit = _regex_search(pattern, readable)
        except _RegexTimeout:
            return MachineVerdict(
                UNDETERMINED, (), f"기계 판정 — {what} 확인이 시간 한도를 넘어 판정하지 못했다."
            )
    if hit is not None:
        evidence = f"{hit[0]}:{hit[1]}"
        return MachineVerdict(MET, (evidence,), f"기계 판정 — {_quote(evidence)} 에서 {what} 를 확인했다.")
    if unreadable:
        return MachineVerdict(
            UNDETERMINED, (), f"기계 판정 — {_quote(rule['path'])} 에 맞는 파일 {unreadable}개를 읽지 못해 판정하지 못했다."
        )
    return MachineVerdict(
        UNMET,
        tuple(path for path, _ in readable[:5]),
        f"기계 판정 — {_quote(rule['path'])} 에 맞는 파일에서 {what} 를 찾지 못했다.",
    )


def _judge_config_value(rule: MachineRule, tree: MachineTree) -> MachineVerdict:
    key, expected = rule.get("key", ""), rule.get("value", "").strip()
    candidates = tree.matching(rule["path"])
    if not candidates:
        return MachineVerdict(UNMET, (), f"기계 판정 — 경로 {_quote(rule['path'])} 에 맞는 설정 파일이 소스에 없다.")
    unreadable = 0
    seen: list[str] = []
    for entry in candidates:
        text = tree.text(entry)
        if text is None:
            unreadable += 1
            continue
        try:
            config = _parse_config(entry.path, text)
        except _ConfigUnreadable:
            unreadable += 1
            continue
        actual = _as_text(_lookup(config, key))
        if actual is not None and actual.strip() == expected:
            return MachineVerdict(
                MET, (entry.path,), f"기계 판정 — {_quote(entry.path)} 에서 {_quote(key)} = {_quote(expected)} 를 확인했다."
            )
        seen.append(entry.path)
    if unreadable:
        return MachineVerdict(
            UNDETERMINED, (), f"기계 판정 — {_quote(rule['path'])} 에 맞는 설정 파일 {unreadable}개를 읽지 못해 판정하지 못했다."
        )
    return MachineVerdict(
        UNMET,
        tuple(seen[:5]),
        f"기계 판정 — {_quote(rule['path'])} 에서 {_quote(key)} = {_quote(expected)} 를 찾지 못했다.",
    )


def judge_items(rules: Iterable[tuple[int, MachineRule]], raw: bytes) -> dict[int, MachineVerdict]:
    """(항목 id, 규칙) 들을 한 트리에서 판정한다 — 규칙 없는 항목은 부르는 쪽이 넣지 않는다."""

    pairs = list(rules)
    if not pairs:
        return {}
    tree = MachineTree(raw)
    return {item_id: judge(rule, tree) for item_id, rule in pairs}
