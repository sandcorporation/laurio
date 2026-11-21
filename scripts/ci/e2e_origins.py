"""e2e 프로젝트가 그 CI 조각이 띄우지 않는 앱 origin 에 닿는지 정적으로 잰다 (#1250).

CI 의 e2e 조각은 자기 프로젝트가 쓰는 Next 앱만 굽고 띄운다(`scripts/ci/e2e.sh` 의 `want_*`). 로컬은 세 앱이
다 떠 있어서, 시험이 다른 앱 주소에 기대도 CI 조각에서만 `ECONNREFUSED` 로 드러난다(스펙 PR #1247 붉음 3·4).

브라우저 없이 소스만 읽는다.
- 프로젝트·파일: `frontend/playwright.config.ts` 의 projects(name·testDir·testIgnore)
- 조각이 띄우는 앱: `scripts/ci/e2e.sh` 의 `<프로젝트>) want_<앱>=1 …;;` 줄
- 닿음: spec 의 맨 위 코드(test·beforeAll …)에서 시작해, 쓰는 이름을 따라 같은 파일과 import 한 `frontend/e2e/**`
  파일의 맨 위 선언(function·const·class)으로 내려간다. **파일이 아니라 선언 단위**다 — `lib/session.ts` 를
  import 해도 `establishOperatorSession` 만 쓰면 같은 파일의 `publicOrigin` 에는 닿지 않는다.
- 앱 표지: 그 앱의 e2e base URL 변수, 기본 포트(53000·53001·53002), `CODEMIT_*_WEB_PORT`, playwright 설정의
  baseURL 상수 이름. 주석은 지우고 본다. backend 직통(`CODEMIT_API_*`·58000)은 표지가 아니다 — 늘 뜬다.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
E2E = FRONTEND / "e2e"
CONFIG = FRONTEND / "playwright.config.ts"
SHARD_SCRIPT = ROOT / "scripts" / "ci" / "e2e.sh"

# 앱(= e2e.sh 의 want_<앱>) → 그 앱의 origin 에 닿는다는 표지.
APP_MARKERS: dict[str, tuple[str, ...]] = {
    "frontend": (r"\bCODEMIT_E2E_BASE_URL\b", r"\b53000\b", r"\bCODEMIT_WEB_PORT\b", r"\bpublicBaseURL\b"),
    "operator": (
        r"\bCODEMIT_OPERATOR_E2E_BASE_URL\b",
        r"\b53001\b",
        r"\bCODEMIT_OPERATOR_WEB_PORT\b",
        r"\boperatorBaseURL\b",
    ),
    "classroom": (
        r"\bCODEMIT_CLASSROOM_E2E_BASE_URL\b",
        r"\b53002\b",
        r"\bCODEMIT_CLASSROOM_WEB_PORT\b",
        r"\bclassroomBaseURL\b",
    ),
}

# 정당한 예외 — (frontend 기준 파일, 선언 이름 또는 맨 위 코드 "<top>", 앱): 까닭.
ALLOWED: dict[tuple[str, str, str], str] = {
    ("e2e/operator/feedback/feedback.spec.ts", "<top>", "frontend"): (
        "제보에 싣는 page_url 문자열일 뿐 그 주소를 열지 않는다"
    ),
}

TOP = "<top>"
_DECL = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+(?P<fn>\w+)|(?:const|let|var)\s+(?P<var>\w+)|class\s+(?P<cls>\w+))"
)
_TYPE_DECL = re.compile(r"^(?:export\s+)?(?:declare\s+)?(?:type|interface|enum)\s+\w+")
_IMPORT = re.compile(r"""^import\s+(?P<what>[\s\S]*?)\s+from\s+["'](?P<src>[^"']+)["'];?""", re.MULTILINE)
_SIDE_IMPORT = re.compile(r"""^import\s+["'][^"']+["'];?""", re.MULTILINE)
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def strip_comments(source: str) -> str:
    """`//`·`/* */` 주석을 지운다. 따옴표·템플릿 문자열 안의 `//`(URL)는 남긴다."""

    out: list[str] = []
    i, n = 0, len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(source[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end == -1 else end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            chunk = source[i : n if end == -1 else end + 2]
            out.append("\n" * chunk.count("\n"))
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@dataclass
class Module:
    path: str  # frontend 기준
    decls: dict[str, str] = field(default_factory=dict)  # 선언 이름 → 본문
    top: str = ""  # 선언이 아닌 맨 위 코드(test(...) 등)
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # 로컬 이름 → (파일, 원래 이름 | "*")


def _resolve(importer: str, spec: str, files: dict[str, str]) -> str | None:
    if not spec.startswith("."):
        return None
    base = (Path(importer).parent / spec).as_posix()
    parts: list[str] = []
    for part in base.split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in ("", "."):
            parts.append(part)
    base = "/".join(parts)
    for candidate in (base, f"{base}.ts", f"{base}.tsx", f"{base}/index.ts"):
        if candidate in files:
            return candidate
    return None


def parse(path: str, files: dict[str, str]) -> Module:
    source = strip_comments(files[path])
    module = Module(path)
    for match in _IMPORT.finditer(source):
        target = _resolve(path, match["src"], files)
        if target is None:
            continue
        what = match["what"].strip()
        star = re.match(r"\*\s+as\s+(\w+)", what)
        if star:
            module.imports[star[1]] = (target, "*")
            continue
        default = re.match(r"(\w+)\s*(?:,|$)", what)
        if default and default[1] != "type":
            module.imports[default[1]] = (target, "default")
        braces = re.search(r"\{([^}]*)\}", what)
        for item in braces[1].split(",") if braces else ():
            item = re.sub(r"^\s*type\s+", "", item).strip()
            if not item:
                continue
            original, _, local = item.partition(" as ")
            module.imports[(local or original).strip()] = (target, original.strip())
    body = _SIDE_IMPORT.sub("", _IMPORT.sub("", source))

    current: str | None = None
    chunks: dict[str | None, list[str]] = {None: []}
    for line in body.splitlines():
        if line and not line[0].isspace() and line[0] not in "})]":
            decl = _DECL.match(line)
            if decl:
                current = decl["fn"] or decl["var"] or decl["cls"]
                if line.startswith("export default"):
                    module.decls.setdefault("default", "")
                    chunks.setdefault("default", [])
                    chunks["default"].append(current)  # default → 실제 이름으로 잇는다
            elif _TYPE_DECL.match(line):
                current = "<type>"
            else:
                current = None
        chunks.setdefault(current, []).append(line)
    for name, lines in chunks.items():
        text = "\n".join(lines)
        if name is None:
            module.top = text
        elif name != "<type>":
            module.decls[name] = text
    return module


def project_files(files: dict[str, str], config: str) -> dict[str, list[str]]:
    """playwright 설정의 projects → 그 프로젝트의 spec 파일(frontend 기준)."""

    out: dict[str, list[str]] = {}
    for block in re.finditer(r"\{\s*name:\s*\"(?P<name>\w+)\"(?P<body>[\s\S]*?)\n\s*\}", config):
        test_dir = re.search(r"testDir:\s*\"\./([^\"]+)\"", block["body"])
        ignores = re.findall(r"\"\*\*/(\w+)/\*\*\"", block["body"])
        if not test_dir:
            continue
        prefix = test_dir[1].rstrip("/") + "/"
        out[block["name"]] = sorted(
            path
            for path in files
            if path.startswith(prefix)
            and path.endswith(".spec.ts")
            and not any(f"/{ignored}/" in f"/{path}" for ignored in ignores)
        )
    return out


def shard_apps(script: str) -> dict[str, set[str]]:
    """`scripts/ci/e2e.sh` 의 조각 정의 → 프로젝트가 띄우는 앱."""

    out: dict[str, set[str]] = {}
    for match in re.finditer(r"^\s*(\w+)\)\s*(want_\w+=1[^\n]*?);;", script, re.MULTILINE):
        out[match[1]] = set(re.findall(r"want_(\w+)=1", match[2]))
    return out


def _apps_in(text: str) -> set[str]:
    return {app for app, markers in APP_MARKERS.items() if any(re.search(m, text) for m in markers)}


@dataclass(frozen=True)
class Reach:
    project: str
    spec: str
    path: str  # 표지가 있는 파일
    decl: str  # 선언 이름 또는 <top>
    app: str

    def __str__(self) -> str:
        return (
            f"[{self.project}] {self.spec} → {self.path}:{self.decl} 가 {self.app} 앱 origin 에 닿는다"
            f" — CI {self.project} 조각은 그 앱을 띄우지 않는다"
        )


def reaches(files: dict[str, str], config: str, script: str) -> list[Reach]:
    """CI 조각이 띄우지 않는 앱에 닿는 곳(허용 목록 밖)."""

    modules: dict[str, Module] = {}

    def module(path: str) -> Module:
        if path not in modules:
            modules[path] = parse(path, files)
        return modules[path]

    shards = shard_apps(script)
    found: list[Reach] = []
    for project, specs in project_files(files, config).items():
        allowed = shards.get(project, set(APP_MARKERS))
        for spec in specs:
            seen: set[tuple[str, str]] = set()
            stack = [(spec, TOP)]
            while stack:
                path, name = stack.pop()
                if (path, name) in seen:
                    continue
                seen.add((path, name))
                mod = module(path)
                text = mod.top if name == TOP else mod.decls.get(name, "")
                for app in sorted(_apps_in(text) - allowed):
                    if (path, name, app) not in ALLOWED:
                        found.append(Reach(project, spec, path, name, app))
                for ident in set(_IDENT.findall(text)):
                    if ident in mod.decls and ident != name:
                        stack.append((path, ident))
                    elif ident in mod.imports:
                        target, original = mod.imports[ident]
                        if original == "*":
                            for member in re.findall(rf"\b{re.escape(ident)}\.(\w+)", text):
                                stack.append((target, member))
                        else:
                            stack.append((target, original))
                if name == "default":
                    stack.extend((path, real) for real in text.split() if real in mod.decls)
    return found


def load() -> tuple[dict[str, str], str, str]:
    files = {
        p.relative_to(FRONTEND).as_posix(): p.read_text(encoding="utf-8")
        for p in E2E.rglob("*.ts")
        if "node_modules" not in p.parts
    }
    return files, CONFIG.read_text(encoding="utf-8"), SHARD_SCRIPT.read_text(encoding="utf-8")


def main() -> int:
    found = reaches(*load())
    for reach in found:
        print(reach)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
