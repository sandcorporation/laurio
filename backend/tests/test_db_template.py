"""시험 DB 가 템플릿에서 복제돼 서는지(#755, `tests/db_template.py`·`tests/conftest.py`).

워커마다 마이그레이션을 전부 도는 대신, 한 워커가 템플릿 DB 를 만들고 나머지는
`CREATE DATABASE … TEMPLATE` 로 복제한다. 여기서는 그 결과 — 지금 붙어 있는 DB 가
템플릿이 아닌 복제본이고, 템플릿에는 이 세션의 표가 붙어 있으며 연결이 남아 있지
않다는 것 — 와 「한 세션에 한 번만 만든다」는 잠금의 계약을 본다.
"""

import pytest
from django.db import connections

from tests.db_template import ensure_template, session_token, template_db_name


def test_template_name_strips_the_worker_suffix():
    assert template_db_name("test_codemit_ab12_gw3", "gw3") == "test_codemit_ab12_tpl"
    assert template_db_name("test_codemit_ab12_gw12", "gw12") == "test_codemit_ab12_tpl"
    # 워커 없이(-n 0) 돌면 접미사가 없다 — 같은 템플릿 이름으로 간다.
    assert template_db_name("test_codemit_ab12", None) == "test_codemit_ab12_tpl"


@pytest.mark.django_db
def test_worker_db_is_a_clone_of_a_template_this_session_built(request):
    conn = connections["default"]
    worker_id = getattr(request.config, "workerinput", {}).get("workerid")
    template = template_db_name(conn.settings_dict["NAME"], worker_id)
    assert conn.settings_dict["NAME"] != template

    with conn.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        assert cursor.fetchone()[0] == conn.settings_dict["NAME"]
        # 복제본에 마이그레이션 기록이 그대로 있다 — 템플릿이 마이그레이션된 DB 였다.
        cursor.execute("SELECT count(*) FROM django_migrations")
        assert cursor.fetchone()[0] > 0
        # 템플릿에는 이 세션의 표가 붙어 있다(다른 세션이 남긴 것을 쓰지 않는다).
        cursor.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            [template],
        )
        assert cursor.fetchone()[0] == session_token(request.config)
        # 템플릿에 연결이 남아 있으면 다른 워커의 복제가 거절된다.
        cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = %s", [template])
        assert cursor.fetchone()[0] == 0


@pytest.mark.django_db
def test_ensure_template_builds_once_per_session_token():
    # 잠금·표의 계약만 본다 — DB 를 새로 만들지 않고, 이 워커의 시험 DB(세션 끝에 지워진다)
    # 의 COMMENT 를 표 자리로 빌린다. `build` 는 이미 있는 DB 에 아무것도 하지 않는다.
    conn = connections["default"]
    name = conn.settings_dict["NAME"]
    calls: list[str] = []

    assert ensure_template(conn, name, "token-a", lambda: calls.append("build")) is True
    assert ensure_template(conn, name, "token-a", lambda: calls.append("again")) is False
    # 표가 다르면(지난 실행이 남긴 템플릿) 다시 만든다.
    assert ensure_template(conn, name, "token-b", lambda: calls.append("rebuild")) is True
    assert calls == ["build", "rebuild"]
