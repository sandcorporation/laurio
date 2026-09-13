"""Contest 상태 전이 그래프 — 한 곳에 선언한다 (#255, ADR-0003 후속).

전이는 예전에 다섯 자리에 흩어져 있었다 — `contests/apps.py`(스캔 셋: 마감·심사종료·과제마감),
`awards/api.py`(선정), `contests/models.py`(심사 연장), `payments/models.py`(결제 확정),
`contests/assignment_api.py`(과제 열기). 이 그래프를 세려고 작정하고 훑은 사람도 다섯 중
하나(DRAFT→ASSIGNMENT_OPEN)를 빠뜨렸다 — 한 곳에서 답할 수 없었기 때문이다.

**그 다섯도 전부가 아니었다.** `accounts/management/commands/seed_e2e_operator_queues.py`
가 e2e 픽스처를 좁게 만들려고 `contest-close` 간선(PUBLISHED→CLOSED)을
`core.transitions.claim_transition` 으로 **직접**, `judging_ends_at` 계산까지
손으로 재현해 다시 불렀다 — 정확히 이 티켓이 끝내려는 모양(간선 하나가 두 곳에서
따로 산다)이었다. 지금은 이 모듈의 `claim_contest_transition("contest-close", ...)`
를 그대로 재사용한다. **이 모듈이 이 그래프가 사는 유일한 곳**이라는 이 파일의 주장은
이 사실까지 확인한 뒤에야 참이다 — enumerate 는 "다섯 자리"가 아니라 "Contest.status
를 쓰는 모든 자리"를 훑어야 끝난다(위 배경의 재발과 같은 실수를 반복하지 않으려면).

**표는 실행기가 아니다.** 실제 전이는 여전히 `core.transitions.claim_transition` 한 번의
조건부 UPDATE 다(ADR-0003) — 이 모듈이 답하는 것은 「이 전이가 정당한가」뿐이다. 다만
**하중을 받는다**: 호출부는 `CONTEST_TRANSITIONS`/`CONTEST_IN_PLACE_UPDATES` 에 있는
**이름**으로만 `claim_contest_transition`/`claim_contest_in_place_update` 를 부를 수 있고,
그 함수들은 그 이름에 선언된 `from_state`/`to_state` 를 그대로 조건부 UPDATE 에 쓴다 —
호출부가 `from_state`/`to_state` 를 다시 타이핑할 자리 자체가 없다. 이름이 선언에 없으면
`KeyError` 로 즉시 죽는다 — 조용히 통과하지 않는다.

**「제자리 갱신」은 전이가 아니다.** 심사 연장(`JudgingExtensionPayment.on_paid`)은
`CLOSED→CLOSED` 로 `claim_transition` 을 재사용하지만 상태를 바꾸지 않는다 — 조건부 UPDATE
규율과 `auto_now` 를 얻으려고 그 기계를 빌려 쓴 것뿐이다. 이것을 `CONTEST_TRANSITIONS` 에
간선으로 넣으면 도메인에 없는 자기 자신으로의 화살표가 생긴다(#257 다이어그램이 그것을
그대로 그리게 된다) — 그래서 별도 타입 `ContestInPlaceUpdate` 로 갈라 `CONTEST_IN_PLACE_
UPDATES` 에 선언한다. 플래그 하나(`is_in_place: bool`)로 합치지 않는 이유도 같다 — 플래그는
다음에 잊을 수 있는 것이고, 이 저장소의 관용구는 `Classification`(질문마다 enum 전체에
답을 강제)처럼 **타입으로 불변식을 강제**하는 쪽이다.

**스캔/행위 구분도 문자열 플래그가 아니라 타입이다.** `ScanContestTransition` 은
`due_field` 를 **필수**로 요구하고, `ActionContestTransition` 은 아예 그 필드가 없다 —
"스캔이면 due_field 가 있다"가 `__post_init__` 의 조건문이 아니라 타입 자체로 성립한다.
`contest_transition_spec` 이 `isinstance` 로 스캔 간선만 받는 것도 같은 이유다.

**생성은 이 그래프 밖이다.** 초안 개최·과제 생성·`seed_e2e_contests`(임의 상태로 Contest 를
직접 만든다)는 「어느 상태에서 왔는가」가 없다 — 이 표가 통제하는 것은 이미 존재하는
Contest 행이 상태를 옮기는 사건이지, 행이 태어나는 사건이 아니다. `Contest.objects.create(...)`
는 이 모듈이 관여하지 않는다(#256 이 그 경계를 코드로 강제한다).

**두 번째 후보.** `notifications/services.py` 에도 `claim_transition` 을 손으로 부르는
자리가 대여섯 개 있다 — 같은 흩어짐의 조짐이다. 다만 그쪽은 `claimed_at`·채널
폴백 순서 등 이 모듈과 다른 모양을 갖고 있어 아직 아무도 감사하지 않았다. 하나의
사례에서 일반화하면 둘 다에 안 맞는 추상이 나오기 쉬우므로, 지금은 이름만 남겨
다음 사람이 증거 없이 다시 발견하지 않게 한다 — 일반화된 `core.TransitionGraph`
같은 것을 만들 때가 오면 이 자리와 그 자리 둘 다를 보고 설계한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.transitions import TransitionSpec
from core.transitions import claim_transition as _claim_transition

from .models import Contest

# Contest 가 상태를 담는 컬럼 — 이 모듈이 아는 유일한 값이라 상수로 한 번만 적는다.
_STATUS_FIELD = "status"


@dataclass(frozen=True)
class _ContestTransitionBase:
    """전이 간선의 공통 뼈대 — `from_state != to_state` 를 생성 시점에 강제한다."""

    name: str
    from_state: str
    to_state: str

    def __post_init__(self) -> None:
        if self.from_state == self.to_state:
            raise ValueError(
                f"{self.name!r}: from_state == to_state 인 전이는 없다 — 제자리 갱신은 "
                "ContestInPlaceUpdate 로 선언한다"
            )


@dataclass(frozen=True)
class ScanContestTransition(_ContestTransitionBase):
    """시각이 지나면 스캔이 도는 간선 — `due_field` 가 그 기준 컬럼이다(필수)."""

    due_field: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.due_field:
            raise ValueError(f"{self.name!r}: ScanContestTransition 은 due_field 가 있어야 한다")


@dataclass(frozen=True)
class ActionContestTransition(_ContestTransitionBase):
    """사람(또는 다른 도메인 사건)의 명시적 호출이 도는 간선 — 기다리는 스캔이 없다."""


ContestTransition = ScanContestTransition | ActionContestTransition


CONTEST_TRANSITIONS: dict[str, ContestTransition] = {
    # 스캔 셋 — contests/apps.py 가 이 선언에서 TransitionSpec 을 파생해 등록한다.
    "contest-close": ScanContestTransition(
        name="contest-close",
        from_state=Contest.Status.PUBLISHED,
        to_state=Contest.Status.CLOSED,
        due_field="deadline_at",
    ),
    "contest-judging-end": ScanContestTransition(
        name="contest-judging-end",
        from_state=Contest.Status.CLOSED,
        to_state=Contest.Status.JUDGING_ENDED,
        due_field="judging_ends_at",
    ),
    "assignment-close": ScanContestTransition(
        name="assignment-close",
        from_state=Contest.Status.ASSIGNMENT_OPEN,
        to_state=Contest.Status.ASSIGNMENT_CLOSED,
        due_field="deadline_at",
    ),
    # 명시적 행위 셋.
    "publish-on-payment": ActionContestTransition(
        name="publish-on-payment",
        from_state=Contest.Status.DRAFT,
        to_state=Contest.Status.PUBLISHED,
    ),
    "award": ActionContestTransition(
        name="award",
        from_state=Contest.Status.CLOSED,
        to_state=Contest.Status.AWARDED,
    ),
    "open-assignment": ActionContestTransition(
        name="open-assignment",
        from_state=Contest.Status.DRAFT,
        to_state=Contest.Status.ASSIGNMENT_OPEN,
    ),
}


@dataclass(frozen=True)
class ContestInPlaceUpdate:
    """전이가 아닌 제자리 갱신 하나 — `from_state == to_state`. `claim_transition` 의
    조건부 UPDATE 규율과 `auto_now` 를 빌려 쓸 뿐 상태는 바뀌지 않는다.

    `name` 필드가 없다(`ContestTransition` 과 다르다) — 이 레지스트리는 하나뿐이고
    이름은 `CONTEST_IN_PLACE_UPDATES` 의 딕셔너리 키 하나로만 산다. `ContestTransition`
    처럼 `name=` 을 따로 들고 있으면 키와 그 값이 갈릴 수 있는 두 번째 자리가 생긴다
    (아래 `CONTEST_TRANSITIONS` 의 키/`name` 일치 검사가 정확히 그 문제를 겨냥한다) —
    필드 자체를 없애면 그 문제가 애초에 생기지 않는다."""

    state: str


CONTEST_IN_PLACE_UPDATES: dict[str, ContestInPlaceUpdate] = {
    "judging-extension": ContestInPlaceUpdate(state=Contest.Status.CLOSED),
}


_duplicate_names = set(CONTEST_TRANSITIONS) & set(CONTEST_IN_PLACE_UPDATES)
if _duplicate_names:
    # core.scans.register_scan 이 스캔 이름 충돌을 즉시 터뜨리는 것과 같은 이유 —
    # 이름 하나가 두 표 중 어느 쪽으로도 풀릴 수 있으면 조회가 "우연히 먼저 부른 쪽"으로
    # 조용히 갈린다.
    raise RuntimeError(
        f"전이와 제자리 갱신 이름이 겹친다: {sorted(_duplicate_names)} — 하나의 이름은 "
        "전이 아니면 제자리 갱신, 둘 다일 수 없다"
    )

_renamed_transitions = {
    key: edge.name for key, edge in CONTEST_TRANSITIONS.items() if edge.name != key
}
if _renamed_transitions:
    # ContestTransition 은 __post_init__ 의 오류 메시지에 자기 이름을 적어야 해서
    # `name` 필드를 그대로 갖고 있다(위 ContestInPlaceUpdate 와 다른 점) — 그런데
    # 그 값이 딕셔너리 키와 갈리면 __post_init__ 의 오류 메시지·다이어그램의 간선
    # 라벨(딕셔너리 키를 쓴다)이 서로 다른 이름을 말하게 된다. 하나를 고치고 다른
    # 하나를 잊는 사고를 여기서 막는다.
    raise RuntimeError(
        f"CONTEST_TRANSITIONS 의 키와 그 값의 name 이 다르다: {_renamed_transitions} — "
        "둘 다 같은 문자열이어야 한다"
    )


def _claim_status(pk, *, from_state: str, to_state: str, now, extra_fields) -> bool:
    """`claim_contest_transition`·`claim_contest_in_place_update` 가 공유하는 몸통 —
    `state_field` 를 한 곳(`_STATUS_FIELD`)에서만 적는다."""

    return _claim_transition(
        Contest,
        pk,
        from_state=from_state,
        to_state=to_state,
        state_field=_STATUS_FIELD,
        now=now,
        extra_fields=extra_fields,
    )


def claim_contest_transition(name: str, pk, *, now=None, extra_fields: dict | None = None) -> bool:
    """선언된 간선 `name` 으로 `Contest(pk)` 를 조건부 UPDATE 한다.

    `name` 이 `CONTEST_TRANSITIONS` 에 없으면 `KeyError` — 선언되지 않은 간선은 이 함수를
    통해서는 애초에 만들 수 없다(호출부가 `from_state`/`to_state` 를 직접 넘기지 못하므로).
    실제 UPDATE 는 `core.transitions.claim_transition` 한 번뿐이다(ADR-0003) — 이 함수는
    그 앞에서 이름을 선언으로 풀어 줄 뿐이다.
    """

    edge = CONTEST_TRANSITIONS[name]
    return _claim_status(pk, from_state=edge.from_state, to_state=edge.to_state, now=now, extra_fields=extra_fields)


def claim_contest_in_place_update(
    name: str, pk, *, now=None, extra_fields: dict | None = None
) -> bool:
    """선언된 제자리 갱신 `name` 으로 `Contest(pk)` 를 조건부 UPDATE 한다 — 상태는 바뀌지
    않는다(`from_state == to_state`). `name` 이 `CONTEST_IN_PLACE_UPDATES` 에 없으면
    `KeyError`."""

    update = CONTEST_IN_PLACE_UPDATES[name]
    return _claim_status(pk, from_state=update.state, to_state=update.state, now=now, extra_fields=extra_fields)


def contest_transition_spec(name: str, *, extra_fields=None) -> TransitionSpec:
    """`core.scans.register_scan(core.scans.transition_scan(...))` 이 쓰는
    `core.transitions.TransitionSpec` 을 선언에서 파생한다 — `contests/apps.py` 가
    `from_state`/`to_state`/`due_field` 를 다시 적지 않는다.

    `name` 이 `ScanContestTransition` 이 아니면(=명시적 행위 간선이면) `ValueError` —
    apps.py 가 실수로 「award」 같은 행위 간선을 스캔으로 등록하려 드는 것을 막는다.
    """

    edge = CONTEST_TRANSITIONS[name]
    if not isinstance(edge, ScanContestTransition):
        raise ValueError(f"{name!r} 은 스캔으로 도는 전이가 아니다({type(edge).__name__})")
    return TransitionSpec(
        model=Contest,
        due_field=edge.due_field,
        from_state=edge.from_state,
        to_state=edge.to_state,
        state_field=_STATUS_FIELD,
        extra_fields=extra_fields,
    )


# ---------------------------------------------------------------------------
# 그래프의 모순을 잡는 세 검사가 읽는 두 선언 (#257).
# ---------------------------------------------------------------------------

#: 생성(이 그래프 밖, 위 모듈 독스트링)이 실제로 만들어내는 상태 — `contests/api.py`의
#: `create_contest`(과제 라우터가 걷히기 전에는 `contests/assignment_api.py`의
#: `create_assignment`도 있었다, #361)가 지금 `Contest.Status.DRAFT` 하나만
#: 리터럴로 찍는다. 도달 불가능 검사(아래 그래프 검사
#: 참고)가 "이 상태는 간선으로도 못 오고 생성으로도 못 온다"를 판정할 때 이 집합을
#: 더한다 — 시드(`seed_e2e_contests`·`seed_demo_contests`)가 임의 상태를 변수로
#: 찍는 것은 생성의 정의 자체가 아니라 테스트 픽스처의 특권이라 여기 넣지 않는다.
#:
#: **손으로 든 값이다 — 코드가 자동으로 맞춰 주지 않는다.** 이 상수와 실제
#: `Contest.objects.create(status=Contest.Status.DRAFT, ...)` 호출 세 곳이 갈리지
#: 않는지는 `tests/test_contest_status_writes_are_declared.py` 의 AST 스캔이 정적으로
#: 확인한다(리터럴 `Contest.Status.<이름>` 만 — 시드처럼 변수를 넘기는 자리는 정적으로
#: 확인할 수 없어 그 스캔도 건너뛴다, 그 파일의 독스트링 참고).
CREATION_STATES: frozenset[str] = frozenset({Contest.Status.DRAFT})

#: 끝 상태 — 나가는 간선이 없어도 정상인 상태들(선정 완료·심사기간 종료·과제 마감).
#: 「나가는 길이 없는 상태」 검사(아래)가 이 목록에 없는 상태는 반드시 나가는 간선이
#: 있어야 한다고 요구한다 — 이 목록에 없이 나가는 길이 없으면 그건 갇힌 것이다.
#:
#: **`{to_state 전체} - {from_state 전체}` 로 파생하지 않는다 — 일부러다.** 지금은
#: 그 파생이 이 리터럴과 우연히 같은 값을 내놓겠지만, "끝 상태 = 나가는 간선이 없는
#: 상태"로 정의를 뒤집으면 `test_every_non_terminal_state_has_an_outgoing_edge` 가
#: 항상 참인 동어반복이 된다 — 갇힌 상태가 생겨도 그 상태가 자동으로 "끝"으로
#: 재분류되어 테스트가 계속 초록으로 남는다. 그러면 그 테스트는 아무것도 지키지
#: 않으면서 지키고 있는 것처럼 보인다(위 도달 불가능 검사의 「래칫」과 같은 종류의
#: 함정이지만 방향이 반대다 — 그건 오늘 아무것도 안 잡아서 위험해 보이고, 이건
#: 스스로 조용해질 수 있어서 위험하다). 그래서 끝 상태는 도메인 판단으로 사람이
#: 적는다 — 나가는 간선이 없다는 사실에서 역산하지 않는다.
TERMINAL_STATES: frozenset[str] = frozenset(
    {Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED, Contest.Status.ASSIGNMENT_CLOSED}
)

#: 시간기반 전이인데 **의도적으로** 스캔 등록부에 없는 이름 (#361, 부모 #358).
#:
#: 과제 라우터(`contests.assignment_api`)가 걷히며 `contests/apps.py`가 더는
#: "assignment-close" 스캔을 등록하지 않는다 — 그 스캔을 계속 등록해 두면 이제
#: `Contest`를 `DRAFT -> ASSIGNMENT_OPEN`으로 옮길 방법 자체가 없으므로(그
#: 유일한 문이던 `open_assignment`도 함께 걷혔다) 영원히 빈 후보만 도는 스캔이
#: 된다(#358 user story 11 "도달할 수 없는 API와 영원히 빈 후보를 도는 스캔이
#: 없기를 원한다"). 그렇다고 이 파일의 "assignment-close" 간선 자체를 지우면
#: `Contest.Status.ASSIGNMENT_OPEN`/`ASSIGNMENT_CLOSED`가 도달 불가능·갇힌
#: 상태가 된다 — 그 두 값은 `Contest.kind`와 함께 아직 모델에 남아 있다(스키마
#: 정리는 다음 티켓의 몫, CLAUDE.md "호출부를 먼저, 스키마를 나중에"). 그래서
#: 간선은 선언에 그대로 두고, 아래 검사에서만 이 이름을 봐 준다 — 이 예외는
#: 그 모델·필드가 실제로 걷히는 날 이 상수와 함께 지운다.
SCAN_EDGES_INTENTIONALLY_UNREGISTERED: frozenset[str] = frozenset({"assignment-close"})


@dataclass(frozen=True)
class ContestGraphValidation:
    """`validate_contest_transition_graph()` 의 결과 — 그래프 자체의 모순 셋."""

    unreachable_states: frozenset[str]
    unregistered_scan_edges: frozenset[str]
    stuck_states: frozenset[str]

    @property
    def problems(self) -> list[str]:
        problems = []
        if self.unreachable_states:
            problems.append(
                f"어느 간선으로도, 생성으로도 닿지 않는 상태: {sorted(self.unreachable_states)}"
            )
        if self.unregistered_scan_edges:
            problems.append(
                f"시간기반 전이인데 스캔 등록부에 없다(영원히 안 일어난다): "
                f"{sorted(self.unregistered_scan_edges)}"
            )
        if self.stuck_states:
            problems.append(
                f"끝 상태가 아닌데 나가는 간선이 없다(갇힌 상태): {sorted(self.stuck_states)}"
            )
        return problems


def validate_contest_transition_graph(*, scan_registry) -> ContestGraphValidation:
    """그래프 자체가 스스로 모순인 세 경우를 찾는다(#257) — 도달 불가능한 상태, 스캔
    등록부에 없는 시간기반 전이, 끝이 아닌데 나가는 간선이 없는 상태(갇힌 상태).

    `scan_registry` 를 인자로 받아 이 함수를 순수하게 남긴다 — `core.scans` 를 이
    모듈이 임포트하지 않는다(호출부, 즉 테스트가 `core.scans.SCAN_REGISTRY` 를 넘긴다).

    **`django.core.checks` 로 등록하지 않는다 — 의도적인 선택이다.** 이 모듈 위쪽의
    「이름이 겹치면 즉시 죽는다」 두 가드(`_duplicate_names`·`_renamed_transitions`)는
    부팅 시점에 예외로 터진다. 이 함수가 찾는 셋은 그러지 않는다 — 이유가 다르기
    때문이다. 이름 충돌은 **런타임 정확성 버그**다: 조회가 조용히 엉뚱한 간선으로
    풀려 실제 요청이 잘못된 UPDATE 를 낸다. 이 함수가 찾는 것(도달 불가능·미등록
    스캔·갇힌 상태)은 **모델링 결함**이다 — 지금 선언된 간선의 동작을 하나도 깨뜨리지
    않는다, 다만 그래프의 모양이 이상하다는 신호다. 정확성 버그는 어떤 환경(로컬·CI·
    staging·prod)에서도 조용히 넘어가면 안 되므로 부팅 자체를 막고, 모델링 결함은
    배포 전에 CI 의 `pytest` 잡(모든 티켓이 이미 통과해야 하는 게이트, CLAUDE.md
    「티켓을 닫는 기준」)이 잡으면 충분하다 — `check_adapter_mode`(#83)처럼 프로덕션
    부팅 자체를 거부할 만큼 위험하지 않다.
    """

    reachable = set(CREATION_STATES) | {edge.to_state for edge in CONTEST_TRANSITIONS.values()}
    unreachable_states = frozenset(set(Contest.Status) - reachable)

    unregistered_scan_edges = frozenset(
        name
        for name, edge in CONTEST_TRANSITIONS.items()
        if isinstance(edge, ScanContestTransition)
        and name not in scan_registry
        and name not in SCAN_EDGES_INTENTIONALLY_UNREGISTERED
    )

    non_terminal = set(Contest.Status) - TERMINAL_STATES
    have_outgoing_edge = {edge.from_state for edge in CONTEST_TRANSITIONS.values()}
    stuck_states = frozenset(non_terminal - have_outgoing_edge)

    return ContestGraphValidation(
        unreachable_states=unreachable_states,
        unregistered_scan_edges=unregistered_scan_edges,
        stuck_states=stuck_states,
    )


def contest_transition_diagram() -> str:
    """`CONTEST_TRANSITIONS`/`CONTEST_IN_PLACE_UPDATES` 에서 mermaid `stateDiagram-v2`
    텍스트를 낸다(#257) — 손으로 그리지 않는다.

    전이는 화살표(`A --> B : 이름`)로, 제자리 갱신은 화살표가 아니라 `note` 로 그린다
    — 심사 연장이 CLOSED 에서 CLOSED 로 가는 화살표를 그리면 도메인에 없는 자기
    자신으로의 전이가 그려진다(위 모듈 독스트링 「제자리 갱신은 전이가 아니다」).

    `docs/features/backend.md` 의 「Contest 의 상태」 절에 붙는 블록과 **글자 그대로**
    같아야 한다 — `tests/test_contest_transition_graph.py` 가 재생성해 그 파일과
    비교한다(다이어그램이 선언과 갈라지면 그 테스트가 빨개진다). 사람이 다시 만들
    때는 `cd backend && uv run python manage.py print_contest_transition_diagram`.
    """

    lines = ["stateDiagram-v2"]
    for name, edge in CONTEST_TRANSITIONS.items():
        lines.append(f"    {edge.from_state} --> {edge.to_state} : {name}")
    for name, update in CONTEST_IN_PLACE_UPDATES.items():
        lines.append(f"    note right of {update.state} : {name} (제자리 갱신, 상태 불변)")
    return "\n".join(lines)
