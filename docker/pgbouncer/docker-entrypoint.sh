#!/bin/sh
# pgbouncer 설정을 컨테이너 기동 시점에 환경변수로 만든다(#457). 이미지는 하나,
# dev·staging·prod 는 POSTGRES_HOST/POSTGRES_USER 등만 다르게 준다 — backend가
# 이미 읽는 것과 같은 이름이라 compose 의 postgres 환경 앵커를 그대로 나눠 쓴다.
set -eu

: "${POSTGRES_HOST:?POSTGRES_HOST 가 필요하다 — 실제 Postgres 컨테이너/호스트 이름}"
: "${POSTGRES_USER:?POSTGRES_USER 가 필요하다}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD 가 필요하다}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
PGBOUNCER_LISTEN_PORT="${PGBOUNCER_LISTEN_PORT:-6432}"
# 부모 스펙(#453)이 못박은 값 — 트랜잭션 모드로 쓴다. 세션 모드로 바꾸면
# Django 쪽의 DISABLE_SERVER_SIDE_CURSORS 완화는 더 이상 필요 없어지지만,
# 그러면 애초에 이 티켓이 존재하는 이유(동시 연결이 실제 DB 연결 수만큼
# 늘지 않는 것)가 사라진다 — 바꾸려면 그 트레이드오프를 먼저 다시 판단한다.
PGBOUNCER_POOL_MODE="${PGBOUNCER_POOL_MODE:-transaction}"
PGBOUNCER_MAX_CLIENT_CONN="${PGBOUNCER_MAX_CLIENT_CONN:-200}"
PGBOUNCER_DEFAULT_POOL_SIZE="${PGBOUNCER_DEFAULT_POOL_SIZE:-20}"

CONFIG_DIR=/etc/pgbouncer
mkdir -p "$CONFIG_DIR"

# 클라이언트가 실제로 보내는 비밀번호는 검사하지 않지만(auth_type=plain 이
# 아니라 아래처럼 매 유저 항목이 하나뿐이라 사실상 고정값이다), pgbouncer가
# **뒤(backend Postgres)에 붙을 때** 쓸 비밀번호는 여기서 알아야 한다 — 처음에
# auth_type=trust + 이 파일 없이 시도했더니 "no such user"로 거부됐다: trust는
# 클라이언트 인증을 건너뛸 뿐, 백엔드 접속용 자격증명 조회(userlist)는 여전히
# 요구한다. 그래서 auth_type은 plain이고, 클라이언트도 이 비밀번호(=실제
# Postgres 비밀번호와 같다)를 그대로 보내야 붙는다 — "인증이 없다"가 아니라
# "직접 Postgres에 붙을 때와 같은 자격증명을 요구한다"이다.
cat > "$CONFIG_DIR/userlist.txt" <<LIST
"${POSTGRES_USER}" "${POSTGRES_PASSWORD}"
LIST
chmod 600 "$CONFIG_DIR/userlist.txt"

cat > "$CONFIG_DIR/pgbouncer.ini" <<INI
[databases]
; "*" — 요청된 dbname 을 그대로 실제 Postgres 에 전달한다(와일드카드).
; 앱(POSTGRES_DB)이 무슨 이름을 요구하든(dev 는 codemit, 라이브 테스트가
; 만드는 일회용 이름 포함) 여기서 이름을 하드코딩하지 않아도 된다.
* = host=${POSTGRES_HOST} port=${POSTGRES_PORT}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = ${PGBOUNCER_LISTEN_PORT}
auth_type = plain
auth_file = ${CONFIG_DIR}/userlist.txt
pool_mode = ${PGBOUNCER_POOL_MODE}
max_client_conn = ${PGBOUNCER_MAX_CLIENT_CONN}
default_pool_size = ${PGBOUNCER_DEFAULT_POOL_SIZE}
; Django(psycopg3)가 접속 때 보내는 시작 파라미터 중 하나 — 모르는 파라미터를
; 세션마다 다시 SET 하려 들면 트랜잭션 모드에서 깨진다(연결이 요청마다 다른
; 서버 세션으로 갈릴 수 있어서다). pgbouncer 문서가 권장하는 값 그대로다.
ignore_startup_parameters = extra_float_digits
; 트랜잭션이 끝나 실제 연결을 반납할 때마다 DISCARD ALL 을 강제한다 — 세션
; 모드라면 없어도 되지만, 트랜잭션 모드에서는 그 연결이 곧바로 다른 클라이언트
; 몫이 될 수 있다. 없으면 한 클라이언트가 만든 임시 테이블(CREATE TEMP TABLE)·
; 세션 수준 SET·advisory lock 이 다음 클라이언트에게 그대로 남을 수 있다 —
; pgbouncer 문서가 트랜잭션 모드의 표준 권장값으로 못박은 설정이라 여기서는
; 직접 재현하지 않고 그 권장을 그대로 따른다(#457에서 실제로 재현·확인한 것은
; 서버측 커서 하나뿐이다 — 위 config/settings.py 의 DISABLE_SERVER_SIDE_CURSORS
; 주석 참고).
server_reset_query = DISCARD ALL
server_reset_query_always = 1
; 연결·끊김을 한 줄씩 찍지 않는다(2026-09-21). 트랜잭션 모드에서는 요청마다 짧은
; 연결이 드나들어, prod 로그를 Loki 로 모으자마자 이 풀러가 **시간당 492줄**로 전체의
; 절반 가까이를 차지한 것이 보였다 — 그중 진단에 쓰인 줄은 없었다. 연결 문제는
; 분당 한 줄씩 나오는 stats 줄(대기 클라이언트·평균 대기 시간)이 그대로 보여준다.
log_connections = 0
log_disconnections = 0
; 서버 로그인이 한 번 실패하면 다시 시도하기까지 기다리는 초(기본 15). 그동안
; 기다리던 클라이언트는 곧바로 「server login has been failing, try again later
; (server_login_retry)」를 받는다 — 배포가 db 를 다시 만들 때 0.4초 비었던 DB 가
; 15초짜리 장애가 됐다(GlitchTip 오류 68, 재현은 backend/tests/
; test_pgbouncer_config.py). 1초면 DB 가 돌아온 다음 초에 붙는다.
server_login_retry = 1
INI

exec pgbouncer "$CONFIG_DIR/pgbouncer.ini"
