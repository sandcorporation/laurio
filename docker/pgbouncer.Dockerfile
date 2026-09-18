# Postgres 앞 연결 풀러(pgbouncer, #453/#457) — 트랜잭션 모드로 쓴다.
#
# 벤더 이미지(예: edoburu/pgbouncer)에 기대지 않고 Debian 패키지로 설치한다 —
# 그 패키지가 amd64·arm64 양쪽에 있으므로, backend·search 이미지(docker/
# backend.Dockerfile, docker/search.Dockerfile)와 같은 Dockerfile 하나로 CI
# 이미지 매트릭스(#458)가 두 아키텍처를 굽는다.
#
# 설정은 빌드 시점이 아니라 컨테이너 기동 시점에 환경변수에서 만든다
# (docker-entrypoint.sh) — dev·staging·prod 가 가리키는 실제 DB 호스트가
# 다르기 때문이다(search 의 DISABLE_SECURITY_PLUGIN 처럼 "이미지는 하나,
# 런타임 값으로 갈린다"는 같은 관용구).
FROM debian:bookworm-slim

# netcat-openbsd 는 compose 헬스체크(`nc -z`)용이다 — pgbouncer 자신은 ping
# 명령을 주지 않는다.
RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbouncer netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

COPY docker/pgbouncer/docker-entrypoint.sh /docker-entrypoint.sh

# pgbouncer 는 root 로 뜨는 것을 스스로 거부한다("PgBouncer should not run as
# root"). Debian 패키지가 postgresql-common 의존성으로 이미 만들어 둔
# `postgres` 시스템 계정을 그대로 쓴다 — 이 이미지에 실제 Postgres 서버가 있는
# 것은 아니라 이름이 어색하지만, 전용 유저를 새로 만드는 것보다 패키지가 이미
# 준비한 계정을 재사용하는 편이 유지비가 적다.
RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /etc/pgbouncer \
    && chown postgres:postgres /etc/pgbouncer

USER postgres

EXPOSE 6432

ENTRYPOINT ["/docker-entrypoint.sh"]
