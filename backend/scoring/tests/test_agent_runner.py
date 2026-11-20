"""에이전트 채점 실행기(#999) — 실행 틀(`scoring.agent_runner`)과 그 이미지·compose 의 계약.

CLI 는 가짜다(이 파일이 만드는 `claude`·`codex` 스크립트 — 받은 argv·env·cwd·stdin 과 저장소 파일 목록을 JSON 으로
찍는다). 진짜 CLI 를 가짜 벤더에 붙여 보는 것은 PR 검사의 `agent-grader` 잡(`scripts/ci/agent-grader-check.sh`)이다.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import stat
import sys
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from django.conf import settings

from scoring import agent_runner as ar

REPO_ROOT = settings.BASE_DIR.parent
RUNNER_FILE = Path(ar.__file__)
SECCOMP_PROFILE = REPO_ROOT / "docker" / "agent-grader-seccomp.json"

FAKE_CLI = """#!{python}
import json, os, sys, time
prompt = sys.stdin.read()
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
files = sorted(
    os.path.relpath(os.path.join(d, f), os.getcwd()) for d, _, fs in os.walk(os.getcwd()) for f in fs
)
modes = {{p: oct(os.stat(p).st_mode & 0o777) for p in files}}
print(json.dumps({{"argv": sys.argv, "env": dict(os.environ), "cwd": os.getcwd(), "prompt": prompt,
                  "files": files, "modes": modes}}))
print("stderr-line", file=sys.stderr)
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def _zip(files: dict[str, str | bytes], *, links: dict[str, str] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buf.getvalue()


@pytest.fixture
def cli_dir(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("claude", "codex"):
        script = bin_dir / name
        script.write_text(FAKE_CLI.format(python=sys.executable), encoding="utf-8")
        script.chmod(0o755)
    return bin_dir


@pytest.fixture
def config(tmp_path: Path, cli_dir: Path) -> ar.RunnerConfig:
    work = tmp_path / "work"
    work.mkdir()
    return ar.RunnerConfig(work_root=work, proxy_base_url="http://proxy.test:8002", cli_path=f"{cli_dir}:/usr/bin:/bin")


def _spec(vendor: ar.Vendor = "anthropic", **extra: object) -> ar.RunSpec:
    spec: dict[str, object] = {
        "vendor": vendor,
        "model": "claude-sonnet-4-5" if vendor == "anthropic" else "gpt-5.5",
        "prompt": "저장소를 읽고 판정하라",
        "output_schema": {"type": "object", "properties": {"verdict": {"type": "string"}}},
        "run_token": "run-token-abc",
        "max_budget_usd": 1.0,
    }
    spec.update(extra)
    return ar.validate_spec(spec)


def _write_zip(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "repo.zip"
    path.write_bytes(data)
    return path


# ── 고정 인자 ────────────────────────────────────────────────────────────────────────────────────────────


def test_claude_argv_is_the_fixed_read_only_set() -> None:
    argv = ar.claude_argv(model="claude-sonnet-4-5", output_schema_json='{"type":"object"}', max_budget_usd=1)
    assert argv == [
        "claude",
        "-p",
        "--model",
        "claude-sonnet-4-5",
        "--safe-mode",
        "--restricted",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--tools",
        "Read,Grep,Glob",
        "--allowedTools",
        "Read,Grep,Glob",
        "--json-schema",
        '{"type":"object"}',
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        "1.00",
    ]
    # `--bare` 는 init 도구를 Read 하나로 줄여 디렉터리를 못 뒤진다(#992 실측).
    assert "--bare" not in argv


def test_codex_argv_is_read_only_ephemeral_and_goes_through_the_proxy() -> None:
    argv = ar.codex_argv(
        model="gpt-5.5", output_schema_path="/work/r/output-schema.json", repo_dir="/work/r/repo", proxy_base_url="http://llm-proxy:8002"
    )
    assert argv[:2] == ["codex", "exec"]
    assert argv[-1] == "-"  # 프롬프트는 stdin
    joined = " ".join(argv)
    for flag in (
        "--sandbox read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--output-schema /work/r/output-schema.json",
        "--json",
        "--model gpt-5.5",
        "--cd /work/r/repo",
    ):
        assert flag in joined
    config = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert config == [
        'model_provider="codemit"',
        'model_providers.codemit.name="codemit"',
        'model_providers.codemit.base_url="http://llm-proxy:8002/v1"',
        f'model_providers.codemit.env_key="{ar.CODEX_TOKEN_ENV}"',
        'model_providers.codemit.wire_api="responses"',
        "model_providers.codemit.request_max_retries=0",
        "model_providers.codemit.stream_max_retries=0",
        'shell_environment_policy.inherit="none"',
        'shell_environment_policy.set.PATH="/usr/local/bin:/usr/bin:/bin"',
        "project_doc_max_bytes=0",
        'web_search="disabled"',
    ]
    disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
    assert "hooks" in disabled and "plugins" in disabled
    assert disabled == list(ar.CODEX_DISABLED_FEATURES)


def test_cli_env_is_built_from_scratch_with_only_the_run_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-value-not-leaked")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-value-not-leaked")
    claude = ar.run_env(vendor="anthropic", home=tmp_path / "h", tmp=tmp_path / "t", run_token="tok", proxy_base_url="http://llm-proxy:8002/")
    codex = ar.run_env(vendor="openai", home=tmp_path / "h", tmp=tmp_path / "t", run_token="tok", proxy_base_url="http://llm-proxy:8002")
    assert claude["ANTHROPIC_API_KEY"] == "tok"
    assert claude["ANTHROPIC_BASE_URL"] == "http://llm-proxy:8002"
    assert "OPENAI_API_KEY" not in claude and "OPENAI_API_KEY" not in codex
    assert codex[ar.CODEX_TOKEN_ENV] == "tok"
    assert "ANTHROPIC_API_KEY" not in codex
    assert codex["CODEX_HOME"] == str(tmp_path / "h" / ".codex")
    for env in (claude, codex):
        assert env["HOME"] == str(tmp_path / "h")
        assert "fake-openai-value-not-leaked" not in env.values()
        assert set(env) <= {
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_BASE_URL",
            "DISABLE_AUTOUPDATER",
            "DISABLE_TELEMETRY",
            "DISABLE_ERROR_REPORTING",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            "CODEX_HOME",
            ar.CODEX_TOKEN_ENV,
        }


def test_cli_versions_are_pinned_in_one_place_and_match_the_dockerfile() -> None:
    dockerfile = (REPO_ROOT / "docker" / "agent-grader.Dockerfile").read_text(encoding="utf-8")
    assert f"ARG CLAUDE_CODE_VERSION={ar.CLAUDE_CODE_VERSION}\n" in dockerfile
    assert f"ARG CODEX_VERSION={ar.CODEX_VERSION}\n" in dockerfile
    assert '"@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"' in dockerfile
    assert '"@openai/codex@${CODEX_VERSION}"' in dockerfile
    for version in (ar.CLAUDE_CODE_VERSION, ar.CODEX_VERSION):
        assert all(part.isdigit() for part in version.split(".")), "범위(^·~·latest)가 아닌 정확한 버전"
    assert "COPY backend/scoring/agent_runner.py /app/agent_runner.py" in dockerfile
    assert "\nUSER grader\n" in dockerfile


def test_runner_uses_only_the_standard_library() -> None:
    """이미지에는 Django 도 backend 의존성도 없다 — 파일 하나만 복사된다."""

    tree = ast.parse(RUNNER_FILE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots - {"__future__"} <= set(sys.stdlib_module_names)


# ── 박제본 풀기 ──────────────────────────────────────────────────────────────────────────────────────────


def test_extract_strips_the_zipball_root_and_makes_the_tree_read_only(tmp_path: Path) -> None:
    data = _zip({"owner-repo-abc123/app.py": "print(1)\n", "owner-repo-abc123/pkg/mod.py": "x = 1\n"})
    dest = tmp_path / "repo"
    prefix = ar.extract_repo(_write_zip(tmp_path, data), dest)
    assert prefix == "owner-repo-abc123"
    assert (dest / "app.py").read_text() == "print(1)\n"
    assert (dest / "pkg" / "mod.py").exists()
    assert stat.S_IMODE((dest / "app.py").stat().st_mode) == 0o444
    assert stat.S_IMODE((dest / "pkg").stat().st_mode) == 0o555
    assert stat.S_IMODE(dest.stat().st_mode) == 0o555


def test_extract_keeps_paths_when_there_is_no_single_root(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    assert ar.extract_repo(_write_zip(tmp_path, _zip({"app.py": "a", "lib/x.py": "b"})), dest) == ""
    assert (dest / "app.py").exists() and (dest / "lib" / "x.py").exists()


@pytest.mark.parametrize("name", ["../evil.py", "/etc/passwd", "a/../../evil.py", "C:/evil.py", "a\\..\\evil.py"])
def test_extract_rejects_paths_that_leave_the_repo(tmp_path: Path, name: str) -> None:
    with pytest.raises(ar.RunRejected) as caught:
        ar.extract_repo(_write_zip(tmp_path, _zip({"ok.py": "1", name: "x"})), tmp_path / "repo")
    assert caught.value.reason == "repo_zip_bad_path"
    assert not (tmp_path / "evil.py").exists()


def test_extract_does_not_create_symlinks(tmp_path: Path) -> None:
    dest = tmp_path / "repo"
    ar.extract_repo(_write_zip(tmp_path, _zip({"app.py": "1"}, links={"secret": "/etc/passwd"})), dest)
    assert not (dest / "secret").exists() and not (dest / "secret").is_symlink()


def test_extract_refuses_archives_over_the_size_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar, "MAX_EXTRACTED_BYTES", 10)
    with pytest.raises(ar.RunRejected) as caught:
        ar.extract_repo(_write_zip(tmp_path, _zip({"big.txt": "x" * 100})), tmp_path / "repo")
    assert caught.value.reason == "repo_zip_too_large"


def test_extract_refuses_what_is_not_a_zip(tmp_path: Path) -> None:
    with pytest.raises(ar.RunRejected) as caught:
        ar.extract_repo(_write_zip(tmp_path, b"not a zip"), tmp_path / "repo")
    assert caught.value.reason == "repo_zip_invalid"


# ── 실행 하나 ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_a_run_feeds_the_cli_and_removes_its_work_dir(tmp_path: Path, config: ar.RunnerConfig, vendor: ar.Vendor) -> None:
    zip_path = _write_zip(tmp_path, _zip({"me-repo-1/app.py": "def f():\n    return 1\n"}))
    result = ar.execute_run(_spec(vendor), zip_path, config)

    assert result["exit_code"] == 0 and result["timed_out"] is False
    assert result["repo_root_prefix"] == "me-repo-1"
    assert result["stderr_tail"].strip() == "stderr-line"
    seen = json.loads(result["stdout"])
    assert seen["prompt"] == "저장소를 읽고 판정하라"  # stdin 으로 — argv 에 없다
    assert "저장소를 읽고 판정하라" not in seen["argv"]
    assert seen["files"] == ["app.py"]
    assert seen["modes"] == {"app.py": "0o444"}
    run_dir = Path(seen["cwd"]).parent
    assert Path(seen["cwd"]) == run_dir / "repo"
    assert seen["env"]["HOME"] == str(run_dir / "home")
    if vendor == "anthropic":
        assert result["cli_version"] == ar.CLAUDE_CODE_VERSION
        assert seen["env"]["ANTHROPIC_API_KEY"] == "run-token-abc"
        assert seen["env"]["ANTHROPIC_BASE_URL"] == "http://proxy.test:8002"
        assert "--json-schema" in seen["argv"]
    else:
        assert result["cli_version"] == ar.CODEX_VERSION
        assert seen["env"][ar.CODEX_TOKEN_ENV] == "run-token-abc"
        assert 'model_providers.codemit.base_url="http://proxy.test:8002/v1"' in seen["argv"]
    # 끝나면 실행 폴더가 없다(읽기 전용으로 돌린 저장소까지).
    assert list(config.work_root.iterdir()) == []


def test_a_failing_cli_still_returns_a_result_and_cleans_up(tmp_path: Path, config: ar.RunnerConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = Path(config.cli_path.split(":")[0]) / "claude"
    fake.write_text(fake.read_text().replace('os.environ.get("FAKE_EXIT", "0")', '"3"'))
    result = ar.execute_run(_spec(), _write_zip(tmp_path, _zip({"a.py": "1"})), config)
    assert result["exit_code"] == 3 and result["timed_out"] is False
    assert list(config.work_root.iterdir()) == []


def test_a_run_over_its_time_limit_is_killed(tmp_path: Path, config: ar.RunnerConfig) -> None:
    fake = Path(config.cli_path.split(":")[0]) / "claude"
    fake.write_text(fake.read_text().replace('if os.environ.get("FAKE_SLEEP"):', "if True:").replace(
        'float(os.environ["FAKE_SLEEP"])', "30"
    ))
    result = ar.execute_run(_spec(timeout_seconds=1), _write_zip(tmp_path, _zip({"a.py": "1"})), config)
    assert result["timed_out"] is True and result["exit_code"] is None
    assert result["duration_seconds"] < 10
    assert list(config.work_root.iterdir()) == []


def test_a_rejected_archive_runs_nothing_and_leaves_nothing(tmp_path: Path, config: ar.RunnerConfig) -> None:
    with pytest.raises(ar.RunRejected):
        ar.execute_run(_spec(), _write_zip(tmp_path, _zip({"../x": "1"})), config)
    assert list(config.work_root.iterdir()) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"vendor": "google"}, "spec_bad_vendor"),
        ({"run_token": ""}, "spec_missing_run_token"),
        ({"prompt": " "}, "spec_missing_prompt"),
        ({"output_schema": "x"}, "spec_missing_output_schema"),
        ({"max_budget_usd": 0}, "spec_bad_max_budget_usd"),
        ({"max_budget_usd": 50}, "spec_bad_max_budget_usd"),
        ({"timeout_seconds": ar.RUN_TIMEOUT_SECONDS + 1}, "spec_bad_timeout_seconds"),
    ],
)
def test_bad_specs_are_rejected_before_anything_runs(change: dict[str, object], reason: str) -> None:
    raw: dict[str, object] = dict(_spec())
    raw.update(change)
    with pytest.raises(ar.RunRejected) as caught:
        ar.validate_spec(raw)
    assert caught.value.reason == reason


# ── HTTP 서비스와 부르는 쪽 ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def server(config: ar.RunnerConfig) -> Iterator[tuple[ar.AgentGraderServer, str]]:
    srv = ar.AgentGraderServer(("127.0.0.1", 0), config)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def test_an_idle_service_does_nothing(server: tuple[ar.AgentGraderServer, str], config: ar.RunnerConfig) -> None:
    """배포돼 떠 있어도 부르는 쪽(#1000)이 없으면 CLI 를 띄우지 않고 아무것도 쓰지 않는다."""

    srv, url = server
    import urllib.request

    with urllib.request.urlopen(url + "/health", timeout=5) as response:
        health = json.loads(response.read())
    assert health == {
        "ok": True,
        "claude_code": ar.CLAUDE_CODE_VERSION,
        "codex": ar.CODEX_VERSION,
        "max_concurrent_runs": 2,
        "active_runs": 0,
    }
    assert list(config.work_root.iterdir()) == []


def test_request_run_round_trip(server: tuple[ar.AgentGraderServer, str], config: ar.RunnerConfig) -> None:
    _, url = server
    result = ar.request_run(_spec("openai"), _zip({"r-1/app.py": "1"}), service_url=url, timeout=30)
    assert result["vendor"] == "openai" and result["exit_code"] == 0
    assert json.loads(result["stdout"])["files"] == ["app.py"]
    assert list(config.work_root.iterdir()) == []


def test_request_run_surfaces_a_rejection(server: tuple[ar.AgentGraderServer, str]) -> None:
    _, url = server
    with pytest.raises(ar.RunRejected) as caught:
        ar.request_run(_spec(), _zip({"../evil": "1"}), service_url=url, timeout=30)
    assert caught.value.reason == "repo_zip_bad_path"


def test_a_third_concurrent_run_is_turned_away(server: tuple[ar.AgentGraderServer, str]) -> None:
    srv, url = server
    assert ar.MAX_CONCURRENT_RUNS == 2
    assert srv.take_slot() and srv.take_slot()
    try:
        assert not srv.take_slot()
        with pytest.raises(ar.AgentGraderBusy):
            ar.request_run(_spec(), _zip({"a.py": "1"}), service_url=url, timeout=30)
    finally:
        srv.give_slot()
        srv.give_slot()
    assert srv.active_runs() == 0


def test_an_unreachable_service_is_a_transient_error() -> None:
    with pytest.raises(ar.AgentGraderError):
        ar.request_run(_spec(), _zip({"a.py": "1"}), service_url="http://127.0.0.1:9", timeout=2)


# ── 키·자격증명 없음 ─────────────────────────────────────────────────────────────────────────────────────


def test_selfcheck_flags_key_env_and_credential_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    assert ar.selfcheck({"PATH": "/bin", "HOME": str(home)}, home, check_versions=False) == []
    (home / ".codex" / "auth.json").write_text("{}")
    problems = ar.selfcheck(
        {"PATH": "/bin", "OPENAI_API_KEY": "x", "CLAUDE_CODE_OAUTH_TOKEN": "y", "DB_PASSWORD": "z"}, home, check_versions=False
    )
    assert problems == [
        "env:CLAUDE_CODE_OAUTH_TOKEN",
        "env:DB_PASSWORD",
        "env:OPENAI_API_KEY",
        f"file:{home / '.codex' / 'auth.json'}",
    ]


# ── compose ──────────────────────────────────────────────────────────────────────────────────────────────


class _ComposeLoader(yaml.SafeLoader):
    """compose 의 `!reset` 을 그 값 그대로 읽는다."""


_ComposeLoader.add_constructor(
    "!reset",
    lambda loader, node: loader.construct_sequence(node)
    if isinstance(node, yaml.SequenceNode)
    else loader.construct_mapping(node)
    if isinstance(node, yaml.MappingNode)
    else loader.construct_scalar(node),
)


def _compose(name: str) -> dict:
    return yaml.load((REPO_ROOT / "docker" / name).read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_prod_agent_grader_is_locked_down() -> None:
    prod = _compose("compose.prod.yaml")
    svc = prod["services"]["agent-grader"]
    assert svc["read_only"] is True
    assert svc["networks"] == ["agent", "agent-call"]
    assert prod["networks"]["agent"] == {"internal": True}
    assert prod["networks"]["agent-call"] == {"internal": True}
    assert "ports" not in svc and "volumes" not in svc and "env_file" not in svc
    assert svc["cap_drop"] == ["ALL"]
    # seccomp 는 풀지 않는다 — docker 기본 프로필 + bwrap 몫(아래 test_seccomp_profile_*).
    assert svc["security_opt"] == ["no-new-privileges:true", f"seccomp:./{SECCOMP_PROFILE.name}"]
    tmpfs = {entry.split(":")[0]: entry for entry in svc["tmpfs"]}
    assert set(tmpfs) == {"/work", "/tmp"}
    assert svc["mem_limit"] == "1536m"
    # 키 env 가 없다 — 프록시 주소 하나뿐.
    assert svc["environment"] == {"AGENT_GRADER_PROXY_BASE_URL": ar.DEFAULT_PROXY_BASE_URL}
    assert ar.selfcheck(dict(svc["environment"]), Path("/nonexistent"), check_versions=False) == []
    assert svc["healthcheck"]["test"] == ["CMD", "python3", "/app/agent_runner.py", "health"]
    assert svc["image"].endswith("/codemit-agent-grader:${CODEMIT_IMAGE_TAG:-local}-arm64")


def _members(compose: dict, network: str) -> set[str]:
    return {name for name, svc in compose["services"].items() if network in (svc.get("networks") or ["default"])}


def test_the_caller_reaches_the_runner_but_the_runner_sees_only_the_proxy_and_the_caller() -> None:
    """에이전트 채점·리뷰는 `celery-worker` 의 스캔이 `http://agent-grader:8003` 으로 부른다(#1031). 둘이 같은
    네트워크에 없으면 이름이 풀리지 않아 스위치를 켜는 순간 모든 실행이 `AgentGraderError` 다."""

    prod = _compose("compose.prod.yaml")
    assert ar.DEFAULT_SERVICE_URL == "http://agent-grader:8003"
    caller = set(prod["services"]["celery-worker"]["networks"])
    assert caller & set(prod["services"]["agent-grader"]["networks"]) == {"agent-call"}
    # 실행기에서 보이는 것: 프록시(`agent`)와 부르는 쪽(`agent-call`)뿐. 둘 다 밖으로 나가는 길이 없다.
    assert _members(prod, "agent") == {"agent-grader", "llm-proxy"}
    assert _members(prod, "agent-call") == {"agent-grader", "celery-worker"}


def test_ci_check_calls_the_runner_from_where_prod_calls_it() -> None:
    """검사 driver 가 `agent` 에 서서 부르면 운영의 네트워크 갈림을 못 본다(#1031 이 그렇게 빠졌다)."""

    check = _compose("compose.agent-grader-check.yaml")
    driver = set(check["services"]["driver"]["networks"])
    assert "agent" not in driver
    assert driver & set(check["services"]["agent-grader"]["networks"]) == {"agent-call"}
    assert check["networks"]["agent-call"] == {"internal": True}


def test_ci_check_runs_the_same_locked_down_service_as_prod() -> None:
    """PR 검사가 가짜 벤더로 돌리는 실행기는 운영 정의의 격리 설정을 그대로 쓴다."""

    prod = _compose("compose.prod.yaml")["services"]["agent-grader"]
    check = _compose("compose.agent-grader-check.yaml")["services"]["agent-grader"]
    for key in ("read_only", "tmpfs", "cap_drop", "mem_limit", "pids_limit", "networks", "environment"):
        assert check[key] == prod[key], key
    # 검사 실행기(Ubuntu)의 AppArmor 만 더 푼다 — 운영 호스트에는 AppArmor 가 없다.
    assert check["security_opt"] == [*prod["security_opt"], "apparmor:unconfined"]


# docker 기본 seccomp 프로필(moby/profiles seccomp v0.2.4 = docker-v29.9.2 가 싣는 것)의 `syscalls` 해시 — 위에 더한
# 규칙 말고는 한 글자도 바꾸지 않았다는 증거다. 기본 프로필을 올리면 이 값과 출처를 같이 고친다.
UPSTREAM_SYSCALLS_SHA256 = "87516bb09b654fe78895cd56b7144af559fad28934c923755f483ae6e415fd5f"
CLONE_NEWUSER = 0x10000000


def _seccomp() -> dict:
    return json.loads(SECCOMP_PROFILE.read_text(encoding="utf-8"))


def test_seccomp_profile_is_docker_default_plus_bwrap_rules_only() -> None:
    profile = _seccomp()
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    upstream, added = profile["syscalls"][:-2], profile["syscalls"][-2:]
    digest = hashlib.sha256(json.dumps(upstream, sort_keys=True).encode()).hexdigest()
    assert digest == UPSTREAM_SYSCALLS_SHA256
    # clone 은 CLONE_NEWUSER 가 있을 때만 — 그 밖의 네임스페이스 clone 은 기본 프로필 그대로다.
    clone, rest = added
    assert clone["names"] == ["clone"] and clone["action"] == "SCMP_ACT_ALLOW"
    assert clone["args"] == [{"index": 0, "value": CLONE_NEWUSER, "valueTwo": CLONE_NEWUSER, "op": "SCMP_CMP_MASKED_EQ"}]
    assert sorted(rest["names"]) == ["mount", "pivot_root", "umount2", "unshare"]
    assert rest["action"] == "SCMP_ACT_ALLOW" and "args" not in rest and "includes" not in rest


def test_seccomp_profile_does_not_open_clone3_or_setns() -> None:
    """bwrap 이 쓰지 않는 네임스페이스 syscall 은 여전히 CAP_SYS_ADMIN 에게만 열린다."""

    for rule in _seccomp()["syscalls"]:
        if rule["action"] != "SCMP_ACT_ALLOW":
            continue
        opened = {"clone3", "setns", "sethostname"} & set(rule["names"])
        assert not opened or rule.get("includes", {}).get("caps") == ["CAP_SYS_ADMIN"], rule


def test_only_the_agent_scorer_calls_the_runner() -> None:
    """실행기를 부르는 곳은 허용 목록뿐이다 — `core.agent_scoring`(#1000)과 완성도 리뷰 `scoring.quality`(#1001),
    채점 서비스는 예외 이름만 들인다. 실행 틀 모듈은 `scoring.apps` 가 `core.agent_ports` 에 등록하고(#1085),
    `core.agent_scoring` 은 거기서 꺼낸다.
    기본값(`CONTEST_SCORING_METHOD=single_call`)이면 그마저 타지 않는다(`test_agent_scoring.py`)."""

    callers = []
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        if "tests" in path.parts or path == RUNNER_FILE or ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "agent_runner" in text:
            callers.append(str(path.relative_to(REPO_ROOT)))
    allowed = {
        "backend/core/agent_ports.py",
        "backend/core/agent_scoring.py",
        "backend/scoring/apps.py",
        "backend/scoring/quality.py",
        "backend/scoring/services.py",
    }
    assert "backend/core/agent_scoring.py" in callers
    assert set(callers) <= allowed, sorted(set(callers) - allowed)
    services_text = (REPO_ROOT / "backend/scoring/services.py").read_text(encoding="utf-8")
    assert "from .agent_runner import AgentGraderBusy, AgentGraderError\n" in services_text
    assert "request_run" not in services_text
