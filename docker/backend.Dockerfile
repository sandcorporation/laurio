# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

# 가상환경을 /app 밖에 둔다. dev compose가 소스를 /app에 바인드 마운트하므로
# 안에 두면 마운트가 가려버린다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# pg_dump 17 — 매일 새벽 2시 DB 백업(core.backups)이 쓴다. DB 가 postgres:17 인데 bookworm 의
# 기본 postgresql-client 는 15 라 17 서버를 덤프하지 못한다("server version mismatch").
# PGDG 저장소에서 클라이언트만 설치한다. backend·celery-worker·beat·events 가 같은 이미지라
# 워커에도 들어간다. 소스보다 앞에 둬 레이어 캐시가 오래 산다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 락파일만 먼저 복사해 의존성 레이어를 캐시한다. 소스가 바뀌어도 재설치하지 않는다.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

COPY backend/ ./

# 문법 검사(#409)가 쓰는 tree-sitter 문법을 이미지에 넣는다. tree-sitter-language-pack 은
# 문법을 설치 때가 아니라 처음 쓸 때 인터넷에서 받으므로, 이 단계가 없으면 새 컨테이너의
# 첫 채점이 GitHub 에 기대다 파싱 시간 제한에 걸린다(2026-09-15 CI 에서 드러났다). 채점
# 중에는 내려받지 않고, 없는 문법의 파일은 AI 판정으로 넘긴다(classroom/syntax_check.py).
# 캐시 위치를 /app 밖에 둔다 — dev compose 가 /app 을 바인드 마운트한다.
ENV XDG_CACHE_HOME=/opt/codemit-cache
# 받은 묶음 압축본(bundles/)은 풀린 뒤 쓰이지 않는다 — 이미지에서 뺀다(약 60MB).
RUN python manage.py prefetch_syntax_grammars --skip-checks \
    && rm -rf /opt/codemit-cache/tree-sitter-language-pack/*/bundles

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
