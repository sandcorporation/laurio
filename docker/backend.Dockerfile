# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# 가상환경을 /app 밖에 둔다. dev compose가 소스를 /app에 바인드 마운트하므로
# 안에 두면 마운트가 가려버린다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 락파일만 먼저 복사해 의존성 레이어를 캐시한다. 소스가 바뀌어도 재설치하지 않는다.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

COPY backend/ ./

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
