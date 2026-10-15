"""시험 DB 를 워커마다 마이그레이션하지 않고 템플릿에서 복제한다 (#755).

pytest-django 는 xdist 워커마다 제 시험 DB(`test_codemit_<해시>_gwN`)를 새로 만들어
마이그레이션을 전부 돌린다 — 약 7.5초이고 세션 픽스처라 **각 워커가 맨 처음 집는
시험 하나**의 setup 에 붙는다(CI 는 워커 12개, 합 90초). 여기서는 한 워커가 템플릿
DB(`test_codemit_<해시>_tpl`)를 만들어 마이그레이션하고, 나머지(그리고 그 워커
자신)는 `CREATE DATABASE … TEMPLATE` 로 복제한다(1초 미만).

- **누가 먼저 만드나**는 Postgres 자문 잠금(`pg_advisory_xact_lock`)이 가른다 —
  파일 잠금이 아니라서 호스트·컨테이너 어디서 돌든 같은 DB 를 보는 모두가 같은 잠금을
  본다. 트랜잭션 잠금인 이유: 세션 잠금은 트랜잭션 모드 풀러(pgbouncer) 뒤에서 문장마다
  다른 서버 연결에 떨어질 수 있다. 잠금을 쥔 연결은 `postgres` DB 에 붙어 있고 템플릿을
  만드는 일은 다른 연결이 하므로, `CREATE DATABASE`(트랜잭션 안에서 못 돈다)와
  부딪히지 않는다.
- **이 세션의 것인가**는 템플릿 DB 의 COMMENT 에 적은 세션 표(token)로 안다. 표는
  컨트롤러가 한 번 만들어 `workerinput` 으로 워커에 준다(`-n 0` 이면 제 프로세스의 것).
  지난 실행이 남긴 템플릿은 표가 달라 다시 만든다 — `--reuse-db` 처럼 묵은 스키마를
  쓰는 일이 없다.
- **xdist 컨트롤러가 워커를 띄우는 동안 미리 만든다**(`tests/conftest.py` 의 sessionstart,
  워커는 그동안 수집한다). 워커가 각자 잠금 앞에서 기다리면 그 기다림이 워커마다 첫 시험의
  setup 에 붙어 junit 이 여전히 「느린 시험 12건」을 보인다. `-n 0` 은 기다리는 워커가 없으니
  픽스처가 처음 쓰일 때 만든다 — DB 를 안 쓰는 실행이 값을 치르지 않는다. 워커의 픽스처도
  같은 길을 품고 있어 컨트롤러가 못 만든 경우(표가 없다)에도 선다.
- 템플릿에 연결이 남아 있으면 복제가 거절되므로 만든 뒤 연결을 닫는다. 컨트롤러가 세션
  끝에 템플릿을 지운다(`tests/conftest.py`) — 워커가 전부 내려간 뒤다.
- 두 체크아웃이 동시에 돌아도 템플릿 이름은 `_default_test_db_name()`(경로 해시)에서
  나오므로 겹치지 않는다 — 워커 DB 이름과 같은 꼴이다.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

TEMPLATE_SUFFIX = "_tpl"
WORKERINPUT_KEY = "codemit_test_db_token"

# 컨트롤러(또는 -n 0 의 단일 프로세스)의 세션 표. 워커 프로세스에서도 임포트 시점에
# 하나 생기지만 쓰이지 않는다 — `session_token()` 이 workerinput 의 것을 먼저 본다.
_CONTROLLER_TOKEN = uuid.uuid4().hex


def session_token(config) -> str:
    """이 pytest 세션의 표 — 컨트롤러와 모든 워커가 같은 값을 본다."""

    workerinput = getattr(config, "workerinput", None)
    if workerinput:
        return workerinput[WORKERINPUT_KEY]
    return _CONTROLLER_TOKEN


def template_db_name(test_db_name: str, worker_id: str | None) -> str:
    """워커 DB 이름(`…_gwN`)에서 접미사를 떼고 `_tpl` 을 붙인다. 워커가 없으면 그대로."""

    base = test_db_name
    if worker_id and base.endswith(f"_{worker_id}"):
        base = base[: -len(worker_id) - 1]
    return base + TEMPLATE_SUFFIX


def ensure_template(connection, template: str, token: str, build: Callable[[], None]) -> bool:
    """`template` 이 이 세션(`token`)의 것이 되게 한다. 만들었으면 True, 이미 있었으면 False.

    잠금을 쥔 동안 `build()` 가 템플릿을 만든다(다른 연결로). 잠금은 `postgres` DB 에
    붙은 별도 연결의 트랜잭션에 걸린다(모듈 docstring).
    """

    with connection._nodb_cursor() as cursor:
        with cursor.db.connection.transaction():
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [template])
            cursor.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
                [template],
            )
            row = cursor.fetchone()
            if row is not None and row[0] == token:
                return False
            build()
            cursor.execute(
                f"COMMENT ON DATABASE {connection.ops.quote_name(template)} IS %s", [token]
            )
            return True


def build_template(connections, template: str, *, verbosity: int) -> None:
    """Django 의 보통 길(`create_test_db`: CREATE → migrate → createcachetable)을 템플릿 이름으로 한 번 돈다.

    지난 실행의 템플릿이 남아 있으면 먼저 지운다(표가 다르다). 끝나면 연결을 닫고 설정을
    되돌린다 — 템플릿에 연결이 남아 있으면 복제가 거절된다.
    """

    from django.conf import settings

    conn = connections["default"]
    old_name = conn.settings_dict["NAME"]
    old_test_name = conn.settings_dict["TEST"]["NAME"]
    with conn._nodb_cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {conn.ops.quote_name(template)}")
    conn.settings_dict["TEST"]["NAME"] = template
    try:
        conn.creation.create_test_db(verbosity=verbosity, autoclobber=True, serialize=False)
    finally:
        conn.settings_dict["TEST"]["NAME"] = old_test_name
        conn.close()
        settings.DATABASES[conn.alias]["NAME"] = old_name
        conn.settings_dict["NAME"] = old_name


def prebuild_template(connections, *, token: str, verbosity: int) -> str:
    """xdist 컨트롤러가 워커를 띄우는 동안 템플릿을 미리 만든다(`tests/conftest.py` 의 sessionstart).

    워커가 각자 잠금 앞에서 기다리면 그 기다림이 워커마다 첫 시험의 setup 에 붙어, junit 이
    여전히 「느린 시험 12건」을 보인다. 컨트롤러가 먼저 만들면 워커의 몫은 복제(1초 미만)뿐이다.
    """

    conn = connections["default"]
    template = template_db_name(conn.creation._get_test_db_name(), None)
    ensure_template(
        conn, template, token, lambda: build_template(connections, template, verbosity=verbosity)
    )
    return template


def setup_test_databases(connections, *, token: str, worker_id: str | None, verbosity: int) -> list:
    """pytest-django 의 `django_db_setup` 이 부르는 몸통. `teardown_databases` 에 넘길 old_config 를 돌려준다.

    템플릿이 아직 이 세션의 것이 아니면(`-n 0`, 또는 컨트롤러가 못 만든 경우) 여기서 만든다.
    "default" 만 만들고 그 거울(`TEST["MIRROR"]`, settings 의 "monitor")은 Django 가 하듯
    같은 이름을 가리키게 한다. 직렬화(`serialized_rollback`)는 쓰는 시험이 없어 하지 않는다.
    """

    from django.conf import settings

    conn = connections["default"]
    old_name = conn.settings_dict["NAME"]
    worker_db = conn.creation._get_test_db_name()
    template = template_db_name(worker_db, worker_id)
    quote = conn.ops.quote_name

    ensure_template(
        conn, template, token, lambda: build_template(connections, template, verbosity=verbosity)
    )

    with conn._nodb_cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {quote(worker_db)}")
        cursor.execute(f"CREATE DATABASE {quote(worker_db)} TEMPLATE {quote(template)}")

    settings.DATABASES[conn.alias]["NAME"] = worker_db
    conn.settings_dict["NAME"] = worker_db
    for alias in connections:
        if connections[alias].settings_dict["TEST"].get("MIRROR") == conn.alias:
            connections[alias].creation.set_as_test_mirror(conn.settings_dict)
    conn.ensure_connection()
    return [(conn, old_name, True)]


def drop_template(settings_dict: dict, template: str) -> None:
    """세션 끝에 컨트롤러가 템플릿을 지운다 — 최선을 다하되 실패해도 시험 결과를 바꾸지 않는다.

    Django 연결을 쓰지 않는다: 컨트롤러에서는 pytest-django 의 DB 차단이 켜져 있어
    `ensure_connection` 이 막힌다. 접속값만 빌려 `postgres` DB 에 직접 붙는다.
    """

    import psycopg

    try:
        with psycopg.connect(
            host=settings_dict["HOST"],
            port=settings_dict["PORT"],
            user=settings_dict["USER"],
            password=settings_dict["PASSWORD"],
            dbname="postgres",
            autocommit=True,
            connect_timeout=5,
        ) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{template}"')
    except Exception:  # noqa: BLE001 - 이미 없거나 DB 가 내려간 뒤다
        pass
