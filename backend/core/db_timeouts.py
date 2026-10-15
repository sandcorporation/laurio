"""요청 경로의 DB 한도 — gthread 에서 걸린 요청을 거두는 장치(#745).

**왜.** gunicorn gthread 의 주 루프는 1초마다 하트비트를 보내므로 `timeout = 30` 이 걸린
요청을 죽이지 않는다(#742). 행 잠금 대기나 느린 쿼리 하나가 스레드를 영구히 쥐면 그 워커는
살아 있는 척 연결을 계속 받아 줄 세운다. sync 시절에는 30초 SIGKILL 이 그 워커를 되살렸다.
그래서 요청 안의 SQL 문에 PostgreSQL 의 `statement_timeout`(25초 — 요청 예산 30초 안)과
`lock_timeout`(5초)을 건다.

**어떻게 — 문마다 `SET LOCAL` 을 함께 보낸다.** 이 미들웨어가 요청 동안 `default` 연결에
`execute_wrapper` 를 걸어, 문 하나를 `SET LOCAL statement_timeout = …; SET LOCAL
lock_timeout = …; <문>` 한 메시지로 보낸다. 다른 길이 막혀서다:

- 접속 파라미터(`OPTIONS["options"] = "-c statement_timeout=…"`): 배포의 풀러
  pgbouncer 1.18(debian bookworm)이 `FATAL: unsupported startup parameter: options` 로
  접속을 거절한다(dev `pgbouncer` 프로필로 확인). `ignore_startup_parameters` 에 넣으면
  거절은 없지만 한도도 조용히 버려진다. 그리고 같은 settings 를 쓰는 celery 도 받는다.
- 연결을 얻은 뒤 세션 `SET`: 풀러가 트랜잭션 모드라 트랜잭션마다 다른 서버 연결로 갈 수
  있고, `server_reset_query_always = 1` 이 반납 때마다 `DISCARD ALL` 로 지운다 — 다음
  문에는 남지 않는다.
- 역할 수준(`ALTER ROLE … SET`): celery 도 같은 사용자라 가르지 못한다.

`SET LOCAL` 은 그 문이 든 트랜잭션(autocommit 이면 한 메시지의 암묵 트랜잭션, `atomic`
안이면 그 트랜잭션)과 함께 끝나므로 서버 연결이 다음 클라이언트로 넘어가도 따라가지 않고,
같은 메시지라 풀러가 둘을 다른 서버 연결로 가를 수도 없다. 왕복은 늘지 않는다 — Django 의
psycopg3 기본 커서(`ClientCursor`)가 인자를 클라이언트에서 합쳐 단순 질의 프로토콜로 보내므로
여러 문을 한 메시지에 실을 수 있다. 실행 뒤에는 앞의 두 `SET` 결과를 넘겨 마지막 문의
결과에 커서를 둔다.

**요청 경로에만.** 미들웨어라 celery 태스크 본체·관리 명령·마이그레이션은 지나지 않는다 —
채점(몇 분)·백업 같은 긴 일이 거기 있다. 다만 **요청으로 도는 일은 걸린다**: celery beat 의
스캔은 태스크가 `/api/internal/scans/{name}` 을 HTTP 로 부르는 것이라(ADR-0003, `core/tasks.py`)
스캔 본체가 요청 안에서 돌고, e2e 시드도 시드 엔드포인트 안의 `call_command` 다. 스캔이 잠금을
5초 넘게 기다리면 500 이 되고, 태스크는 `HTTPError` 를 재시도하지 않아 다음 beat 로 밀린다.
그래도 지금 그런 스캔은 없다(#747 점검) — 스캔은 한 번에 후보 몇십 개를 문 여러 개로 나눠
돌고, 스캔이 기다릴 수 있는 행 잠금(공모전·분배 몫·인계·판매자)은 벤더 호출을 잠금 밖에 두는
규율(#127) 덕에 짧은 DB 쓰기 동안만 잡힌다. 그래서 뷰별로 한도를 늘리는 장치는 두지 않았다.

**요청 안에서 한도를 따로 걸면 다음 문에서 덮인다.** `SET LOCAL lock_timeout = …` 이나
`set_config('lock_timeout', …, true)` 를 요청 안에서 내면, 이 래퍼가 그다음 문 앞에 붙이는
`SET LOCAL` 이 같은 트랜잭션의 값을 이 모듈의 값으로 되돌린다. 지금 그렇게 거는 유일한 자리인
`classroom/scoring.py` 의 `_short_lock_timeout` 은 배포에서는 상주 grader(`manage.py grader`)
에서만 돌아 요청을 지나지 않는다. 다만 pytest 에서는 `CLASSROOM_GRADER_INLINE`(시험 동안 켜짐)
때문에 즉시 채점 요청 안에서 `grade_inline` 으로 돌아, 그 300ms 가 다음 문의 접두(5000ms)에
덮인다(값을 0 으로 해도 접두가 `lock_timeout = 0` 으로 덮는다) — HTTP 로 그 짧은 한도를
재는 시험은 지금 쓸 수 없다. 요청 안에서 다른 한도가 필요해지면 문 하나의 SQL 에 직접 싣지 말고
이 미들웨어에 그 뷰의 예외를 먼저 만든다. 비동기 요청(이벤트 서비스의 실시간 스트림)도 그대로
통과시킨다 — DB 를 다른 스레드에서 쓰고, 스트림은 원래 길게 열린다. `executemany`, 스트리밍
응답 본문을 만드는 동안의 문, 서버측 커서(배포는 풀러 때문에 꺼 둔다)에도 걸리지 않는다.

**끊기면.** psycopg 의 `QueryCanceled`(`canceling statement due to statement timeout`)
또는 `LockNotAvailable`(`canceling statement due to lock timeout`)이 Django 의
`OperationalError` 로 올라와 500 이 되고 GlitchTip 에 잡힌다. 값은 settings 의
`CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS`·`CODEMIT_REQUEST_LOCK_TIMEOUT_MS`(0 이면 끔).
"""

from __future__ import annotations

import psycopg
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.db import connections

_ALIAS = "default"


def _prefix() -> str:
    statement_ms = int(settings.CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS)
    lock_ms = int(settings.CODEMIT_REQUEST_LOCK_TIMEOUT_MS)
    return (
        f"SET LOCAL statement_timeout = {statement_ms}; "
        f"SET LOCAL lock_timeout = {lock_ms}; "
    )


def _limit_statement(execute, sql, params, many, context):
    raw = context["cursor"].cursor
    # 서버측 커서(`QuerySet.iterator()`, 풀러가 없는 dev·CI 에서만 열린다)는 문을
    # `DECLARE … CURSOR FOR <문>` 으로 감싸므로 앞에 붙일 수 없다 — 그대로 보낸다.
    # 실패한 트랜잭션 안에서는 `ROLLBACK TO SAVEPOINT` 말고는 받지 않는다 — 앞에 붙인 SET 이
    # 「current transaction is aborted」로 먼저 거절돼 atomic 의 savepoint 롤백이 막힌다.
    if (
        many
        or not isinstance(sql, str)
        or isinstance(raw, psycopg.ServerCursor)
        or raw.connection.info.transaction_status == psycopg.pq.TransactionStatus.INERROR
    ):
        return execute(sql, params, many, context)
    prefix = _prefix()
    try:
        result = execute(prefix + sql, params, many, context)
        # 앞의 두 SET 결과를 넘겨 커서를 마지막 문의 결과에 둔다. 뒤 문의 오류(IntegrityError
        # 등)는 여기까지 오지 않는다 — psycopg 가 `execute` 안에서 한 메시지의 결과 전부를 보고
        # 바로 던지고, Django 의 `_execute` 가 그것을 이미 Django 오류로 바꿔 올린다.
        raw.nextset()
        raw.nextset()
        return result
    finally:
        _hide_prefix(raw, prefix)


def _hide_prefix(raw, prefix: str) -> None:
    """Django 가 기록하는 SQL(`connection.queries`·`CaptureQueriesContext`)에서 접두를 벗긴다.

    Django 는 그 SQL 을 psycopg 커서가 실제로 보낸 문(`cursor._query.query`)에서 읽는다
    (`last_executed_query`). 접두가 남으면 질의 모양·횟수를 재는 시험과 느린 질의 로그가 모두
    `SET LOCAL …` 로 시작해 읽히지 않으므로, 기록되는 쪽에는 원문만 남긴다 — 이 래퍼가 기록
    직전에 도는 유일한 자리라 여기서 한 번만 한다.
    """

    query = getattr(raw, "_query", None)
    encoded = prefix.encode()
    if query is not None and isinstance(query.query, bytes) and query.query.startswith(encoded):
        query.query = query.query[len(encoded) :]


class RequestDbTimeoutMiddleware:
    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._async = iscoroutinefunction(get_response)
        if self._async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._async:
            return self.get_response(request)
        with connections[_ALIAS].execute_wrapper(_limit_statement):
            return self.get_response(request)
