"""우리 채점 루프(#1245) — 실행기 `selfloop` 갈래를 가짜 `llm-proxy`(두 벤더)에 붙여 본다. 진짜 모델은 부르지 않는다.

시임은 실행기의 실행 하나(`agent_runner.execute_run` — HTTP `POST /runs` 가 그대로 부르는 것)다. 모델 쪽은
`tests.selfloop_fake` 가 진짜 API 처럼 tool_use·tool_result 짝을 따지는 가짜 프록시다.
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from django.conf import settings

from scoring import agent_runner as ar
from scoring import selfloop
from tests.selfloop_fake import TOKEN, Call, FakeProxy, Say, Status, serve

REPO_ROOT = settings.BASE_DIR.parent
APP_PY = "import os\n\ndef login(user):\n    return check(user)\n# 끝\n"
FILES = {"repo-abc/app.py": APP_PY, "repo-abc/README.md": "# 로그인 기능이 있다\n", "repo-abc/lib/util.py": "x = 1\n"}
MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4.1-mini"}
REQS = [{"id": 7, "text": "로그인"}]
PLAN = [Call("submit_plan", {"plans": [{"requirement_id": 7, "files": ["app.py", "없는.py"]}]})]
READ_APP = [Call("read_file", {"path": "app.py"})]
GOOD = [Call("submit_verdict", {"met": True, "evidence": ["app.py:3-4"], "reason": "로그인 함수가 있다."})]
IMPORT_ONLY = [Call("submit_verdict", {"met": True, "evidence": ["app.py:1"], "reason": "있다."})]

vendors = pytest.mark.parametrize("vendor", ["anthropic", "openai"])


def _zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _run(tmp_path: Path, vendor: str, script: dict, *, requirements: list | None = None, **extra: object) -> tuple[dict, FakeProxy]:
    proxy = FakeProxy(vendor=vendor, model=MODELS[vendor], script=script)
    zip_path = tmp_path / "repo.zip"
    zip_path.write_bytes(_zip())
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    raw = {
        "vendor": vendor,
        "model": MODELS[vendor],
        "prompt": "지침",
        "output_schema": {"type": "object"},
        "run_token": TOKEN,
        "max_budget_usd": 1,
        "mode": "selfloop",
        "requirements": requirements or REQS,
        **extra,
    }
    with serve(proxy):
        result = ar.execute_run(ar.validate_spec(raw), zip_path, ar.RunnerConfig(work_root=work, proxy_base_url=proxy.url))
    assert proxy.rejections == [], "가짜 프록시(= 진짜 API)가 대화 꼴을 거절했다"
    assert not any(work.iterdir()), "실행 폴더를 지운다"
    return result, proxy


def _loop(result: dict) -> dict:
    return json.loads(result["stdout"])


# ── 정상 ────────────────────────────────────────────────────────────────────────────────────────────────


@vendors
def test_plan_then_fresh_context_per_requirement_gives_a_verified_verdict(tmp_path: Path, vendor: str) -> None:
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [READ_APP, GOOD]})

    assert result["cli_version"] == f"selfloop-{selfloop.SELFLOOP_VERSION}"
    assert result["exit_code"] == 0 and result["timed_out"] is False
    assert result["repo_root_prefix"] == "repo-abc"
    out = _loop(result)
    assert out["verdicts"] == [{"requirement_id": 7, "met": True, "evidence": ["app.py:3-4"], "reason": "로그인 함수가 있다."}]
    loop = out["loop"]
    assert loop["stopped"] is None and loop["vendor"] == vendor and loop["model"] == MODELS[vendor]
    assert loop["map"]["turns"] == 1 and loop["map"]["dropped_files"] == 1 and loop["map"]["failed"] == ""
    sub = loop["requirements"][0]
    assert sub["status"] == "verdict" and sub["turns"] == 2 and sub["candidates"] == ["app.py"]
    assert sub["tool_calls"] == {"read_file": 1}
    assert sub["usage"] == {"requests": 2, "input_tokens": 200, "output_tokens": 20, "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert loop["usage"]["requests"] == 3
    # 하위 루프는 새 문맥이다 — 첫 요청에 지도 단계의 대화가 없고, 그 요구사항과 후보만 있다.
    first_sub = next(r for r in proxy.requests if "submit_plan" not in json.dumps(r.get("tools")))
    assert "파일 트리" not in json.dumps(first_sub, ensure_ascii=False)
    assert "requirement_id 7" in json.dumps(first_sub, ensure_ascii=False)
    assert "- app.py" in json.dumps(first_sub, ensure_ascii=False)
    # read_file 결과는 줄 번호가 붙는다.
    assert proxy.tool_results[7][0].splitlines()[2] == "3\tdef login(user):"


def test_requirements_run_in_separate_contexts(tmp_path: Path) -> None:
    script = {
        "map": [[Call("submit_plan", {"plans": [{"requirement_id": 1, "files": ["app.py"]}]})]],
        1: [GOOD],
        2: [[Call("submit_verdict", {"met": False, "evidence": [], "reason": "없다."})]],
    }
    result, proxy = _run(tmp_path, "openai", script, requirements=[{"id": 1, "text": "로그인"}, {"id": 2, "text": "결제"}])

    out = _loop(result)
    assert sorted(v["requirement_id"] for v in out["verdicts"]) == [1, 2]
    assert out["loop"]["requirements"][1]["candidates"] == []
    assert proxy.calls_for(1) == 1 and proxy.calls_for(2) == 1


# ── 근거 확인 ───────────────────────────────────────────────────────────────────────────────────────────


@vendors
def test_import_line_evidence_is_asked_again_with_the_real_lines_then_fixed(tmp_path: Path, vendor: str) -> None:
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [IMPORT_ONLY, GOOD]})

    out = _loop(result)
    assert out["verdicts"][0]["met"] is True and out["verdicts"][0]["evidence"] == ["app.py:3-4"]
    sub = out["loop"]["requirements"][0]
    assert sub["evidence_retries"] == 1 and sub["evidence_dropped"] == 1 and sub["status"] == "verdict"
    retry = proxy.tool_results[7][-1]
    assert "app.py:1" in retry and "주석·import" in retry and "1\timport os" in retry


@vendors
def test_evidence_wrong_three_times_becomes_unmet_with_unverifiable_reason(tmp_path: Path, vendor: str) -> None:
    missing = [Call("submit_verdict", {"met": True, "evidence": ["nope.py:3"], "reason": "있다."})]
    out_of_range = [Call("submit_verdict", {"met": True, "evidence": ["app.py:40"], "reason": "있다."})]
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [missing, out_of_range, IMPORT_ONLY, GOOD]})

    out = _loop(result)
    verdict = out["verdicts"][0]
    assert verdict["met"] is False and verdict["evidence"] == []
    assert verdict["reason"].startswith("근거 확인 불가")
    sub = out["loop"]["requirements"][0]
    assert sub["status"] == "evidence_unverified" and sub["evidence_retries"] == 2 and sub["evidence_dropped"] == 3
    assert proxy.calls_for(7) == 3, "세 번째도 틀리면 더 묻지 않는다"
    assert "그런 파일이 없다" in proxy.tool_results[7][0]
    assert "파일 밖" in proxy.tool_results[7][1]


def test_evidence_check_rejects_blank_comment_import_and_outside_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.ts").write_text("import x from 'y';\n\n// 주석\nexport function pay() {\n  return charge();\n}\n")
    tools = selfloop.RepoTools(root)

    assert selfloop.check_evidence(tools, ["a.ts:4-5", "a.ts:1-5"]) == []
    bad = selfloop.check_evidence(tools, ["a.ts:1-3", "a.ts", "../x.py:1", "a.ts:5-4"])
    assert len(bad) == 4
    assert "주석·import" in bad[0] and "줄 번호" in bad[1] and "루트 밖" in bad[2] and "파일 밖" in bad[3]


# ── 꼴 검사 ─────────────────────────────────────────────────────────────────────────────────────────────


@vendors
def test_broken_verdict_shape_is_asked_again_then_accepted(tmp_path: Path, vendor: str) -> None:
    broken = [Call("submit_verdict", {"met": "네", "evidence": "app.py:3", "reason": ""})]
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [broken, GOOD]})

    out = _loop(result)
    assert out["verdicts"][0]["met"] is True
    assert out["loop"]["requirements"][0]["schema_retries"] == 1
    error = proxy.tool_results[7][0]
    assert "met 은 true/false" in error and "evidence 는 문자열 배열" in error and "reason" in error


def test_unparseable_arguments_three_times_leave_the_requirement_unresolved(tmp_path: Path) -> None:
    result, proxy = _run(tmp_path, "openai", {"map": [PLAN], 7: [[Call("submit_verdict", "{met: yes")]]})

    out = _loop(result)
    assert out["verdicts"] == []
    sub = out["loop"]["requirements"][0]
    assert sub["status"] == "unresolved" and sub["schema_retries"] == 2 and "꼴" in sub["problem"]
    assert proxy.calls_for(7) == 3


@vendors
def test_text_only_answer_is_nudged_once(tmp_path: Path, vendor: str) -> None:
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [Say("충족입니다."), GOOD]})

    out = _loop(result)
    assert out["verdicts"][0]["met"] is True and out["loop"]["requirements"][0]["nudges"] == 1
    last = json.dumps(proxy.requests[-1], ensure_ascii=False)
    assert "submit_verdict 를 불러" in last


def test_text_only_twice_leaves_the_requirement_unresolved(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "anthropic", {"map": [PLAN], 7: [Say("충족입니다.")]})

    sub = _loop(result)["loop"]["requirements"][0]
    assert sub["status"] == "unresolved" and sub["nudges"] == 1 and sub["turns"] == 2


def test_broken_plan_falls_back_to_no_candidates(tmp_path: Path) -> None:
    bad_plan = [Call("submit_plan", {"plans": [{"requirement_id": 99, "files": ["app.py"]}]})]
    result, _ = _run(tmp_path, "anthropic", {"map": [bad_plan], 7: [GOOD]})

    loop = _loop(result)["loop"]
    assert loop["map"]["schema_retries"] == 2 and loop["map"]["turns"] == 3 and "꼴" in loop["map"]["failed"]
    assert loop["requirements"][0]["candidates"] == [] and loop["requirements"][0]["status"] == "verdict"


# ── 도구 · 한도 ─────────────────────────────────────────────────────────────────────────────────────────


@vendors
def test_paths_outside_the_snapshot_are_refused(tmp_path: Path, vendor: str) -> None:
    escape = [
        Call("read_file", {"path": "../../../etc/passwd"}),
        Call("read_file", {"path": "/etc/passwd"}),
        Call("list_dir", {"path": ".."}),
        Call("glob", {"pattern": "../*"}),
    ]
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: [escape, GOOD]})

    assert _loop(result)["verdicts"][0]["met"] is True
    refused = proxy.tool_results[7][:4]
    assert all(r.startswith("거절:") for r in refused), refused
    assert all("root:" not in r for r in refused)


def test_symlink_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("비밀\n")
    os.symlink(secret, root / "link.txt")
    os.symlink(tmp_path, root / "up")
    tools = selfloop.RepoTools(root)

    for path in ("link.txt", "up/secret.txt"):
        with pytest.raises(selfloop.ToolRefused, match="루트 밖"):
            tools.read_file(path, 1, 0)
    assert "비밀" not in tools.grep("비밀", ".", "")
    assert tools.glob("**/*.txt") == "(맞는 파일 없음)"


def test_repeated_reads_are_blocked_and_told(tmp_path: Path) -> None:
    again = [Call("read_file", {"path": "app.py"})]
    same_range = [Call("read_file", {"path": "./app.py", "start_line": 1, "end_line": 0})]
    result, proxy = _run(tmp_path, "anthropic", {"map": [PLAN], 7: [again, again, same_range, GOOD]})

    sub = _loop(result)["loop"]["requirements"][0]
    assert sub["repeat_blocked"] == 2 and sub["tool_calls"] == {"read_file": 3}
    assert "이미" in proxy.tool_results[7][1] and "이미" in proxy.tool_results[7][2]


def test_grep_results_are_capped(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "big.py").write_text("hit\n" * 200)
    out = selfloop.RepoTools(root).grep("hit", ".", "*.py")
    assert out.count("big.py:") == selfloop.GREP_MAX_RESULTS and "더 있다" in out


def test_read_file_stops_at_20kb(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "long.txt").write_text(("가" * 99 + "\n") * 400)
    out = selfloop.RepoTools(root).read_file("long.txt", 1, 0)
    assert len(out.encode("utf-8")) <= selfloop.READ_MAX_BYTES + 200
    assert "이어 읽으려면 start_line=" in out


@vendors
def test_turn_limit_ends_the_subloop_without_a_verdict(tmp_path: Path, vendor: str) -> None:
    wander = [[Call("grep", {"pattern": f"x{i}"})] for i in range(20)]
    result, proxy = _run(tmp_path, vendor, {"map": [PLAN], 7: wander})

    out = _loop(result)
    assert out["verdicts"] == []
    sub = out["loop"]["requirements"][0]
    assert sub["status"] == "unresolved" and sub["turns"] == selfloop.SUBLOOP_MAX_TURNS and "턴 한도" in sub["problem"]
    assert proxy.calls_for(7) == selfloop.SUBLOOP_MAX_TURNS


def test_proxy_budget_429_stops_the_whole_run(tmp_path: Path) -> None:
    reqs = [{"id": 7, "text": "로그인"}, {"id": 8, "text": "결제"}]
    result, proxy = _run(tmp_path, "openai", {"map": [Status(429)], 7: [GOOD], 8: [GOOD]}, requirements=reqs)

    loop = _loop(result)["loop"]
    assert loop["stopped"] == "budget"
    assert [s["status"] for s in loop["requirements"]] == ["unresolved", "unresolved"]
    assert proxy.calls_for(7) == 0 and proxy.calls_for(8) == 0


def test_run_deadline_stops_before_calling(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    ticks = iter([0.0, 0.0, 400.0])
    out = selfloop.run_selfloop(
        vendor="anthropic", model="m", token=TOKEN, system="s", requirements=[{"id": 1, "text": "t"}], root=root,
        transport=lambda *a: pytest.fail("시간이 지났는데 불렀다"), seconds=300, clock=lambda: next(ticks, 400.0),
    )
    assert out["loop"]["stopped"] == "deadline" and out["verdicts"] == []


# ── 계약 ─────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "requirements",
    [None, [], [{"id": "1", "text": "a"}], [{"id": 1, "text": " "}], [{"id": 1, "text": "a"}, {"id": 1, "text": "b"}]],
)
def test_selfloop_spec_needs_a_requirement_list(requirements: object) -> None:
    raw = {"vendor": "openai", "model": "m", "prompt": "p", "output_schema": {}, "run_token": "t", "max_budget_usd": 1,
           "mode": "selfloop", "requirements": requirements}
    with pytest.raises(ar.RunRejected, match="spec_bad_requirements"):
        ar.validate_spec(raw)
    with pytest.raises(ar.RunRejected, match="spec_bad_mode"):
        ar.validate_spec({**raw, "mode": "loop"})


def test_cli_spec_is_unchanged_without_mode() -> None:
    raw = {"vendor": "openai", "model": "m", "prompt": "p", "output_schema": {}, "run_token": "t", "max_budget_usd": 1}
    assert "mode" not in ar.validate_spec(raw)


def test_loop_uses_only_the_standard_library_and_is_copied_into_the_image() -> None:
    tree = ast.parse(Path(selfloop.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots - {"__future__"} <= set(sys.stdlib_module_names)
    dockerfile = (REPO_ROOT / "docker" / "agent-grader.Dockerfile").read_text(encoding="utf-8")
    assert "COPY backend/scoring/selfloop.py /app/selfloop.py" in dockerfile
    ignore = (REPO_ROOT / "docker" / "agent-grader.Dockerfile.dockerignore").read_text(encoding="utf-8")
    assert "!backend/scoring/selfloop.py" in ignore.splitlines()
