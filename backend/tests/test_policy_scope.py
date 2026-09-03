"""PlatformPolicy 스코프 (#145, #123, ADR-0023) — 요청 하나·스캔 실행 하나에 SELECT 한 번.

`policies.scope.current_policy()` 는 열린 스코프 안에서는 첫 호출에만 읽고, 스코프 밖에서는 매번 새로
읽는다. 요청 스코프는 미들웨어가, 스캔 스코프는 core.scans 가 연다.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from policies.models import PlatformPolicy
from policies.scope import current_policy, policy_scope
from tests.test_handover import (  # noqa: F401 - 픽스처
    CONTESTS_URL,
    _auth_header,
    _publish_close_award,
    category,
    landing_type,
)


def _policy_selects(queries) -> int:
    return sum(1 for q in queries if "policies_platformpolicy" in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT"))


@pytest.mark.django_db
def test_a_request_selects_the_policy_exactly_once(client, category, landing_type):
    """지급 요청은 금액 계산·수취인 등록 힌트 등 여러 자리에서 정책을 읽는다 — 요청 하나에 SELECT 는 한 번."""

    sponsor, dev, contest, _submission = _publish_close_award(client, category, landing_type)
    accepted = client.post(f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"]))
    assert accepted.status_code == 200
    current_policy()  # 행이 없으면 만드는 get_or_create 의 INSERT 가 아래 계수에 섞이지 않게 미리 만든다.

    with CaptureQueriesContext(connection) as ctx:
        response = client.post(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert response.status_code == 201, response.content
    assert _policy_selects(ctx.captured_queries) == 1, [q["sql"] for q in ctx.captured_queries if "platformpolicy" in q["sql"]]


@pytest.mark.django_db
def test_inside_a_scope_the_policy_is_read_once_and_outside_it_is_read_fresh_each_time():
    current_policy()
    with CaptureQueriesContext(connection) as inside:
        with policy_scope():
            first = current_policy()
            second = current_policy()
    assert first is second
    assert _policy_selects(inside.captured_queries) == 1

    with CaptureQueriesContext(connection) as outside:
        current_policy()
        current_policy()
    assert _policy_selects(outside.captured_queries) == 2


@pytest.mark.django_db
def test_a_policy_change_inside_a_scope_is_visible_to_the_rest_of_that_scope():
    """write-through — 같은 요청 안에서 바꾼 정책을 그 요청의 나머지가 즉시 본다."""

    from django.contrib.auth import get_user_model

    from accounts.operators import create_operator
    from policies.services import update_policy

    create_operator("policy-op", "Correct-Horse-Battery-7!")
    operator = get_user_model().objects.get(username="policy-op")
    with policy_scope():
        before = current_policy()
        update_policy(
            operator=operator,
            reason="테스트",
            expected_version=before.version,
            changes={"platform_fee_bps": before.platform_fee_bps + 1},
        )
        after = current_policy()
    assert after.platform_fee_bps == before.platform_fee_bps + 1
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == after.platform_fee_bps
