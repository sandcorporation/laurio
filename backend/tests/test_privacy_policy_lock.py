"""개인정보처리방침 개정 시행일 전에는 Claude(Anthropic) 키 연결을 저장할 수 없다(#803).

방침 5·6항에 Anthropic, PBC(미국)를 더한 개정의 시행일(`settings.PRIVACY_POLICY_EFFECTIVE_DATE`,
한국 시간 0시)이 오기 전에 제출 소스가 그 회사로 나가면 고지 없는 국외 이전이다. 저장 API 가 거절하고,
화면은 응답의 `anthropic_key_selectable` 로 선택지를 숨긴다. 시계는 `ClockOverride`.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from django.conf import settings as django_settings

import config.settings as config_settings

from classroom.models import Class
from core.models import ClockOverride
from tests.classroom_scenarios import create_class, get_class, login, set_anthropic_key, set_key

EFFECTIVE = date(2026, 11, 6)


def _now(value: datetime) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": value})


@pytest.fixture(autouse=True)
def _effective_nov_6(settings):
    settings.PRIVACY_POLICY_EFFECTIVE_DATE = EFFECTIVE


def test_before_the_effective_date_the_claude_key_is_refused_and_the_old_connection_stays(client, db):
    # 2026-11-05 23:59 KST = 14:59 UTC
    _now(datetime(2026, 11, 5, 14, 59, tzinfo=timezone.utc))
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_key(client, owner["access"], class_id, "sk-test-aaaa1111")

    response = set_anthropic_key(client, owner["access"], class_id)

    assert response.status_code == 422
    assert "2026년 11월 6일" in response.json()["detail"]
    row = get_class(client, owner["access"], class_id)
    assert row["scoring_connection_kind"] == Class.ScoringConnectionKind.OPENAI_KEY
    assert row["openai_key_masked"].endswith("1111")
    assert row["anthropic_key_selectable"] is False


def test_from_midnight_kst_on_the_effective_date_it_opens_by_itself(client, db):
    # 2026-11-06 00:00 KST = 2026-11-05 15:00 UTC
    _now(datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc))
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)

    assert get_class(client, owner["access"], class_id)["anthropic_key_selectable"] is True
    assert set_anthropic_key(client, owner["access"], class_id).status_code == 200


def test_the_openai_key_is_never_locked(client, db):
    _now(datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc))
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)

    set_key(client, owner["access"], class_id, "sk-test-bbbb2222")


def test_the_policy_page_and_the_lock_read_the_same_date():
    """방침 화면의 시행일과 잠금이 보는 설정은 한 값이다 — 한쪽만 고치면 여기서 깨진다."""

    page = (Path(django_settings.BASE_DIR).parent / "frontend/app/privacy/page.tsx").read_text(encoding="utf-8")
    match = re.search(r'const EFFECTIVE_DATE = "(\d+)년 (\d+)월 (\d+)일";', page)
    assert match, "privacy/page.tsx 의 EFFECTIVE_DATE 를 찾지 못했다"
    on_page = date(*(int(g) for g in match.groups()))
    # settings.py 가 정한 값(이 파일의 fixture 가 덮어쓴 값이 아니다)
    assert on_page == config_settings.PRIVACY_POLICY_EFFECTIVE_DATE
