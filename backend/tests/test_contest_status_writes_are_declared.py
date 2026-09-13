"""선언된 경로 밖에서 `Contest.status` 를 바꾸는 코드가 태어나지 못하게 막는다 (#256).

#255 가 Contest 전이 그래프를 `contests.transitions` 한 곳에 모았다. 그런데 그것만으로는
**여섯 번째 지점**을 막지 못한다 — 누군가 `Contest.objects.filter(...).update(status=...)`
를 새로 쓰거나 `core.transitions.claim_transition` 을 Contest 에 대해 직접 다시 부르면
그 선언은 그것을 모른다. 실제로 #255 작업 중에 정확히 그런 코드가 하나 발견됐다 —
`accounts/management/commands/seed_e2e_operator_queues.py` 가 `core.transitions.
claim_transition(Contest, ..., state_field="status", ...)` 를 손으로 직접 불러
`contest-close` 간선(PUBLISHED→CLOSED)을 `judging_ends_at` 계산까지 포함해 재구현하고
있었다. 다섯 자리를 세려고 작정하고 훑은 사람도 이미 하나(#255 본문의
전이 하나)를 놓쳤었다 — 같은 실수가 코드 리뷰 없이 반복되지 않으려면
독스트링 규율이 아니라 **테스트**가 막아야 한다(ADR-0033 의 종류 게이트가 같은 이유로
독스트링 규율이 세 번 실패한 뒤 `tests/test_contest_kind_gates.py` 로 옮겨간 것과 같다 —
이 파일도 그 파일과 같은 AST 정적 스캔 방식을 그대로 따르고, 스캔 대상 파일 목록도
`tests/ast_scan_support.py` 로 공유한다).

**금지되는 것 둘, 정확히 그 두 사고가 실제로 났던 모양이다.**

1. `<Contest 참조>.objects....update(status=...)` / `.bulk_update(objs, ["status"])` —
   Contest 를 향한 QuerySet 호출에서 `status` 를 직접 쓰는 것(payments/models.py 의 예전
   코드가 이랬다). `Contest` 참조는 `Contest.objects...` 든 `contests.models.Contest.
   objects...` 든, 아니면 `qs = Contest.objects.filter(...)` 로 한 단계 별칭을 거친
   `qs.update(...)` 든 잡는다.
2. `claim_transition(Contest, ...)` / `claim_transition(model=Contest, ...)` —
   `core.transitions` 의 원시 primitive 를 Contest 에 대해 **직접** 부르는 것
   (seed_e2e_operator_queues.py 가 이랬다, 위치 인자든 키워드 인자든). 이름 표
   (`contests.transitions.CONTEST_TRANSITIONS`)를 거치지 않고 `from_state`/`to_state` 를
   호출부가 다시 타이핑하면, #255 가 없애려던 바로 그 흩어짐이 되살아난다.

**생성은 막지 않는다.** `Contest.objects.create(status=...)` 와 `Contest.objects.
bulk_create([Contest(status=...), ...])` 는 둘 다 이 스캔을 그대로 통과한다 — 위 금지
목록이 `create`/`bulk_create`/생성자 호출이 아니라 `update`/`bulk_update`/`claim_transition`
호출만 본다. 「생성은 이 통제 밖이다」(`contests/transitions.py` 의 판단)를 정적 스캔 자체가
같은 경계로 지킨다 — 초안 개최·`seed_e2e_contests`·`seed_demo_contests` 는 전부 `.create()`
관용구만 쓰므로 그대로 통과한다.

**정당한 예외가 통과하는 길은 `ALLOWED` 하나다.** 지금은 `contests/transitions.py` 뿐이다
— 선언과 `claim_contest_transition`/`claim_contest_in_place_update`/`contest_transition_spec`
이 사는 바로 그 파일. 새 정당한 예외(다른 시드가 정말 이 표를 거치지 않고 상태를 직접
써야 하는 사정이 생기면)가 필요해지면 이 집합에 이유와 함께 더한다 — 예외가 어디 있는지
찾으려고 저장소를 훑을 필요가 없게 하나로 모아 둔다.

**정밀도.** `Contest` 라는 이름이 호출 사슬 어디에든 있으면 잡는 것이 아니라, `.update()`/
`.bulk_update()` 호출의 **수신자 사슬**(`<모델>.objects.filter(...)....update(...)`)을
따라 내려가 `.objects` 바로 앞의 모델 참조만 본다 — 그래서
`Payout.objects.filter(contest=Contest.objects.get(pk=x), status=...).update(status=...)`
처럼 필터 **인자** 안에 `Contest` 가 등장하는, Contest 와 무관한 Payout 갱신은 잡지 않는다.

**이 테스트를 우회하는 가장 쉬운 방법 — 정적 매칭의 한계.** 위 정밀도 개선 뒤에도 다음은
피해 간다:

- `Contest.objects.filter(**{"status": x}).update(**{"status": y})` — 키워드를 `**` 딕셔너리
  언패킹 뒤에 숨기면 `ast.keyword(arg="status", ...)` 로도, `bulk_update` 의 필드 리스트로도
  안 잡힌다.
- `from contests.models import Contest as C` — **클래스 자체**를 다른 이름으로 다시 import 한
  뒤 `C.objects...update(status=...)` 를 쓰면, "마지막 속성 이름이 Contest" 라는 매칭도
  "지역 변수 별칭" 추적도 비켜 간다(별칭 추적은 `X = Contest.objects...` 형태의 **queryset**
  재대입만 본다 — import 시점의 클래스 재바인딩은 다른 문제다).
- `get_contest_queryset().update(status=...)` — 헬퍼 함수 뒤에 숨긴 조회는 그 함수 안을
  들여다보지 않는 한(이 스캔은 파일 하나 안의 호출 하나만 본다) 추적할 수 없다.
- `contest.status = X; contest.save()` — 어떤 변수가 실제로 Contest 인스턴스인지는 타입
  추론 없이 정적으로 알 수 없다. 이 저장소는 지금까지 Contest 에 이 패턴을 쓴 적이
  잡지 않는다.
- `cursor.execute("UPDATE contests_contest SET status = ...")` — raw SQL 은 애초에 이
  스캔의 대상이 아니다.

완전한 방어가 아니라 **실제로 두 번 일어난 사고와 같은 모양(+ 그 모양의 가장 자연스러운
변형인 별칭 재대입·키워드 인자)을 재현 불가능하게 만드는** 좁은 방어다 — ADR-0033 의
종류 게이트 테스트가 `PAYABLE` 속성 접근 하나만 잡듯, 이 테스트도 딱 그 모양만 잡는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.ast_scan_support import BACKEND_ROOT, python_sources

#: Contest.status 를 직접 다뤄도 되는 유일한 자리 — 선언과 claim 함수가 사는 곳.
#: 새 예외가 필요해지면 여기 더한다(그 판단의 이유도 함께 적는다).
ALLOWED = {
    Path("contests/transitions.py"),
}


def _model_of_queryset_chain(node: ast.AST) -> ast.AST | None:
    """`<모델>.objects.filter(...)....update(...)` 사슬에서 `<모델>` 노드를 찾는다.

    `.func`/`.value` 만 따라 내려가며 `.objects` 속성 접근을 만나면 그 바로 앞(왼쪽)을
    돌려준다 — 그래서 `.filter(contest=Contest.objects.get(...))` 처럼 **인자** 안에
    낀 참조는 이 사슬을 타지 않는다(인자는 따라 내려가지 않기 때문이다). `.objects` 가
    없는 사슬(변수 하나로 받은 QuerySet 등)은 `None` — 그 경우는 별칭 추적이 대신 본다.
    """

    current = node
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            if current.attr == "objects":
                return current.value
            current = current.value
        else:
            return None


def _is_contest_ref(node: ast.AST | None, aliases: set[str]) -> bool:
    """`Contest`(이름) · `<무엇>.Contest`(속성 접근, 예: `contests.models.Contest`) ·
    이미 추적한 별칭(변수) 중 하나인가."""

    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id == "Contest" or node.id in aliases
    if isinstance(node, ast.Attribute):
        return node.attr == "Contest"
    return False


def _build_contest_queryset_aliases(tree: ast.AST) -> set[str]:
    """`qs = Contest.objects.filter(...)` 처럼 Contest QuerySet 을 변수에 한 번 담아 두고
    그 변수에 `.update(...)` 를 부르는 자연스러운 리팩터를 별칭으로 추적한다.

    `X = Y`(Y 가 이미 추적된 별칭)로 한 단계 더 이어지는 것까지만 본다 — 고정점까지
    반복하되, 조건부 재대입·복잡한 표현식은 놓칠 수 있다(모듈 독스트링의 「우회」 목록).
    """

    simple_assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]

    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in simple_assigns:
            name = node.targets[0].id
            if name in aliases:
                continue
            value = node.value
            model_node = _model_of_queryset_chain(value)
            is_contest_qs = (isinstance(value, ast.Name) and value.id in aliases) or _is_contest_ref(
                model_node, aliases
            )
            if is_contest_qs:
                aliases.add(name)
                changed = True
    return aliases


def _mentions_status(node: ast.Call) -> bool:
    """`.update(status=...)`(키워드 이름)과 `.bulk_update(objs, ["status"])`(필드 목록의
    문자열 리터럴) 둘 다를 잡는다 — Django 두 API 가 "status" 를 싣는 자리가 다르다."""

    if any(kw.arg == "status" for kw in node.keywords):
        return True
    for arg in node.args:
        for n in ast.walk(arg):
            if isinstance(n, ast.Constant) and n.value == "status":
                return True
    return False


def _offenses_in(tree: ast.AST) -> list[str]:
    """이 파일(tree) 안에서 Contest.status 를 선언 밖에서 바꾸는 것으로 보이는 호출을 찾는다.

    모듈 docstring의 「금지되는 것 둘」을 그대로 코드로 옮긴다.
    """

    aliases = _build_contest_queryset_aliases(tree)
    offenses = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # ① <Contest 참조>.objects....update(status=...) / .bulk_update(objs, ["status"]).
        if isinstance(func, ast.Attribute) and func.attr in ("update", "bulk_update"):
            receiver = func.value
            targets_contest = _is_contest_ref(receiver, aliases) or _is_contest_ref(
                _model_of_queryset_chain(receiver), aliases
            )
            if _mentions_status(node) and targets_contest:
                offenses.append(
                    f"line {node.lineno}: .{func.attr}(...) 로 status 를 Contest 에 직접 씀"
                )

        # ② claim_transition(Contest, ...) / claim_transition(model=Contest, ...) — 원시
        #    primitive 를 Contest 에 대해 직접 호출(위치 인자든 키워드 인자든).
        callee_name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if callee_name == "claim_transition":
            target = node.args[0] if node.args else next(
                (kw.value for kw in node.keywords if kw.arg == "model"), None
            )
            if _is_contest_ref(target, aliases):
                offenses.append(
                    f"line {node.lineno}: core.transitions.claim_transition 을 Contest 에 "
                    "대해 직접 호출"
                )

    return offenses


def test_contest_status_is_never_written_outside_contests_transitions():
    offenders = []
    for path in python_sources():
        relative = path.relative_to(BACKEND_ROOT)
        if relative in ALLOWED:
            continue
        for offense in _offenses_in(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{relative} — {offense}")

    assert not offenders, (
        "Contest.status 를 선언된 경로(contests.transitions) 밖에서 바꾸는 자리가 있다: "
        f"{offenders}. `contests.transitions.claim_contest_transition`(전이) 또는 "
        "`claim_contest_in_place_update`(제자리 갱신)를 쓰거나, 필요한 간선이 아직 "
        "없다면 `contests/transitions.py` 에 새 간선으로 먼저 선언한다(#255/#256)."
    )


# ---------------------------------------------------------------------------
# CREATION_STATES(contests.transitions) 가 실제 생성 호출부와 갈리지 않았는지 —
# 손으로 든 값(그 상수의 독스트링)이 손으로 든 값답게 실제로 흔들리지 않는지를
# 정적으로 확인한다(#257 코드리뷰). 「생성은 이 그래프 밖」 이라는 경계 자체는
# 여전히 사람이 판단하지만, 그 판단을 적은 상수가 코드와 갈리는 것은 기계가 잡는다.
# ---------------------------------------------------------------------------


def _status_literal_name(node: ast.AST) -> str | None:
    """`<Contest 참조>.Status.<NAME>` 모양이면 `<NAME>`(예: "DRAFT")을 돌려준다.

    변수·함수 호출 등 리터럴이 아닌 값은 `None` — 정적으로 확인할 수 없다는 뜻이고,
    호출부가 이 함수의 결과를 `None` 이면 건너뛴다(시드가 `status=status` 처럼 변수를
    넘기는 자리가 여기 해당한다 — 생성의 정의가 아니라 테스트 픽스처의 특권이라
    `CREATION_STATES` 도 원래 이 자리를 보지 않는다, `contests/transitions.py` 의
    `CREATION_STATES` 독스트링 참고).
    """

    if not (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)):
        return None
    if node.value.attr != "Status":
        return None
    if not _is_contest_ref(node.value.value, set()):
        return None
    return node.attr


def _creation_status_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """`<Contest 참조>.objects.create(status=<리터럴>, ...)` 호출에서 `(줄 번호, 이름)`
    쌍을 뽑는다. `.create()` 만 본다 — `.update()`/`.bulk_update()` 는 위 `_offenses_in`
    이 이미 전이 경로 밖에서는 아예 못 쓰게 막는다."""

    aliases = _build_contest_queryset_aliases(tree)
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "create":
            continue
        receiver = node.func.value
        targets_contest = _is_contest_ref(receiver, aliases) or _is_contest_ref(
            _model_of_queryset_chain(receiver), aliases
        )
        if not targets_contest:
            continue
        for kw in node.keywords:
            if kw.arg != "status":
                continue
            name = _status_literal_name(kw.value)
            if name is not None:
                found.append((node.lineno, name))
    return found


def test_every_literal_creation_status_is_declared_in_creation_states():
    """`contests/transitions.py` 의 `CREATION_STATES` 는 손으로 든 값이다 — 실제
    `Contest.objects.create(status=Contest.Status.<이름>, ...)` 호출부와 정적으로
    갈리지 않는지 여기서 확인한다. 리터럴로 안 쓰고 변수를 넘기는 자리(시드)는
    `_status_literal_name` 이 `None` 을 돌려주므로 애초에 이 검사에 안 걸린다 —
    그 경계가 의도적이라는 것은 위 두 헬퍼 함수의 독스트링에 적혀 있다."""

    from contests.transitions import CREATION_STATES

    declared_names = {status.name for status in CREATION_STATES}

    offenders = []
    for path in python_sources():
        relative = path.relative_to(BACKEND_ROOT)
        if relative in ALLOWED:
            continue
        for lineno, name in _creation_status_literals(ast.parse(path.read_text(encoding="utf-8"))):
            if name not in declared_names:
                offenders.append(f"{relative}:{lineno} — status=Contest.Status.{name}")

    assert not offenders, (
        "Contest.objects.create(status=Contest.Status.<이름>) 이 CREATION_STATES 에 없는 "
        f"값을 리터럴로 찍는 자리가 있다: {offenders}. contests/transitions.py 의 "
        "CREATION_STATES 에 그 값을 더하거나(정말 새 생성 경로라면), 이 생성이 정말 "
        "맞는지(전이여야 하는 건 아닌지) 다시 확인한다."
    )


# ---------------------------------------------------------------------------
# `_offenses_in` 자체의 경계를 직접 확인한다 — 스캔 로직이 옳은지는 실제 저장소가
# 우연히 깨끗해서가 아니라 이 표(무엇을 잡고 무엇을 통과시키는가)로 보장돼야 한다.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        'Contest.objects.filter(pk=1, status="published").update(status="closed")',
        'Contest.objects.bulk_update([Contest(status="closed")], ["status"])',
        'core.transitions.claim_transition(Contest, pk, from_state="a", to_state="b", state_field="status")',
        'claim_transition(Contest, pk, from_state="a", to_state="b")',
        # #256 코드리뷰가 짚은 두 변형 — 키워드 인자, 그리고 한 단계 변수 별칭.
        'claim_transition(model=Contest, pk=pk, from_state="a", to_state="b")',
        'qs = Contest.objects.filter(pk=1, status="published")\nqs.update(status="closed")',
        # 모듈 경로로 참조해도(마지막 속성 이름이 Contest) 잡는다.
        'contests.models.Contest.objects.filter(pk=1).update(status="closed")',
    ],
)
def test_the_known_bypass_shapes_are_caught(source: str):
    assert _offenses_in(ast.parse(source)), f"이 코드가 잡혔어야 한다: {source}"


@pytest.mark.parametrize(
    "source",
    [
        # 생성은 통과한다 — .create()/.bulk_create() 는 update/bulk_update/claim_transition
        # 어느 쪽도 아니다.
        'Contest.objects.create(sponsor=s, status="draft")',
        'Contest.objects.bulk_create([Contest(status="published") for _ in range(3)])',
        # 다른 모델의 status 는 이 스캔의 대상이 아니다.
        'Payout.objects.filter(pk=1, status="requested").update(status="confirmed")',
        'claim_transition(Payout, pk, from_state="a", to_state="b")',
        # 선언을 거치는 정상 경로 — 이름으로만 부른다, Contest 를 직접 언급하지 않는다.
        'claim_contest_transition("award", contest.id, now=now)',
        'claim_contest_in_place_update("judging-extension", contest.pk, now=now)',
        # #256 코드리뷰가 짚은 오탐 — Contest 는 필터 인자 안에 있을 뿐, 갱신 대상은
        # Payout.status 다. 수신자 사슬(.objects 바로 앞)만 보므로 이건 통과한다.
        'Payout.objects.filter(contest=Contest.objects.get(pk=1), status="requested").update(status="confirmed")',
    ],
)
def test_creation_and_declared_calls_pass(source: str):
    assert not _offenses_in(ast.parse(source)), f"이 코드는 통과했어야 한다: {source}"
