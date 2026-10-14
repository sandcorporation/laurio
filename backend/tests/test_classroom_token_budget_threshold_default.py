"""경고 임계 칸은 DB 기본값 80 을 가진다(#665) — 칸을 모르는 새 코드의 INSERT 가 NULL 을
남기면 겹치는 동안 옛 코드의 `ClassOut`(int)이 500 을 낸다."""

import pytest
from django.db import connection


@pytest.mark.django_db
def test_threshold_column_has_db_default_80():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_default FROM information_schema.columns"
            " WHERE table_name = 'classroom_class'"
            " AND column_name = 'token_budget_warning_threshold_percent'"
        )
        (default,) = cursor.fetchone()
    assert default == "80"
