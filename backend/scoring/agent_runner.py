"""에이전트 채점 실행기(#999) — `agent-grader` 컨테이너 안에서 도는 실행 하나의 틀과, 그것을 부르는 쪽의 계약.

공모전 채점을 「CLI 에이전트(Claude Code 또는 Codex)가 마감 커밋의 저장소를 읽기 전용으로 읽고 판정」으로
바꿀 자리다. 이 모듈은 **틀까지만** 한다 — 실행 토큰 발급(`core.agent_run_tokens`, #998)과 스트림 해석·받아들이는
조건(#1000)은 부르는 쪽 몫이다. 부르는 쪽이 없으면 이 서비스는 요청을 기다리기만 하고 아무 데도 나가지 않는다.

실행 하나(`execute_run`):
  1. 박제본 zip 을 `/work/<run>/repo` 에 경로 검사 뒤 푼다(절대 경로·`..`·링크는 들이지 않는다). 최상위 폴더가
     하나뿐이면(GitHub zipball 의 `<owner>-<repo>-<sha>/`) 벗기고, 벗긴 접두사를 결과에 돌려준다. 다 풀면 읽기 전용.
  2. 빈 `HOME=/work/<run>/home`, 키 자리에 실행 토큰, base_url 은 `llm-proxy`. env 는 처음부터 새로 짓는다 —
     이 프로세스의 env 를 물려주지 않는다.
  3. 고정 인자(`claude_argv`·`codex_argv`)로 CLI 를 띄운다. 프롬프트는 stdin 으로 준다(argv 길이 한도·`ps` 노출).
  4. 끝나면(정상·실패·시간 초과 모두) `/work/<run>` 을 지운다. 실행당 `RUN_TIMEOUT_SECONDS` 상한.

이 파일은 이미지에 그대로 복사돼 `python3 agent_runner.py serve` 로 돈다 — **표준 라이브러리만** 쓴다(Django 를
들이지 않는다, `test_agent_runner.py` 가 못 박는다). 부르는 쪽(#1000)은 `request_run` 을 쓴다.

Codex 의 셸 샌드박스(`--sandbox read-only`)는 bubblewrap 이 사용자 네임스페이스를 만들어야 돈다. docker 기본
seccomp 는 그 syscall 을 막아 「No permissions to create a new namespace」로 모든 명령이 실패한다(2026-11-20 실측,
arm64). 그래서 이 서비스만 기본 프로필에 bwrap 몫 다섯(`clone`(CLONE_NEWUSER)·`unshare`·`mount`·`umount2`·`pivot_root`)을
더한 `docker/agent-grader-seccomp.json` 을 쓰고, 능력 전부 제거·no-new-privileges·읽기 전용 루트·비루트·내부 네트워크로
묶는다(`docker/compose.prod.yaml` 의 `agent-grader`). Codex 는 `TMPDIR` 와 상관없이 `/tmp` 에 쓴다 —
`/tmp` 도 tmpfs 다.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Literal, NotRequired, TypedDict

try:  # backend(Django) 에서는 `scoring` 패키지의 모듈이다
    from scoring import selfloop
except ImportError:  # 실행기 이미지 — /app/selfloop.py 가 옆에 있다(agent-grader.Dockerfile)
    import selfloop  # type: ignore[no-redef]

# ── 고정값 — 바꾸면 `docker/agent-grader.Dockerfile` 의 ARG 와 시험이 같이 바뀐다 ──────────────────────────
CLAUDE_CODE_VERSION = "2.1.328"
CODEX_VERSION = "0.170.0"
MAX_CONCURRENT_RUNS = 2
RUN_TIMEOUT_SECONDS = 600
SERVICE_PORT = 8003
DEFAULT_SERVICE_URL = f"http://agent-grader:{SERVICE_PORT}"
DEFAULT_PROXY_BASE_URL = "http://llm-proxy:8002"  # #998 — `agent` 네트워크 안의 프록시

# 박제본 상한. 다운로드 상한(#996 의 100MB)과 같은 크기의 압축본을 받고, 풀린 크기는 tmpfs·메모리 한도
# 안에 둔다(동시 2 × 풀린 것 + CLI 둘). 넘으면 실행하지 않고 413/400 으로 돌려준다.
MAX_REPO_ZIP_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_ZIP_ENTRIES = 50_000
MAX_SPEC_BYTES = 1024 * 1024
# 돌려주는 CLI 출력의 상한 — stream-json 은 도구 결과(읽은 파일 본문)까지 실어 커질 수 있다.
MAX_STDOUT_BYTES = 16 * 1024 * 1024
STDERR_TAIL_BYTES = 8 * 1024

CLI_PATH = "/usr/local/bin:/usr/bin:/bin"
CLAUDE_TOOLS = ("Read", "Grep", "Glob")
CODEX_PROVIDER = "codemit"
CODEX_TOKEN_ENV = "CODEMIT_AGENT_RUN_TOKEN"
# 채점에 쓸 일이 없고 밖으로 나가거나 HOME 밖을 읽는 기능 — 0.170.0 의 `codex features list` 이름.
CODEX_DISABLED_FEATURES = (
    "hooks",
    "plugins",
    "remote_plugin",
    "plugin_sharing",
    "apps",
    "goals",
    "image_generation",
    "in_app_updates",
    "skill_mcp_dependency_install",
    "skill_search",
    "shell_snapshot",
)

# 실행기 컨테이너에 있으면 안 되는 것 — `selfcheck` 가 본다. 진짜 키는 llm-proxy 에만 있다.
FORBIDDEN_ENV_MARKERS = ("API_KEY", "AUTH_TOKEN", "SECRET", "PASSWORD", "ACCESS_KEY")
FORBIDDEN_ENV_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPEN_AI_API_KEY", "CODEX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
CREDENTIAL_PATHS = (
    "~/.claude.json",
    "~/.claude/.credentials.json",
    "~/.codex/auth.json",
    "~/.config/claude",
    "~/.netrc",
    "~/.aws/credentials",
    "~/.config/gcloud",
    "~/.docker/config.json",
)

Vendor = Literal["anthropic", "openai"]
VENDORS: tuple[Vendor, ...] = ("anthropic", "openai")
#: 실행 갈래 — `cli` 는 Claude Code·Codex, `selfloop` 은 우리 루프(#1245, `selfloop.py`).
Mode = Literal["cli", "selfloop"]
MODES: tuple[Mode, ...] = ("cli", "selfloop")
MAX_SELFLOOP_REQUIREMENTS = 100


class RunSpec(TypedDict):
    """실행 하나의 요청. `run_token` 은 `core.agent_run_tokens.issue_run_token` 이 낸 일회용 토큰이다."""

    vendor: Vendor
    model: str
    prompt: str
    output_schema: dict[str, object]
    run_token: str
    max_budget_usd: float
    timeout_seconds: NotRequired[int]
    #: 없으면 `cli`. `selfloop` 이면 `prompt` 는 하위 루프의 지침(system)이고 `requirements` 가 판정할 목록이다 —
    #: `output_schema` 는 받지만 쓰지 않는다(판정 꼴은 루프의 제출 도구가 정한다).
    mode: NotRequired[Mode]
    requirements: NotRequired[list[selfloop.Requirement]]


class RunResult(TypedDict):
    run_id: str
    vendor: Vendor
    cli_version: str
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    repo_root_prefix: str
    stdout: str
    stdout_truncated: bool
    stderr_tail: str


class RunRejected(Exception):
    """요청이 실행 전에 거절됐다 — 사유(`reason`)를 그대로 돌려준다. 다시 보내도 같다."""

    def __init__(self, reason: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class AgentGraderBusy(Exception):
    """동시 실행이 찼다(503) — 부르는 쪽이 나중에 다시 보낸다."""


class AgentGraderError(Exception):
    """실행기에 닿지 못했거나 알 수 없는 응답 — 일시 실패로 센다."""


# ── 고정 인자 ─────────────────────────────────────────────────────────────────────────────────────────────


def claude_argv(*, model: str, output_schema_json: str, max_budget_usd: float) -> list[str]:
    """Claude Code 한 번. `--bare` 는 쓰지 않는다 — init 도구가 Read 하나로 줄어 디렉터리를 못 뒤진다(#992)."""

    tools = ",".join(CLAUDE_TOOLS)
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--safe-mode",
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--tools",
        tools,
        "--allowedTools",
        tools,
        "--json-schema",
        output_schema_json,
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        f"{max_budget_usd:.2f}",
    ]


def _toml_str(value: str) -> str:
    return json.dumps(value)  # TOML 기본 문자열과 JSON 문자열은 이 범위(인쇄 가능 ASCII)에서 같다


def codex_argv(*, model: str, output_schema_path: str, repo_dir: str, proxy_base_url: str) -> list[str]:
    """Codex 한 번. 내장 `openai` provider 는 덮어쓸 수 없어 이름이 다른 사용자 provider 를 둔다(#992).
    셸은 env 를 하나도 물려받지 않는다(`inherit="none"`) — 실행 토큰도 셸에서 보이지 않는다."""

    provider = f"model_providers.{CODEX_PROVIDER}"
    config = [
        f"model_provider={_toml_str(CODEX_PROVIDER)}",
        f"{provider}.name={_toml_str(CODEX_PROVIDER)}",
        f"{provider}.base_url={_toml_str(proxy_base_url.rstrip('/') + '/v1')}",
        f"{provider}.env_key={_toml_str(CODEX_TOKEN_ENV)}",
        f"{provider}.wire_api={_toml_str('responses')}",
        f"{provider}.request_max_retries=0",
        f"{provider}.stream_max_retries=0",
        f"shell_environment_policy.inherit={_toml_str('none')}",
        # 셸에는 키 없는 고정 PATH 하나만 — 없으면 rg·sed 조차 못 찾는다(inherit="none" 은 PATH 까지 비운다).
        f"shell_environment_policy.set.PATH={_toml_str(CLI_PATH)}",
        "project_doc_max_bytes=0",
        f"web_search={_toml_str('disabled')}",
    ]
    argv = [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--output-schema",
        output_schema_path,
        "--json",
        "--model",
        model,
        "--cd",
        repo_dir,
    ]
    for item in config:
        argv += ["-c", item]
    for feature in CODEX_DISABLED_FEATURES:
        argv += ["--disable", feature]
    argv.append("-")  # 프롬프트는 stdin
    return argv


def run_env(
    *, vendor: Vendor, home: Path, tmp: Path, run_token: str, proxy_base_url: str, path: str = CLI_PATH
) -> dict[str, str]:
    """CLI 에 줄 env — 이 프로세스의 env 는 하나도 물려주지 않는다. 키 자리에는 실행 토큰만."""

    env = {
        "PATH": path,
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
    }
    if vendor == "anthropic":
        env |= {
            "ANTHROPIC_API_KEY": run_token,
            "ANTHROPIC_BASE_URL": proxy_base_url.rstrip("/"),
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_ERROR_REPORTING": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    else:
        env |= {"CODEX_HOME": str(home / ".codex"), CODEX_TOKEN_ENV: run_token}
    return env


# ── 박제본 풀기 ───────────────────────────────────────────────────────────────────────────────────────────


def _safe_member_path(name: str) -> PurePosixPath | None:
    """zip 항목 이름 → 상대 경로. 들이면 안 되는 이름이면 RunRejected, 디렉터리 표시뿐이면 None."""

    if "\x00" in name or "\\" in name:
        raise RunRejected("repo_zip_bad_path")
    path = PurePosixPath(name)
    if path.is_absolute() or (path.parts and ":" in path.parts[0]) or ".." in path.parts:
        raise RunRejected("repo_zip_bad_path")
    parts = [p for p in path.parts if p not in ("", ".")]
    return PurePosixPath(*parts) if parts else None


def _common_root(paths: list[PurePosixPath], dirs: set[PurePosixPath]) -> str:
    """모든 항목이 같은 최상위 폴더 하나 아래에 있으면 그 이름(GitHub zipball 꼴), 아니면 ""."""

    tops = {p.parts[0] for p in paths}
    if len(tops) != 1:
        return ""
    (top,) = tops
    nested = [p for p in paths if len(p.parts) > 1]
    if not nested or any(len(p.parts) == 1 and p not in dirs for p in paths):
        return ""
    return top


def extract_repo(zip_path: Path, dest: Path) -> str:
    """박제본을 `dest` 에 풀고 읽기 전용으로 돌린다. 벗긴 최상위 접두사(없으면 "")를 돌려준다.

    링크 항목은 만들지 않는다(밖을 가리킬 수 있다). 크기·항목 수는 압축 해제 전에 선언값으로, 풀면서 실제
    바이트로 한 번 더 센다(선언값을 속인 zip 폭탄)."""

    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise RunRejected("repo_zip_invalid") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise RunRejected("repo_zip_too_many_entries")
        if sum(i.file_size for i in infos) > MAX_EXTRACTED_BYTES:
            raise RunRejected("repo_zip_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        dirs: set[PurePosixPath] = set()
        for info in infos:
            rel = _safe_member_path(info.filename)
            if rel is None:
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                continue
            if info.is_dir():
                dirs.add(rel)
                continue
            members.append((info, rel))
        prefix = _common_root([rel for _, rel in members] + sorted(dirs), dirs)
        dest.mkdir(parents=True)
        written = 0
        for info, rel in members:
            if prefix:
                rel = PurePosixPath(*rel.parts[1:])
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "xb") as out:
                while chunk := src.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_EXTRACTED_BYTES:
                        raise RunRejected("repo_zip_too_large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                    out.write(chunk)
    _make_read_only(dest)
    return prefix


def _make_read_only(root: Path) -> None:
    for current, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(current, name), 0o444)
        for name in dirnames:
            os.chmod(os.path.join(current, name), 0o555)
    os.chmod(root, 0o555)


def _remove_tree(root: Path) -> None:
    """읽기 전용으로 돌린 폴더까지 지운다."""

    if not root.exists():
        return
    for current, dirnames, _ in os.walk(root):
        os.chmod(current, 0o755)
        for name in dirnames:
            path = os.path.join(current, name)
            if not os.path.islink(path):
                os.chmod(path, 0o755)
    shutil.rmtree(root, ignore_errors=True)


# ── 실행 하나 ─────────────────────────────────────────────────────────────────────────────────────────────


def validate_spec(raw: object) -> RunSpec:
    if not isinstance(raw, dict):
        raise RunRejected("spec_not_object")
    vendor = raw.get("vendor")
    if vendor not in VENDORS:
        raise RunRejected("spec_bad_vendor")
    for key in ("model", "prompt", "run_token"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RunRejected(f"spec_missing_{key}")
    if not isinstance(raw.get("output_schema"), dict):
        raise RunRejected("spec_missing_output_schema")
    budget = raw.get("max_budget_usd")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 < budget <= 5:
        raise RunRejected("spec_bad_max_budget_usd")
    spec: RunSpec = {
        "vendor": vendor,
        "model": raw["model"],
        "prompt": raw["prompt"],
        "output_schema": raw["output_schema"],
        "run_token": raw["run_token"],
        "max_budget_usd": float(budget),
    }
    timeout = raw.get("timeout_seconds")
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 0 < timeout <= RUN_TIMEOUT_SECONDS:
            raise RunRejected("spec_bad_timeout_seconds")
        spec["timeout_seconds"] = timeout
    mode = raw.get("mode", "cli")
    if mode not in MODES:
        raise RunRejected("spec_bad_mode")
    if mode == "selfloop":
        spec["mode"] = "selfloop"
        spec["requirements"] = _selfloop_requirements(raw.get("requirements"))
    return spec


def _selfloop_requirements(raw: object) -> list[selfloop.Requirement]:
    if not isinstance(raw, list) or not 0 < len(raw) <= MAX_SELFLOOP_REQUIREMENTS:
        raise RunRejected("spec_bad_requirements")
    out: list[selfloop.Requirement] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RunRejected("spec_bad_requirements")
        rid, text = item.get("id"), item.get("text")
        if isinstance(rid, bool) or not isinstance(rid, int) or not isinstance(text, str) or not text.strip():
            raise RunRejected("spec_bad_requirements")
        out.append({"id": rid, "text": text})
    if len({r["id"] for r in out}) != len(out):
        raise RunRejected("spec_bad_requirements")
    return out


@dataclass(frozen=True)
class RunnerConfig:
    work_root: Path = Path("/work")
    proxy_base_url: str = DEFAULT_PROXY_BASE_URL
    cli_path: str = CLI_PATH  # 시험은 가짜 `claude`·`codex` 가 든 폴더를 앞에 둔다

    @classmethod
    def from_env(cls) -> RunnerConfig:
        return cls(
            work_root=Path(os.environ.get("AGENT_GRADER_WORK_ROOT", "/work")),
            proxy_base_url=os.environ.get("AGENT_GRADER_PROXY_BASE_URL", DEFAULT_PROXY_BASE_URL),
        )


def execute_run(spec: RunSpec, repo_zip: Path, config: RunnerConfig) -> RunResult:
    """실행 하나 — 풀고, 띄우고, 지운다. 실행 전 거절은 RunRejected."""

    run_id = uuid.uuid4().hex
    run_dir = config.work_root / run_id
    repo, home, tmp = run_dir / "repo", run_dir / "home", run_dir / "tmp"
    try:
        run_dir.mkdir(parents=True)
        prefix = extract_repo(repo_zip, repo)
        if spec.get("mode") == "selfloop":
            return _execute_selfloop(spec, repo, prefix, run_id, config)
        home.mkdir()
        tmp.mkdir()
        if spec["vendor"] == "openai":
            (home / ".codex").mkdir()  # CODEX_HOME 은 있어야 한다 — 없으면 Codex 가 바로 끝난다
        schema_json = json.dumps(spec["output_schema"], ensure_ascii=False)
        if spec["vendor"] == "anthropic":
            argv = claude_argv(model=spec["model"], output_schema_json=schema_json, max_budget_usd=spec["max_budget_usd"])
            version = CLAUDE_CODE_VERSION
        else:
            schema_path = run_dir / "output-schema.json"
            schema_path.write_text(schema_json, encoding="utf-8")
            argv = codex_argv(
                model=spec["model"],
                output_schema_path=str(schema_path),
                repo_dir=str(repo),
                proxy_base_url=config.proxy_base_url,
            )
            version = CODEX_VERSION
        env = run_env(
            vendor=spec["vendor"],
            home=home,
            tmp=tmp,
            run_token=spec["run_token"],
            proxy_base_url=config.proxy_base_url,
            path=config.cli_path,
        )
        timeout = spec.get("timeout_seconds", RUN_TIMEOUT_SECONDS)
        outcome = _run_process(argv, env=env, cwd=repo, stdin_text=spec["prompt"], timeout=timeout, out_dir=run_dir)
        return {
            "run_id": run_id,
            "vendor": spec["vendor"],
            "cli_version": version,
            "repo_root_prefix": prefix,
            **outcome,
        }
    finally:
        _remove_tree(run_dir)


def _execute_selfloop(spec: RunSpec, repo: Path, prefix: str, run_id: str, config: RunnerConfig) -> RunResult:
    """우리 루프(#1245) — CLI 를 띄우지 않고 이 프로세스가 `llm-proxy` 를 부른다. 결과 꼴은 CLI 갈래와 같고
    `stdout` 은 `selfloop.LoopOutput` JSON 하나다. 시간은 `timeout_seconds`(없으면 `selfloop.RUN_SECONDS`) 안에서
    루프가 스스로 멈춘다."""

    started = time.monotonic()
    output = selfloop.run_selfloop(
        vendor=spec["vendor"],
        model=spec["model"],
        token=spec["run_token"],
        system=spec["prompt"],
        requirements=spec.get("requirements", []),
        root=repo,
        transport=selfloop.http_transport(config.proxy_base_url),
        seconds=spec.get("timeout_seconds", selfloop.RUN_SECONDS),
    )
    stdout = json.dumps(output, ensure_ascii=False)
    return {
        "run_id": run_id,
        "vendor": spec["vendor"],
        "cli_version": f"selfloop-{selfloop.SELFLOOP_VERSION}",
        "exit_code": 0,
        "timed_out": output["loop"]["stopped"] == "deadline",
        "duration_seconds": round(time.monotonic() - started, 3),
        "repo_root_prefix": prefix,
        "stdout": stdout,
        "stdout_truncated": False,
        "stderr_tail": "",
    }


class _Outcome(TypedDict):
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout: str
    stdout_truncated: bool
    stderr_tail: str


def _run_process(argv: list[str], *, env: dict[str, str], cwd: Path, stdin_text: str, timeout: int, out_dir: Path) -> _Outcome:
    stdout_path, stderr_path = out_dir / "stdout", out_dir / "stderr"
    started = time.monotonic()
    timed_out = False
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        proc = subprocess.Popen(  # noqa: S603 — argv 는 위의 고정 인자다
            argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True
        )
        try:
            assert proc.stdin is not None
            try:
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.close()
            except BrokenPipeError:
                pass
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # 끝났어도 남은 자식(셸 등)까지 프로세스 그룹째 내린다.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    with open(stdout_path, "rb") as f:
        stdout = f.read(MAX_STDOUT_BYTES + 1)
    with open(stderr_path, "rb") as f:
        f.seek(max(0, stderr_path.stat().st_size - STDERR_TAIL_BYTES))
        stderr_tail = f.read()
    return {
        "exit_code": None if timed_out else proc.returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": stdout[:MAX_STDOUT_BYTES].decode("utf-8", "replace"),
        "stdout_truncated": len(stdout) > MAX_STDOUT_BYTES,
        "stderr_tail": stderr_tail.decode("utf-8", "replace"),
    }


# ── HTTP 서비스 ───────────────────────────────────────────────────────────────────────────────────────────
#
# POST /runs   본문 = 실행 명세 JSON 한 줄 + "\n" + 박제본 zip 바이트(`encode_run_request`).
#              200 RunResult · 400/413 {"reason"} 실행 전 거절 · 503 동시 실행이 찼다(Retry-After).
# GET  /health {"ok", "claude_code", "codex", "max_concurrent_runs", "active_runs"}

RUN_CONTENT_TYPE = "application/x-codemit-agent-run"


def encode_run_request(spec: RunSpec, repo_zip: bytes) -> bytes:
    return json.dumps(spec, ensure_ascii=True).encode("ascii") + b"\n" + repo_zip


class _Handler(BaseHTTPRequestHandler):
    server: AgentGraderServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — 부모 서명
        # 요청 줄만 남긴다 — 본문(프롬프트·토큰)은 로그에 없다.
        sys.stderr.write(f"agent-grader {self.address_string()} {format % args}\n")

    def _send_json(self, status: HTTPStatus, body: object, headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(HTTPStatus.NOT_FOUND, {"reason": "not_found"})
            return
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "claude_code": CLAUDE_CODE_VERSION,
                "codex": CODEX_VERSION,
                "max_concurrent_runs": MAX_CONCURRENT_RUNS,
                "active_runs": self.server.active_runs(),
            },
        )

    def do_POST(self) -> None:
        if self.path != "/runs":
            self._send_json(HTTPStatus.NOT_FOUND, {"reason": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            self._send_json(HTTPStatus.LENGTH_REQUIRED, {"reason": "length_required"})
            return
        if length > MAX_REPO_ZIP_BYTES + MAX_SPEC_BYTES:
            self.close_connection = True
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"reason": "repo_zip_too_large"})
            return
        if not self.server.take_slot():
            self.close_connection = True
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"reason": "busy"}, {"Retry-After": "5"})
            return
        try:
            self._run(length)
        finally:
            self.server.give_slot()

    def _run(self, length: int) -> None:
        config = self.server.config
        upload = config.work_root / f"upload-{uuid.uuid4().hex}.zip"
        try:
            line = self.rfile.readline(MAX_SPEC_BYTES + 1)
            remaining = length - len(line)
            if not line.endswith(b"\n") or remaining < 0:
                raise RunRejected("spec_line_invalid")
            try:
                spec = validate_spec(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RunRejected("spec_not_json") from exc
            with open(upload, "wb") as out:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        raise RunRejected("body_truncated")
                    out.write(chunk)
                    remaining -= len(chunk)
            result = execute_run(spec, upload, config)
        except RunRejected as rejected:
            self.close_connection = True
            self._send_json(rejected.status, {"reason": rejected.reason})
            return
        finally:
            upload.unlink(missing_ok=True)
        self._send_json(HTTPStatus.OK, result)


class AgentGraderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], config: RunnerConfig) -> None:
        super().__init__(address, _Handler)
        self.config = config
        self._lock = threading.Lock()
        self._active = 0

    def take_slot(self) -> bool:
        """동시 실행 자리를 하나 잡는다 — 찼으면 기다리지 않고 False(부르는 쪽은 503 을 받는다)."""

        with self._lock:
            if self._active >= MAX_CONCURRENT_RUNS:
                return False
            self._active += 1
            return True

    def give_slot(self) -> None:
        with self._lock:
            self._active -= 1

    def active_runs(self) -> int:
        with self._lock:
            return self._active


# ── 부르는 쪽(#1000) ───────────────────────────────────────────────────────────────────────────────────────


def request_run(
    spec: RunSpec,
    repo_zip: bytes,
    *,
    service_url: str = DEFAULT_SERVICE_URL,
    timeout: float = RUN_TIMEOUT_SECONDS + 60,
) -> RunResult:
    """실행 하나를 맡기고 끝날 때까지 기다린다. 503 → AgentGraderBusy, 400/413 → RunRejected,
    닿지 못함·그 밖의 응답 → AgentGraderError. CLI 가 실패해도(종료코드≠0·시간 초과) 결과는 200 으로 온다."""

    request = urllib.request.Request(
        service_url.rstrip("/") + "/runs",
        data=encode_run_request(spec, repo_zip),
        method="POST",
        headers={"Content-Type": RUN_CONTENT_TYPE},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — 내부 주소
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            reason = str(json.loads(body).get("reason", ""))
        except (ValueError, AttributeError):
            reason = ""
        if exc.code == HTTPStatus.SERVICE_UNAVAILABLE:
            raise AgentGraderBusy(reason or "busy") from exc
        if exc.code in (HTTPStatus.BAD_REQUEST, HTTPStatus.REQUEST_ENTITY_TOO_LARGE):
            raise RunRejected(reason or "rejected", HTTPStatus(exc.code)) from exc
        raise AgentGraderError(f"HTTP {exc.code} {reason}".strip()) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        raise AgentGraderError(type(exc).__name__) from exc


def check_health(*, service_url: str = DEFAULT_SERVICE_URL, timeout: float = 5) -> None:
    """실행기의 `GET /health` 에 한 번 닿아 본다(#1257). 닿지 못했거나 `ok` 가 아니면 AgentGraderError."""

    try:
        with urllib.request.urlopen(service_url.rstrip("/") + "/health", timeout=timeout) as response:  # noqa: S310 — 내부 주소
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise AgentGraderError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        raise AgentGraderError(type(exc).__name__) from exc
    if not (isinstance(body, dict) and body.get("ok") is True):
        raise AgentGraderError("health 응답이 ok 가 아니다")


# ── 자가 점검·진입점 ──────────────────────────────────────────────────────────────────────────────────────


def selfcheck(env: dict[str, str] | None = None, home: Path | None = None, *, check_versions: bool = True) -> list[str]:
    """컨테이너 안에 진짜 키 env·자격증명 파일이 없는가, CLI 둘이 고정 버전인가. 문제 목록(없으면 [])."""

    env = dict(os.environ) if env is None else env
    problems: list[str] = []
    for name in sorted(env):
        if name in FORBIDDEN_ENV_NAMES or any(marker in name.upper() for marker in FORBIDDEN_ENV_MARKERS):
            problems.append(f"env:{name}")
    homes = [home] if home is not None else [Path.home(), Path("/root")]
    for base in homes:
        for pattern in CREDENTIAL_PATHS:
            path = base / pattern.removeprefix("~/")
            try:
                if path.exists():
                    problems.append(f"file:{path}")
            except PermissionError:
                continue
    if check_versions:
        for argv, want in ((["claude", "--version"], CLAUDE_CODE_VERSION), (["codex", "--version"], CODEX_VERSION)):
            try:
                out = subprocess.run(argv, capture_output=True, text=True, timeout=60, env={"PATH": env.get("PATH", ""), "HOME": "/tmp"})  # noqa: S603
                version_line = out.stdout.strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                version_line = f"error {type(exc).__name__}"
            if want not in version_line.split():
                problems.append(f"version:{argv[0]}={version_line!r}")
    return problems


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "serve"
    if command == "serve":
        config = RunnerConfig.from_env()
        config.work_root.mkdir(parents=True, exist_ok=True)
        server = AgentGraderServer(("0.0.0.0", SERVICE_PORT), config)  # noqa: S104 — 내부 네트워크 전용
        sys.stderr.write(f"agent-grader listening :{SERVICE_PORT} claude={CLAUDE_CODE_VERSION} codex={CODEX_VERSION}\n")
        server.serve_forever()
        return 0
    if command == "selfcheck":
        problems = selfcheck()
        print(json.dumps({"ok": not problems, "problems": problems, "claude_code": CLAUDE_CODE_VERSION, "codex": CODEX_VERSION}))
        return 1 if problems else 0
    if command == "health":
        with urllib.request.urlopen(f"http://127.0.0.1:{SERVICE_PORT}/health", timeout=3) as response:  # noqa: S310
            return 0 if json.loads(response.read()).get("ok") else 1
    sys.stderr.write("쓰는 법: agent_runner.py serve|selfcheck|health\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
