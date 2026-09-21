"""연결 풀러(pgbouncer)가 DB 재시작 한 번을 15초짜리 장애로 늘리지 않는다
(GlitchTip 오류 68).

배포가 `db` 컨테이너를 다시 만들면(compose 설정이 바뀐 배포 — 2026-09-21 의
로그 회전이 그랬다) Postgres 가 내려가는 순간 풀러의 새 서버 로그인이
「the database system is shutting down」으로 거절된다. pgbouncer 는 그 뒤
`server_login_retry`(기본 15초) 동안 새 로그인을 시도하지 않고 기다리던
클라이언트에게 곧바로 「server login has been failing, try again later
(server_login_retry)」를 돌려준다 — DB 는 이미 돌아와 있는데도.

재현(임시 postgres:17 + 이 이미지의 풀러, 스레드 여덟이 0.1초 간격으로 질의):
`docker stop`/`start` 로 DB 가 0.4초 비는 동안 세 번 중 두 번 이 오류가 났고,
DB 가 돌아온 뒤 **15초 동안** 800~900건이 계속 실패했다. 실제 풀러를 띄우는
재현은 docker 가 필요해 스위트에 넣지 않고, 여기서는 그 값을 설정이 짧게
고정하는지만 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "pgbouncer" / "docker-entrypoint.sh"


def test_pgbouncer_retries_a_failed_server_login_within_seconds():
    text = ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(r"^server_login_retry\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    assert match, "server_login_retry 를 적지 않으면 pgbouncer 기본값 15초가 된다"
    assert int(match.group(1)) <= 2
