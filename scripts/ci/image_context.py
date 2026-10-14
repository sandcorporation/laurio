#!/usr/bin/env python3
"""배포 이미지 하나의 「빌드 문맥 해시」 — 같으면 같은 이미지라 다시 굽지 않는다(#705).

    image_context.py services                         서비스 이름(한 줄에 하나)
    image_context.py field <서비스> <dockerfile|target|dsn|app>
    image_context.py paths <서비스>                   해시에 드는 경로
    image_context.py release <서비스>                 그 경로를 마지막으로 바꾼 커밋(Sentry release)
    image_context.py hash <서비스> <플랫폼> [빌드 인자 파일]
    image_context.py check                            Dockerfile 의 COPY 원본이 전부 문맥에 있는가

`scripts/ci/images.sh` 가 서비스마다 이 해시를 내고, 태그 `ctx-<해시>-<arch|env>` 가 ghcr 에 있으면
굽지 않고 커밋 태그만 그 매니페스트에 더한다. 해시에 드는 것: 아래 표의 경로마다 `git rev-parse
HEAD:<경로>`(트리·blob 해시 — 그 경로 아래 무엇이 바뀌어도 달라진다), Dockerfile, 루트
`.dockerignore`와 (있으면) `docker/<서비스>.Dockerfile.dockerignore`(무엇이 문맥에 드는지를 바꾼다), 빌드 대상·플랫폼, 빌드 인자 값(NEXT_PUBLIC 값이
바뀌면 다시 굽는다).

**가장 위험한 자리는 표가 Dockerfile 보다 좁은 것이다** — Dockerfile 이 읽는 파일이 표에 없으면 그
파일을 고친 커밋이 옛 이미지로 배포된다. 그래서 `check` 와 `scripts/test_image_context.py` 가
Dockerfile 의 `COPY`/`ADD`(다른 단계에서 가져오는 `--from` 은 빼고)·`RUN --mount=type=bind` 원본을
읽어 전부 표 안에 있는지 본다. 표가 넓은 것(쓰지 않는 패키지까지 든다)은 괜찮다 — 덜 건너뛸 뿐이다.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

# 해시 계산 방식을 바꾸면 올린다 — 옛 ctx 태그와 섞이지 않게.
HASH_VERSION = "1"

# 모든 서비스의 문맥에 드는 것(Dockerfile 자신은 서비스마다 더한다).
COMMON_PATHS = (".dockerignore",)

NODE_WORKSPACE = ("packages", "package.json", "pnpm-workspace.yaml", "pnpm-lock.yaml")


@dataclass(frozen=True)
class Service:
    name: str
    paths: tuple[str, ...]
    target: str = ""
    app: bool = False  # Next 앱 — NEXT_PUBLIC_* 가 굳어 환경(staging/prod)마다 따로 굽는다
    dsn: str = ""  # Sentry DSN 변수의 꼬리(STAGING_SENTRY_DSN_<dsn>)

    @property
    def dockerfile(self) -> str:
        return f"docker/{self.name}.Dockerfile"


SERVICES: dict[str, Service] = {
    s.name: s
    for s in (
        Service("backend", ("backend",), dsn="BACKEND"),
        Service("frontend", ("frontend", *NODE_WORKSPACE), target="runner", app=True, dsn="FRONTEND"),
        Service("operator", ("operator", *NODE_WORKSPACE), target="runner", app=True, dsn="OPERATOR"),
        Service("classroom", ("classroom", *NODE_WORKSPACE), target="runner", app=True, dsn="CLASSROOM"),
        Service("search", (), dsn="SEARCH"),
        Service("pgbouncer", ("docker/pgbouncer",), dsn="PGBOUNCER"),
    )
}


def context_paths(service: Service) -> list[str]:
    paths = {*COMMON_PATHS, service.dockerfile, *service.paths}
    # BuildKit 은 `<Dockerfile>.dockerignore` 가 있으면 루트 `.dockerignore` 대신 그것을 쓴다 — 있을 때만
    # 표에 넣는다(지금 있는 것은 ci 이미지의 것뿐이다, #709). 지금 디렉터리(저장소 루트)를 기준으로 본다.
    own_ignore = f"{service.dockerfile}.dockerignore"
    if os.path.exists(own_ignore):
        paths.add(own_ignore)
    return sorted(paths)


# ── Dockerfile 읽기 ─────────────────────────────────────────────────────────


def _instructions(text: str) -> list[str]:
    """줄 잇기(`\\`)를 풀고 주석·빈 줄을 뺀 지시문들."""
    out: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if pending and line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        out.append((pending + line).strip())
        pending = ""
    if pending.strip():
        out.append(pending.strip())
    return out


def copy_sources(dockerfile_text: str) -> list[str]:
    """빌드 문맥에서 읽는 경로 — `COPY`/`ADD` 원본(`--from` 제외)과 `RUN --mount=type=bind` 의 source."""
    found: list[str] = []
    for ins in _instructions(dockerfile_text):
        head, _, rest = ins.partition(" ")
        keyword = head.upper()
        if keyword in ("COPY", "ADD"):
            rest = rest.strip()
            flags: list[str] = []
            while rest.startswith("--"):
                flag, _, rest = rest.partition(" ")
                flags.append(flag)
                rest = rest.strip()
            if any(f.startswith("--from=") for f in flags):
                continue
            if rest.startswith("["):
                args = json.loads(rest)
            else:
                args = shlex.split(rest)
            for src in args[:-1]:
                if keyword == "ADD" and "://" in src:
                    continue
                found.append(src)
        elif keyword == "RUN":
            for token in shlex.split(rest, posix=True):
                if not token.startswith("--mount="):
                    continue
                opts = dict(
                    part.split("=", 1) if "=" in part else (part, "")
                    for part in token[len("--mount=") :].split(",")
                )
                if opts.get("type") == "bind" and "from" not in opts:
                    found.append(opts.get("source") or opts.get("src") or ".")
    return found


def _normalize(path: str) -> str:
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    path = path.rstrip("/")
    return path or "."


def is_covered(source: str, paths: list[str] | tuple[str, ...]) -> bool:
    """`source` 가 `paths` 중 하나 안에 드는가. 와일드카드는 그 앞의 디렉터리로 본다."""
    src = _normalize(source)
    for i, ch in enumerate(src):
        if ch in "*?[":
            src = _normalize(src[:i].rsplit("/", 1)[0] if "/" in src[:i] else ".")
            break
    if src == ".":
        return False  # 문맥 통째 — 어떤 표도 덮지 못한다
    for p in paths:
        p = _normalize(p)
        if src == p or src.startswith(p + "/"):
            return True
    return False


def uncovered(service: Service, dockerfile_text: str) -> list[str]:
    paths = context_paths(service)
    return [s for s in copy_sources(dockerfile_text) if not is_covered(s, paths)]


# ── 해시 ────────────────────────────────────────────────────────────────────


def context_digest(
    objects: dict[str, str], target: str, platform: str, build_args: dict[str, str]
) -> str:
    """순수 함수 — 경로별 git 객체 해시 + 대상 + 플랫폼 + 빌드 인자 → 24자 16진."""
    h = hashlib.sha256()
    h.update(f"v{HASH_VERSION}\n".encode())
    for path in sorted(objects):
        h.update(f"path {path} {objects[path]}\n".encode())
    h.update(f"target {target}\nplatform {platform}\n".encode())
    for key in sorted(build_args):
        h.update(f"arg {key}={build_args[key]}\n".encode())
    return h.hexdigest()[:24]


def parse_build_args(text: str) -> dict[str, str]:
    args: dict[str, str] = {}
    for line in text.splitlines():
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        args[key.strip()] = value
    return args


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", f"safe.directory={os.getcwd()}", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_objects(paths: list[str], rev: str = "HEAD") -> dict[str, str]:
    """경로마다 `rev` 에서의 객체 해시. 없는 경로가 있으면 멈춘다 — 표가 낡았다."""
    objects: dict[str, str] = {}
    for path in paths:
        try:
            objects[path] = _git("rev-parse", "--verify", "--quiet", f"{rev}:{path}")
        except subprocess.CalledProcessError:
            raise SystemExit(f"{rev} 에 {path} 가 없다 — scripts/ci/image_context.py 의 표를 고친다")
    return objects


def release(service: Service) -> str:
    """그 이미지의 문맥을 마지막으로 바꾼 커밋 — 얕은 클론이면 틀린 값이 나오므로 멈춘다."""
    if _git("rev-parse", "--is-shallow-repository") == "true":
        raise SystemExit("얕은 클론이다 — release(경로별 마지막 커밋)를 셀 수 없다. 전체 이력으로 체크아웃한다")
    return _git("log", "-1", "--format=%H", "--", *context_paths(service))


def _service(name: str) -> Service:
    if name not in SERVICES:
        raise SystemExit(f"모르는 서비스: {name} (있는 것: {' '.join(SERVICES)})")
    return SERVICES[name]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "services":
        print("\n".join(SERVICES))
    elif cmd == "field":
        svc = _service(rest[0])
        value = getattr(svc, rest[1])
        print(("true" if value else "false") if isinstance(value, bool) else value)
    elif cmd == "paths":
        print("\n".join(context_paths(_service(rest[0]))))
    elif cmd == "release":
        print(release(_service(rest[0])))
    elif cmd == "hash":
        svc = _service(rest[0])
        platform = rest[1]
        args = parse_build_args(open(rest[2], encoding="utf-8").read()) if len(rest) > 2 else {}
        print(context_digest(git_objects(context_paths(svc)), svc.target, platform, args))
    elif cmd == "check":
        bad = 0
        for svc in SERVICES.values():
            with open(svc.dockerfile, encoding="utf-8") as f:
                missing = uncovered(svc, f.read())
            for src in missing:
                print(f"{svc.dockerfile}: {src} 가 문맥 표에 없다", file=sys.stderr)
            bad += len(missing)
        return 1 if bad else 0
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
