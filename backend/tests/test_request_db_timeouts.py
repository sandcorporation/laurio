"""요청 경로의 DB 한도(#745) — gthread 에서 걸린 요청을 거두는 장치.

gunicorn gthread 의 `timeout` 은 걸린 요청을 죽이지 않는다(#742). 그래서 요청 안의
SQL 문 하나하나에 `SET LOCAL statement_timeout`·`lock_timeout` 을 함께 실어 보낸다
(`core.db_timeouts`). 이 파일이 못 박는 것:

- 요청 안의 느린 문은 끊긴다(실제 PostgreSQL 의 `pg_sleep`).
- 요청 밖(celery 태스크 본체·관리 명령)의 같은 문은 끊기지 않는다.
- autocommit 요청에서도 `SET LOCAL` 이 그 문의 암묵 트랜잭션에 먹는다 — `transaction=True`
  시험이라 시험 바깥 트랜잭션 없이 실제 autocommit 으로 돈다.
- 접두 뒤 문의 오류는 `execute` 에서 바로 올라온다(psycopg 가 결과 전부를 본다).
- 한도는 문이 든 트랜잭션과 함께 끝난다 — 연결 풀러(트랜잭션 모드)가 그 서버 연결을
  다음 클라이언트에게 넘겨도 따라가지 않는다.

뷰는 운영 URL 에 없는 시험용이다 — 느린 문을 낼 실제 엔드포인트가 없어서다. 그래도
요청은 테스트 클라이언트로 미들웨어 체인 전체를 지난다.
"""

from __future__ import annotations

import psycopg
import pytest
from celery import shared_task
from django.db import DataError, OperationalError, connection, transaction
from django.http import JsonResponse
from django.test import Client
from django.urls import path


def _sleep_view(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_sleep(%s)", [float(request.GET["s"])])
    return JsonResponse({"ok": True})


def _settings_view(request):
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('statement_timeout'), current_setting('lock_timeout')"
            )
            in_atomic = cursor.fetchone()
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        autocommit = cursor.fetchone()[0]
    return JsonResponse(
        {
            "statement": in_atomic[0],
            "lock": in_atomic[1],
            "autocommit": autocommit,
            "is_autocommit": connection.get_autocommit(),
        }
    )


def _divide_by_zero_view(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1/0")
    return JsonResponse({"ok": True})


def _iterator_view(request):
    # QuerySet.iterator() 는 풀러가 없는 곳(dev·CI)에서 서버측 커서(DECLARE … CURSOR)를 연다.
    from django.contrib.contenttypes.models import ContentType

    count = sum(1 for _ in ContentType.objects.all().iterator(chunk_size=5))
    return JsonResponse({"count": count})


urlpatterns = [
    path("sleep/", _sleep_view),
    path("iterator/", _iterator_view),
    path("settings/", _settings_view),
    path("divide-by-zero/", _divide_by_zero_view),
]


@shared_task
def _sleep_then_show_statement_timeout():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_sleep(0.3)")
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


@pytest.fixture
def client_here(settings):
    settings.ROOT_URLCONF = __name__
    return Client(raise_request_exception=True)


@pytest.mark.django_db(transaction=True)
def test_requests_run_with_statement_and_lock_timeouts(client_here):
    body = client_here.get("/settings/").json()

    assert body == {
        "statement": "25s",
        "lock": "5s",
        "autocommit": "25s",
        "is_autocommit": True,
    }
    # 한도는 그 문의 트랜잭션과 함께 끝난다 — 같은 연결의 다음 문(요청 밖)에는 없다.
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        assert cursor.fetchone()[0] == "0"


@pytest.mark.django_db(transaction=True)
def test_slow_statement_in_a_request_is_cancelled(client_here, settings):
    settings.CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS = 100

    with pytest.raises(OperationalError, match="statement timeout"):
        client_here.get("/sleep/", {"s": 2})


@pytest.mark.django_db
def test_celery_task_bodies_are_not_limited(settings):
    # celery 태스크 본체는 요청 미들웨어를 지나지 않는다(내부 HTTP 스캔은 요청이라 걸린다).
    settings.CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS = 100

    assert _sleep_then_show_statement_timeout.apply().get() == "0"


@pytest.mark.django_db
def test_error_of_the_prefixed_statement_rises_from_execute(client_here, monkeypatch):
    # psycopg 는 한 메시지의 결과를 execute 안에서 전부 보고 오류를 던진다 — 결과를 넘기는
    # nextset 까지 가지 않는다. Django 의 오류 변환(DataError)도 execute 에서 이미 돈다.
    called = []
    original = psycopg.Cursor.nextset

    def recording_nextset(self):
        called.append(True)
        return original(self)

    monkeypatch.setattr(psycopg.Cursor, "nextset", recording_nextset)

    with pytest.raises(DataError, match="division by zero"):
        client_here.get("/divide-by-zero/")
    assert called == []


@pytest.mark.django_db
def test_zero_turns_the_limit_off(client_here, settings):
    settings.CODEMIT_REQUEST_STATEMENT_TIMEOUT_MS = 0
    settings.CODEMIT_REQUEST_LOCK_TIMEOUT_MS = 0

    body = client_here.get("/settings/").json()

    assert body == {"statement": "0", "lock": "0", "autocommit": "0", "is_autocommit": False}


@pytest.mark.django_db
def test_server_side_cursors_still_work_in_a_request(client_here):
    assert client_here.get("/iterator/").json()["count"] > 5


@pytest.mark.django_db
def test_recorded_sql_is_the_original_statement(client_here):
    # 질의 모양·횟수를 재는 시험과 느린 질의 로그가 보는 SQL 에는 접두가 없어야 한다.
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as captured:
        client_here.get("/settings/")

    assert captured.captured_queries
    assert not any("SET LOCAL" in q["sql"] for q in captured.captured_queries)
