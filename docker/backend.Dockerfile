# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1

# 가상환경을 /app 밖에 둔다. dev compose가 소스를 /app에 바인드 마운트하므로
# 안에 두면 마운트가 가려버린다.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 상장 PDF(#1126, certificates/rendering.py) 를 그리는 WeasyPrint 가 부르는 시스템 라이브러리 —
# pango(글자 배치)와 harfbuzz-subset(PDF 에 넣을 글꼴 서브셋, 없으면 fontTools 로 돌아 몇 배 느리다).
# 글꼴은 저장소에 담긴 것만 쓰므로 시스템 글꼴 패키지는 넣지 않는다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
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
