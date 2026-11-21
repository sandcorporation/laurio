"""e2e 프로젝트가 닿는 앱 origin(#1250) — CI 조각이 띄우지 않는 앱에 닿으면 붉다.

`scripts/ci/e2e.sh` 의 조각은 자기 프로젝트 앱(과 그 시험이 기대는 앱)만 띄운다. 로컬은 세 앱이 다 떠 있어 통과하고
CI 조각에서만 드러나던 실수(#1247 붉음 3·4)를 브라우저 없이 정적으로 잡는다.

프로젝트마다 `playwright.config.ts` 의 testDir 아래 spec 에서 시작해 상대 import 를 따라가며(`frontend/e2e/**`),
**실제로 쓰이는 선언**(스펙 파일 전체, 가져온 이름이 가리키는 최상위 선언과 그 안에서 부르는 같은 파일의 선언)만 읽는다 —
`lib/session.ts` 처럼 한 파일에 여러 앱의 origin 이 있어도, 그 프로젝트가 쓰지 않는 것은 보지 않는다.
허용: 그 프로젝트의 앱, `e2e.sh` 의 조각이 같이 띄우는 앱, backend 직통(앱 origin 이 아니다).
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
E2E_SH = "scripts/ci/e2e.sh"
CONFIG = "frontend/playwright.config.ts"
E2E_DIR = "frontend/e2e"

# 앱 origin 을 가리키는 표식 — 환경변수 이름과 포트(오프셋 계산 포함).
ENV_APP = {
    "CODEMIT_E2E_BASE_URL": "public",
    "CODEMIT_OPERATOR_E2E_BASE_URL": "operator",
    "CODEMIT_CLASSROOM_E2E_BASE_URL": "classroom",
    "CODEMIT_WEB_PORT": "public",
    "CODEMIT_OPERATOR_WEB_PORT": "operator",
    "CODEMIT_CLASSROOM_WEB_PORT": "classroom",
}
PORT_APP = {"53000": "public", "53001": "operator", "53002": "classroom"}
MARK = re.compile(
    r"\b(" + "|".join(sorted(ENV_APP, key=len, reverse=True)) + r")\b"
    r"|(?<![\w.])(53000|53001|53002)(?!\d)"
)

# 정당한 예외 — (e2e 폴더 기준 파일, 앱) → 이유. 연결하는 것이 아니라 글자로만 있는 경우다.
ALLOWED: dict[tuple[str, str], str] = {
    ("operator/feedback/feedback.spec.ts", "public"): "제보 본문의 page_url 문자열이다 — 그 주소로 연결하지 않는다",
}

DECL = re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)")
IMPORT = re.compile(r"import\s+(?:type\s+)?([^;]*?)\s+from\s+[\"']([^\"']+)[\"']|import\s+[\"']([^\"']+)[\"']", re.S)
IDENT = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class Chunk:
    name: str  # 최상위 선언 이름, 앞부분(import 등)은 ""
    text: str
    start: int  # 1부터


def chunks_of(text: str) -> list[Chunk]:
    out: list[Chunk] = [Chunk("", "", 1)]
    for number, line in enumerate(text.splitlines(), 1):
        found = DECL.match(line)
        if found:
            out.append(Chunk(found.group(1), "", number))
        out[-1].text += line + "\n"
    return out


def resolve(root: Path, origin: Path, spec: str) -> Path | None:
    if not spec.startswith("."):
        return None
    base = (origin.parent / spec).resolve()
    for candidate in (base, base.with_suffix(".ts"), Path(f"{base}.ts"), base / "index.ts"):
        if candidate.is_file() and candidate.suffix == ".ts":
            return candidate
    return None


def parse_names(clause: str) -> set[str] | None:
    """가져온 이름. 이름 목록이 아니면(`* as`·기본값·부수 효과) None = 파일 전체."""
    clause = clause.strip()
    if "{" not in clause or clause.startswith("*") or not clause.startswith("{"):
        return None
    names = set()
    for part in clause[clause.index("{") + 1 : clause.rindex("}")].split(","):
        part = re.sub(r"^type\s+", "", part.strip())
        if part:
            names.add(part.split(" as ")[0].strip())
    return names


def reachable_marks(root: Path, entry: Path) -> list[tuple[Path, int, str]]:
    """entry 에서 쓰이는 선언들의 앱 표식 — (파일, 줄, 앱)."""
    found: list[tuple[Path, int, str]] = []
    seen: dict[Path, set[str] | None] = {}
    todo: list[tuple[Path, set[str] | None]] = [(entry, None)]
    while todo:
        path, wanted = todo.pop()
        text = path.read_text(encoding="utf-8")
        chunks = chunks_of(text)
        by_name = {c.name: c for c in chunks if c.name}
        # 이 파일에서 읽을 선언들을 닫는다: 가져온 이름 + 그 안에서 부르는 같은 파일의 선언.
        use = set(by_name) if wanted is None else {n for n in wanted if n in by_name}
        previous = seen.get(path, set())
        if path in seen and (previous is None or (wanted is not None and use <= previous)):
            continue
        seen[path] = None if wanted is None else (previous | use)
        closure = set(use)
        stack = list(use)
        while stack:
            for ident in IDENT.findall(by_name[stack.pop()].text):
                if ident in by_name and ident not in closure:
                    closure.add(ident)
                    stack.append(ident)
        for chunk in chunks:
            if chunk.name and chunk.name not in closure:
                continue
            for offset, line in enumerate(chunk.text.splitlines()):
                if chunk.name == "" and not MARK.search(line):
                    continue
                if line.lstrip().startswith(("//", "*", "/*")):
                    continue
                for mark in MARK.finditer(line):
                    app = ENV_APP.get(mark.group(1) or "") or PORT_APP[mark.group(2)]
                    found.append((path, chunk.start + offset, app))
        for imported in IMPORT.finditer("".join(c.text for c in chunks if c.name == "" or c.name in closure)):
            clause, spec, bare = imported.group(1), imported.group(2), imported.group(3)
            target = resolve(root, path, spec or bare)
            if target is None:
                continue
            todo.append((target, parse_names(clause) if clause is not None else None))
    return found


def project_dirs(root: Path) -> dict[str, str]:
    """playwright projects 의 {이름: testDir(e2e 기준)}."""
    text = (root / CONFIG).read_text(encoding="utf-8")
    pairs = re.findall(r"name:\s*\"(\w+)\",\s*testDir:\s*\"\./e2e/?([^\"]*)\"", text)
    return {name: directory for name, directory in pairs}


def served_by_shard(root: Path) -> dict[str, set[str]]:
    """e2e.sh 의 조각 정의 — 프로젝트별로 같이 띄우는 앱(자기 앱 포함)."""
    text = (root / E2E_SH).read_text(encoding="utf-8")
    flag_app = {"want_frontend": "public", "want_operator": "operator", "want_classroom": "classroom"}
    out: dict[str, set[str]] = {}
    for target, body in re.findall(r"^\s+(public|operator|classroom)\)\s*([^\n]*?)\s*;;", text, re.M):
        out[target] = {flag_app[flag] for flag in re.findall(r"(want_\w+)=1", body)}
    return out


def specs_of(root: Path) -> dict[str, list[Path]]:
    """프로젝트별 spec — 가장 깊은 testDir 이 주인이다."""
    dirs = project_dirs(root)
    base = root / E2E_DIR
    out: dict[str, list[Path]] = {name: [] for name in dirs}
    for spec in sorted(base.rglob("*.spec.ts")):
        rel = spec.relative_to(base).as_posix()
        owner = max(
            (n for n, d in dirs.items() if d == "" or rel.startswith(d.rstrip("/") + "/")),
            key=lambda n: len(dirs[n]),
        )
        out[owner].append(spec)
    return out


def violations(root: Path) -> list[str]:
    served = served_by_shard(root)
    base = root / E2E_DIR
    bad: list[str] = []
    for project, specs in specs_of(root).items():
        allowed = served.get(project, {project}) | {project}
        for spec in specs:
            for path, line, app in reachable_marks(root, spec):
                if app in allowed:
                    continue
                rel = path.relative_to(base).as_posix()
                if (rel, app) in ALLOWED:
                    continue
                bad.append(
                    f"{project} 프로젝트의 {spec.relative_to(base).as_posix()} 가 {rel}:{line} 에서 {app} 앱 origin 에 닿는다 — "
                    f"CI 조각은 {sorted(allowed)} 만 띄운다(backend 직통을 쓰거나 {E2E_SH} 의 조각에 앱을 더한다)"
                )
    return sorted(set(bad))


class MainIsClean(unittest.TestCase):
    def test_projects_and_shards_are_read(self) -> None:
        self.assertEqual(set(project_dirs(ROOT)), {"public", "operator", "classroom"})
        self.assertEqual(served_by_shard(ROOT)["classroom"], {"classroom", "public"})
        self.assertEqual(served_by_shard(ROOT)["operator"], {"operator"})
        self.assertEqual(served_by_shard(ROOT)["public"], {"public"})

    def test_no_project_reaches_an_app_its_shard_does_not_serve(self) -> None:
        self.assertEqual(violations(ROOT), [])

    def test_every_allowance_is_still_needed(self) -> None:
        base = ROOT / E2E_DIR
        served = served_by_shard(ROOT)
        used = set()
        for project, specs in specs_of(ROOT).items():
            allowed = served.get(project, {project}) | {project}
            for spec in specs:
                for path, _, app in reachable_marks(ROOT, spec):
                    if app not in allowed:
                        used.add((path.relative_to(base).as_posix(), app))
        self.assertEqual(set(ALLOWED), used, "쓰이지 않는 허용 항목은 지운다")


class Fixtures(unittest.TestCase):
    """#1247 에서 붉었던 두 꼴 — 고치기 전 그대로."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        for rel, content in {
            "scripts/ci/e2e.sh": (ROOT / E2E_SH).read_text(encoding="utf-8"),
            CONFIG: (ROOT / CONFIG).read_text(encoding="utf-8"),
            f"{E2E_DIR}/lib/session.ts": (ROOT / E2E_DIR / "lib/session.ts").read_text(encoding="utf-8"),
        }.items():
            self.put(rel, content)

    def put(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_operator_spec_using_the_public_origin_helper(self) -> None:
        # d4f415f4 이전: 운영자 조각의 시험이 publicOrigin() 으로 공개 앱(53000)을 쳤다.
        self.put(
            f"{E2E_DIR}/operator/feedback/feedback.spec.ts",
            'import { test } from "@playwright/test";\n'
            'import { establishOperatorSession, publicOrigin } from "../../lib/session";\n'
            'test("x", async () => { const origin = publicOrigin(); await establishOperatorSession(origin); });\n',
        )
        got = violations(self.root)
        self.assertEqual(len(got), 1, got)
        self.assertIn("operator 프로젝트의 operator/feedback/feedback.spec.ts", got[0])
        self.assertIn("public 앱 origin", got[0])

    def test_public_spec_whose_helper_reaches_the_operator_app(self) -> None:
        # 076d22b7 이전: 공개·강의실 조각의 권한 도우미가 운영자 앱(53001)에 로그인했다.
        self.put(
            f"{E2E_DIR}/lib/feedback-permission.ts",
            "function operatorOrigin(): string {\n"
            '  return new URL(process.env.CODEMIT_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001").origin;\n'
            "}\n"
            "export async function setFeedbackPermission(email: string): Promise<void> {\n"
            "  const origin = operatorOrigin();\n"
            "}\n",
        )
        for folder in ("feedback", "classroom"):
            self.put(
                f"{E2E_DIR}/{folder}/a.spec.ts",
                'import { test } from "@playwright/test";\n'
                'import { setFeedbackPermission } from "../lib/feedback-permission";\n'
                'test("x", async () => { await setFeedbackPermission("a@b.c"); });\n',
            )
        got = violations(self.root)
        self.assertEqual(len(got), 2, got)
        self.assertTrue(all("operator 앱 origin" in line for line in got), got)
        self.assertTrue(any(line.startswith("public 프로젝트") for line in got))
        self.assertTrue(any(line.startswith("classroom 프로젝트") for line in got))

    def test_backend_direct_and_unused_helpers_pass(self) -> None:
        self.put(
            f"{E2E_DIR}/feedback/a.spec.ts",
            'import { test } from "@playwright/test";\n'
            'import { publicOrigin } from "../lib/session";\n'
            'const api = process.env.CODEMIT_API_BASE_URL ?? "http://127.0.0.1:58000";\n'
            'test("x", async () => { publicOrigin(); fetch(api); });\n',
        )
        self.assertEqual(violations(self.root), [])

    def test_classroom_may_reach_the_public_app_its_shard_serves(self) -> None:
        self.put(
            f"{E2E_DIR}/classroom/a.spec.ts",
            'import { test } from "@playwright/test";\n'
            'import { establishDeveloperSession, publicOrigin } from "../lib/session";\n'
            'test("x", async () => { publicOrigin(); });\n',
        )
        self.assertEqual(violations(self.root), [])

    def test_port_literals_are_marks(self) -> None:
        self.put(
            f"{E2E_DIR}/classroom/b.spec.ts",
            'import { test } from "@playwright/test";\n'
            'test("x", async () => { await fetch("http://127.0.0.1:53001/login"); });\n',
        )
        got = violations(self.root)
        self.assertEqual(len(got), 1, got)
        self.assertIn("operator 앱 origin", got[0])


if __name__ == "__main__":
    sys.exit(unittest.main())
