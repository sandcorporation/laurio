# syntax=docker/dockerfile:1
#
# 에이전트 채점 실행기(#999) — Claude Code·Codex CLI 를 고정 버전으로 담고, 실행 틀
# (`backend/scoring/agent_runner.py`, 표준 라이브러리만)이 HTTP 로 실행을 받는다. 키·자격증명은 없다 — 실행마다
# 받는 일회용 토큰과 `llm-proxy`(#998)만 쓴다. 운영 호스트가 arm64 라 그대로 arm64 로 굽는다(image.yml).
#
# 바탕은 backend 이미지와 같은 uv 파이썬 이미지(실행 틀이 파이썬이다), Node 는 앱 이미지와 같은 node:22 에서
# 가져온다(ci.Dockerfile 과 같은 모양). 두 CLI 는 npm 패키지가 플랫폼별 네이티브 바이너리를 optional 의존으로
# 들고 있다 — linux-arm64·linux-x64 모두 있다.
FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS node

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1

# 버전은 `agent_runner.py` 의 CLAUDE_CODE_VERSION·CODEX_VERSION 과 같아야 한다(test_agent_runner.py 가 견준다).
ARG CLAUDE_CODE_VERSION=2.1.328
ARG CODEX_VERSION=0.170.0

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules

# rg·bubblewrap 은 Codex 가 제 패키지(플랫폼별 vendor/)에 들고 있다 — apt 로 더 넣지 않는다. Codex 의 셸은 env 를
# 물려받지 않아(`inherit="none"`) 고정 PATH(`/usr/local/bin:/usr/bin:/bin`)만 보므로 그 rg 를 /usr/local/bin 에 잇는다.
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g --no-fund --no-audit --no-update-notifier \
        "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "@openai/codex@${CODEX_VERSION}" \
    && npm cache clean --force \
    && rm /usr/local/bin/npm \
    && rg_path=$(find /usr/local/lib/node_modules/@openai/codex -path '*/codex-path/rg' -type f | head -n 1) \
    && test -n "$rg_path" && ln -s "$rg_path" /usr/local/bin/rg && rg --version \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin grader

COPY backend/scoring/agent_runner.py /app/agent_runner.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENT_GRADER_WORK_ROOT=/work

USER grader
WORKDIR /work
EXPOSE 8003

CMD ["python3", "/app/agent_runner.py", "serve"]
