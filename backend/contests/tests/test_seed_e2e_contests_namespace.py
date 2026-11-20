"""`seed_e2e_contests` 의 워커 네임스페이스 (#104).

e2e 스위트를 워커 여럿으로 돌리려면 이 명령이 **다른 워커의 데이터를 지우지
않아야** 한다. 지금은 `[E2E] ` 접두어가 붙은 것을 전부 지우고 다시 만들기
때문에, 두 워커가 동시에 부르면 서로의 픽스처를 파괴한다.

이 파일은 HTTP 를 거치지 않는다 — 검증 대상이 관리 명령 자신의 행동이고,
`tests/test_home_curation.py` 의 시드 테스트가 같은 이유로 `call_command` 를
직접 부른다.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from contests.models import Contest


def _seed(namespace: str = "") -> dict:
    """명령을 돌리고 그 JSON 출력을 돌려준다."""

    from io import StringIO

    out = StringIO()
    args = ["seed_e2e_contests"]
    if namespace:
        args += ["--namespace", namespace]
    call_command(*args, stdout=out)
    return json.loads(out.getvalue().strip().splitlines()[-1])


def test_namespaces_do_not_delete_each_other(db):
    """**다른 네임스페이스의 데이터는 살아남는다** (#104).

    이게 성립하지 않으면 워커를 늘리는 순간 두 워커가 서로의 픽스처를 지우고,
    실패는 코드 회귀와 구분되지 않는다 — 예전 병렬화 시도가 16건 실패로 끝난
    이유가 이것이다.
    """

    first = _seed("w0")
    second = _seed("w1")

    # 두 번째 시드가 첫 번째를 지웠다면 이 조회가 비어 있다.
    assert Contest.objects.filter(id=first["judging"]["id"]).exists(), (
        "w1 의 시드가 w0 의 Contest 를 지웠다 — 네임스페이스가 격리되지 않았다"
    )
    assert Contest.objects.filter(id=second["judging"]["id"]).exists()
    assert first["judging"]["id"] != second["judging"]["id"]


def test_namespaces_get_distinct_accounts(db):
    """계정도 갈린다 — username 이 unique 라 같은 이름을 쓰면 두 번째가 터진다."""

    first = _seed("w0")
    second = _seed("w1")

    assert first["judging"]["developer_login_seed"] != second["judging"]["developer_login_seed"]
    assert first["judging"]["sponsor_login_seed"] != second["judging"]["sponsor_login_seed"]


def test_reseeding_the_same_namespace_replaces_only_its_own(db):
    """같은 네임스페이스를 다시 심으면 자기 것만 갈아엎는다 — 워커 안에서는
    파일마다 다시 심어 격리를 얻는 지금 동작이 그대로 유지돼야 한다."""

    other = _seed("w1")
    first = _seed("w0")
    again = _seed("w0")

    assert not Contest.objects.filter(id=first["judging"]["id"]).exists(), (
        "같은 네임스페이스를 다시 심었는데 옛 Contest 가 남았다 — 테스트 간 격리가 깨진다"
    )
    assert Contest.objects.filter(id=again["judging"]["id"]).exists()
    assert Contest.objects.filter(id=other["judging"]["id"]).exists(), (
        "w0 를 다시 심었는데 w1 이 사라졌다"
    )


def test_default_namespace_keeps_the_existing_prefix(db):
    """네임스페이스를 안 주면 예전과 똑같이 `[E2E] ` 로 심는다.

    런타임에 Contest 를 만드는 스펙들(submit·upload·grill·payment)이 그 접두어를
    직접 쓰고, `global-setup` 의 일괄 정리도 그 접두어를 훑는다.
    """

    seeded = _seed()

    contest = Contest.objects.get(id=seeded["judging"]["id"])
    assert contest.title.startswith("[E2E] ")
    assert get_user_model().objects.filter(username="e2e-seed-sponsor").exists()


@pytest.mark.parametrize("bad", ["with space", "대문자아님", "w/0", "a" * 33])
def test_namespace_is_rejected_when_it_could_collide_or_overflow(db, bad):
    """네임스페이스는 짧은 영숫자여야 한다.

    username 과 title 에 그대로 들어가므로, 공백이나 구분자가 섞이면 접두어
    비교(`startswith`)가 다른 네임스페이스를 잡아먹을 수 있고, 길면 username
    길이 제한을 넘겨 시드가 런타임에 터진다.
    """

    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        _seed(bad)
