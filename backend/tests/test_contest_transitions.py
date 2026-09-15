"""Contest 전이 그래프가 한 곳에 선언되어 있고, 하중을 받는지 (#255, ADR-0003).

**직접 호출로 테스트한다 — HTTP를 거치지 않는다.** 이 저장소의 원칙(CLAUDE.md「HTTP가
유일한 시임이다」)은 "HTTP 로 볼 수 있는 동작을 위해 더 낮은 시임을 새로 만들지 않는다"는
것이지 "함수를 직접 부르면 안 된다"가 아니다 — 이미 이 저장소가 그 경계로 direct 테스트를
둔 전례가 둘이다: `tests/test_status_classification.py`(질문마다 전체 사상 + 키 집합)와
운영자 큐 SQL 술어(312개 조합)가 그렇다. ADR-0026 이 프론트에 같은 시임을 들이면서 바로 이
둘을 근거로 들었다. 여기서 확인하는 것도 같은 층 — **순수 선언**(간선 집합·타입 모양·
`contest_transition_spec` 이 선언에서 파생되는지·호출부가 쓰는 이름이 선언과 같은 집합인지)
과 **표가 실행기가 되지 않았다는 사실**(조건부 UPDATE 쿼리 수 — HTTP 요청은 쿼리를 여럿
내므로 이건 HTTP 로는 볼 수 없다) 뿐이다.

**도메인 동작(전이가 실제로 일어나는가, 잘못된 상태에서는 거부되는가, 동시 요청이 한 번만
이기는가)은 여기서 다시 단언하지 않는다** — 다섯 전이 각각의 HTTP 시임 테스트
(test_contest_deadline_transition.py·test_judging_period_and_award.py·test_payments.py·
test_charges.py·test_assignments.py)가 이미 고정하고 있다. 여기서 같은 것을 다시 단언하면
그 시임 테스트가 깨져도 이 파일은 초록으로 남는 사본이 생긴다 — 그것이 이 원칙이 막으려는
바로 그 중복이다.
"""

from __future__ import annotations

import ast

import pytest

from contests.models import Contest
from contests.transitions import (
    CONTEST_IN_PLACE_UPDATES,
    CONTEST_TRANSITIONS,
    ActionContestTransition,
    ScanContestTransition,
    claim_contest_in_place_update,
    claim_contest_transition,
    contest_transition_spec,
)
from core.clock import Clock
from tests.ast_scan_support import BACKEND_ROOT, python_sources

# contests.transitions 가 이름으로 받는 세 함수 — 각자 어느 표에서 이름을 찾는지.
_NAME_LOOKUP_FUNCTIONS = {
    "claim_contest_transition": CONTEST_TRANSITIONS,
    "contest_transition_spec": CONTEST_TRANSITIONS,
    "claim_contest_in_place_update": CONTEST_IN_PLACE_UPDATES,
}


def test_the_five_scattered_spots_are_declared_as_exactly_these_six_edges():
    """다섯 자리(스캔 셋·선정·결제확정·과제열기)가 여기 여섯 간선으로 다 있다 —
    apps.py 가 스캔 셋을 등록하므로 한 자리가 셋을 낳는다. (일곱 번째 **호출부**
    `seed_e2e_operator_queues.py` 도 있었지만 새 간선이 아니라 이미 있는
    「contest-close」를 손으로 다시 부르던 것이었다 — #255 코드리뷰가 잡아 지금은
    그 자리도 이 표를 그대로 쓴다.)

    무료 공모전의 공개 전이 「publish-free」(#415, ADR-0048)가 일곱 번째로 더해졌다
    — 결제 대신 개최 권한이 여는, `draft -> published`로 가는 두 번째 간선이다."""

    assert set(CONTEST_TRANSITIONS) == {
        "contest-close",
        "contest-judging-end",
        "publish-on-payment",
        "publish-free",
        "award",
    }


def test_every_declared_transition_is_a_real_state_change():
    """전이는 from_state != to_state 다 — 제자리 갱신은 이 표에 없다."""

    for name, edge in CONTEST_TRANSITIONS.items():
        assert edge.from_state != edge.to_state, f"{name} 은 제자리 갱신처럼 보인다"


def test_judging_extension_is_declared_as_an_in_place_update_not_an_edge():
    """심사 연장(CLOSED -> CLOSED)은 전이 표에 없고, 제자리 갱신 표에만 있다 — #257의
    다이어그램이 자기 자신으로 가는 화살표를 그리지 않으려면 이 구별이 여기서부터 서야 한다."""

    assert "judging-extension" not in CONTEST_TRANSITIONS
    assert "judging-extension" in CONTEST_IN_PLACE_UPDATES
    update = CONTEST_IN_PLACE_UPDATES["judging-extension"]
    assert update.state == Contest.Status.CLOSED


def test_scan_edges_and_action_edges_are_distinguished_by_type_not_a_flag():
    """스캔/행위 구분이 문자열 플래그가 아니라 타입이다 — 「스캔이면 due_field 가
    있다」가 조건문이 아니라 타입 자체로 성립하는지 확인한다."""

    scan_names = {"contest-close", "contest-judging-end"}
    action_names = {"publish-on-payment", "award"}

    for name in scan_names:
        assert isinstance(CONTEST_TRANSITIONS[name], ScanContestTransition)
        assert CONTEST_TRANSITIONS[name].due_field  # 필수 필드 — 빈 문자열이면 안 된다.
    for name in action_names:
        assert isinstance(CONTEST_TRANSITIONS[name], ActionContestTransition)
        assert not hasattr(CONTEST_TRANSITIONS[name], "due_field")




def test_an_undeclared_transition_name_is_loud_not_silently_false():
    """선언에 없는 이름으로는 애초에 시도조차 할 수 없다 — 조용히 통과하지 않는다."""

    with pytest.raises(KeyError):
        claim_contest_transition("no-such-edge", 1)


def test_an_undeclared_in_place_update_name_is_loud_not_silently_false():
    with pytest.raises(KeyError):
        claim_contest_in_place_update("no-such-update", 1)


def test_deriving_a_scan_spec_for_an_action_edge_is_rejected():
    """「award」·「publish-on-payment」는 스캔이 아니라 명시적
    행위다 — apps.py 가 실수로 이들을 스캔으로 등록하려 들면 여기서 막힌다."""

    with pytest.raises(ValueError):
        contest_transition_spec("award")


@pytest.mark.django_db
def test_scan_spec_is_derived_from_the_declaration_not_retyped():
    spec = contest_transition_spec("contest-judging-end")
    edge = CONTEST_TRANSITIONS["contest-judging-end"]
    assert spec.model is Contest
    assert spec.from_state == edge.from_state
    assert spec.to_state == edge.to_state
    assert spec.due_field == edge.due_field
    assert spec.state_field == "status"


@pytest.mark.django_db
def test_claiming_a_declared_edge_is_a_single_conditional_update(django_assert_num_queries):
    """표는 실행기가 아니다 — 실제 전이는 여전히 조건부 UPDATE 한 번이다(ADR-0003).
    쿼리 수 1개로 그것을 고정한다. HTTP 요청은 인증·직렬화 등으로 쿼리를 여럿 내므로
    이 사실은 HTTP 시임으로는 볼 수 없다 — 여기서만 볼 수 있는 유일한 사실이라 직접
    확인한다. 실제로 전이가 CLOSED->AWARDED 로 일어나는지 같은 도메인 동작은
    test_judging_period_and_award.py 가 이미 HTTP 로 고정하고 있으므로 여기서
    다시 단언하지 않는다 — `won` 하나만 그 조건부 UPDATE 의 rowcount 신호로 본다."""

    contest = _bare_contest(Contest.Status.CLOSED)
    now = Clock.now()  # 카운트 밖에서 미리 구한다 — Clock.now() 자체가 SELECT 한 번이다.

    with django_assert_num_queries(1):
        won = claim_contest_transition("award", contest.pk, now=now)

    assert won is True


@pytest.mark.django_db
def test_in_place_update_is_also_a_single_conditional_update(django_assert_num_queries):
    """제자리 갱신도 같은 계약이다 — 상태는 안 바뀌지만 조건부 UPDATE 는 여전히 한 번."""

    contest = _bare_contest(Contest.Status.CLOSED, judging_ends_at=None)
    now = Clock.now()

    with django_assert_num_queries(1):
        won = claim_contest_in_place_update(
            "judging-extension", contest.pk, now=now, extra_fields={"judging_extension_count": 1}
        )

    assert won is True


def _declared_name_calls(tree: ast.AST) -> list[tuple[str, str]]:
    """`(함수 이름, 첫 인자 문자열)` 쌍 — `claim_contest_transition("award", ...)` 같은
    호출에서 이름 리터럴을 뽑는다. 변수로 넘긴 이름은(지금 호출부 어디에도 없다) 잡지
    못한다 — 정적 분석의 한계이고, 지금 관용구(문자열 리터럴 하나)가 유지되는 한 충분하다."""

    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        func_name = node.func.id
        if func_name not in _NAME_LOOKUP_FUNCTIONS:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            found.append((func_name, node.args[0].value))
    return found


def test_every_call_site_uses_a_name_the_declaration_actually_has():
    """문자열 이름이 옛 안전성(오타 나면 import 시점에 죽는 enum 속성 접근)을 잃는
    대가로 얻는 것 — 오타가 나면 그 자리를 실행할 때까지 몰랐다. 코드베이스 전체를
    정적으로 훑어 그 대가를 좁힌다: 선언에 없는 이름을 쓰는 자리가 있으면 지금
    당장(그 코드가 실행되기 한참 전에) 여기서 잡는다."""

    # `python_sources()` 는 tests/ 전체를 건너뛴다 — 이 파일 자신이 일부러 잘못된
    # 이름("no-such-edge" 등)으로 KeyError 를 확인하므로, 이 검사에 끼면 안 된다.
    offenders = []
    for path in python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func_name, name in _declared_name_calls(tree):
            table = _NAME_LOOKUP_FUNCTIONS[func_name]
            if name not in table:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {func_name}({name!r})")

    assert not offenders, (
        "선언에 없는 이름으로 contests.transitions 함수를 부르는 자리가 있다(런타임에 "
        f"KeyError 로 죽는다): {offenders}"
    )


def _bare_contest(status: str, **extra) -> Contest:
    """조건부 UPDATE 를 걸 대상 행 하나 — 이 테스트가 보는 것은 **행 자체가 아니라
    UPDATE 문의 모양**이므로 스폰서·카테고리는 최소한만 채운다."""

    from datetime import timedelta

    from django.contrib.auth import get_user_model

    from accounts.models import SponsorProfile
    from contests.models import Category

    tag = f"{status}-{Contest.objects.count()}"
    user = get_user_model().objects.create_user(
        username=f"contest-transitions-{tag}", email=f"contest-transitions-{tag}@example.invalid"
    )
    sponsor = SponsorProfile.objects.create(user=user, display_name=f"스폰서-{tag}")
    category = Category.objects.create(name=f"카테고리-{tag}")
    now = Clock.now()
    defaults = dict(
        sponsor=sponsor,
        title="테스트 공모전",
        category=category,
        prize=100_000,
        deadline_at=now + timedelta(days=1),
        status=status,
    )
    defaults.update(extra)
    return Contest.objects.create(**defaults)
