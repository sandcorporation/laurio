# Contest 전이 그래프는 한 곳에 선언되고, 그 선언 밖은 정적으로 막힌다

Status: Amended by ADR-0044 (2026-09-13 결정)

ADR-0003 은 Contest 상태 전이를 **어떻게** 하는가(조건부 UPDATE + rowcount, 주기 스캔)를
정했다. 그런데 **무엇이 유효한 전이인가**는 정하지 않았고, 그 결과 다섯 자리 —
`contests/apps.py`(스캔 셋: 마감·심사종료·과제마감)·`awards/api.py`(선정)·
`contests/models.py`(심사 연장)·`payments/models.py`(결제 확정)·
`contests/assignment_api.py`(과제 열기) — 에 전이가 흩어졌다. 이 그래프를 세려고
작정하고 훑은 사람도 하나(DRAFT→ASSIGNMENT_OPEN)를 놓쳤고, 그 다섯도 전부가
아니었다 — `seed_e2e_operator_queues.py` 가 `core.transitions.claim_transition` 을
Contest 에 대해 직접 불러 `contest-close` 간선을 손으로 재구현하고 있었다(#255 작업
중 발견). 관용구도 갈라져 있었다 — 넷은 `claim_transition` 을 썼지만 결제 확정
경로만 손으로 쓴 조건부 UPDATE 였다.

## 결정

`contests/transitions.py` 하나에 그래프를 선언한다.

- **전이**(`CONTEST_TRANSITIONS: dict[str, ContestTransition]`)와 **제자리 갱신**
  (`CONTEST_IN_PLACE_UPDATES: dict[str, ContestInPlaceUpdate]`)을 **타입으로** 가른다
  — 심사 연장(CLOSED→CLOSED)은 상태를 안 바꾸므로 전이 표에 넣으면 도메인에 없는
  자기 자신으로의 화살표가 다이어그램(#257)에 생긴다. 플래그(`is_in_place: bool`)로
  합치지 않는다 — 플래그는 다음에 잊을 수 있고, `from_state == to_state` 인 전이가
  없다는 불변식을 타입 자체가 강제하는 편이 (이 저장소가 `Classification` 에서 이미
  쓰는 것과 같은 원칙, 「타입으로 불변식을 강제한다」) 더 안전하다.
- 전이는 다시 **스캔**(`ScanContestTransition`, `due_field` 필수)과 **명시적 행위**
  (`ActionContestTransition`, 그 필드가 아예 없다)로 가른다 — "스캔이면 due_field 가
  있다"가 조건문이 아니라 타입 자체로 성립한다.
- 호출부는 `claim_contest_transition(name, pk, ...)`/`claim_contest_in_place_update
  (name, pk, ...)` 를 **이름으로만** 부른다 — `from_state`/`to_state` 를 다시 타이핑할
  자리가 없다. `name` 이 선언에 없으면 `KeyError` — 조용히 통과하지 않는다.
- **표는 실행기가 아니다.** 실제 전이는 여전히 `core.transitions.claim_transition`
  한 번의 조건부 UPDATE 다 — 이 선언이 답하는 것은 「이 전이가 정당한가」뿐이고,
  그 사실을 `tests/test_contest_transitions.py`(쿼리 수 1개 단언)가 고정한다.
  검증 전용 표(조건을 두 벌로 쓰면 언젠가 갈라지고, 갈라졌을 때 코드보다 나쁘다 —
  코드는 흩어져 있음을 스스로 드러내지만 표는 권위 있어 보인다)가 되지 않기 위해서다.
- **생성은 이 그래프 밖이다.** `contests/api.py`/`contests/assignment_api.py` 의
  생성 엔드포인트, 그리고 `seed_e2e_contests`/`seed_demo_contests` 는 「어느 상태에서
  왔는가」가 없다. 같은 파일의 `CREATION_STATES`(지금은 `{DRAFT}`, 실제 생성 API 가
  찍는 값)가 그 경계를 코드로 남긴다 — 도달 불가능 검사(#257)가 「생성으로도 못 오고
  간선으로도 못 오는 상태」를 판정할 때 이 집합을 더한다.
- **선언 밖에서 `Contest.status` 를 바꾸는 코드는 정적으로 막는다**(#256,
  `tests/test_contest_status_writes_are_declared.py`). AST 로 두 모양을 잡는다 —
  `<Contest 참조>.objects....update(status=...)` 류의 손으로 쓴 조건부 UPDATE, 그리고
  `claim_transition(Contest, ...)` 류의 원시 primitive 직접 호출. 완전한 방어가
  아니다(그 파일의 독스트링이 우회 가능성을 정직하게 적는다 — `**` 언패킹, import
  재바인딩, 헬퍼 함수 뒤에 숨기기, `x.status = ...` 직접 대입은 못 잡는다) — 실제로
  두 번 일어난 사고와 그 자연스러운 변형만 재현 불가능하게 만드는 좁은 방어다.
- **다이어그램은 선언의 부산물이다**(#257). `contest_transition_diagram()` 이
  `CONTEST_TRANSITIONS`/`CONTEST_IN_PLACE_UPDATES` 에서 mermaid `stateDiagram-v2`
  텍스트를 내고, `docs/features/backend.md` 에 그대로 박는다. 제자리 갱신은 화살표가
  아니라 `note` 로 그린다. CI 의 `pytest` 잡이 재생성해 그 문서와 글자 그대로 비교하므로
  낡을 수 없다. 같은 선언에서 그래프 자체의 모순 셋도 잡는다 — 도달 불가능한 상태
  (`CREATION_STATES` ∪ 모든 간선의 `to_state`), 스캔 등록부에 없는 시간기반 전이
  (`core.scans.SCAN_REGISTRY`), 끝이 아닌데(`TERMINAL_STATES` 에 없는데) 나가는
  간선이 없는 상태.

## Considered Options

**`Classification` 에 전이를 포함한 합성 표를 만든다.** ADR-0033 이 `kind` 를 합성
Classification 키로 넣는 것을 이미 검토하고 기각한 것과 같은 이유로 기각한다 —
전이(from→to)는 `Classification` 이 다루는 「질문 하나 = enum 전체 값 → 답」 모양이
아니다(같은 status 값이 여러 다른 from 을 가질 수 있는 것이 아니라, 정확히 특정
(from, to) 쌍이 유효한지를 묻는 관계형 질문이다). `core/classification.py` 자신의
독스트링도 "전이(from→to)는 질문이 아니다"라고 못박아 뒀다.

**`Contest.status` 를 문자열 대신 코드가 이름으로 참조하지 못하게 함수 시그니처에
`from_state`/`to_state` 를 그대로 남긴다.** 그러면 오타가 import 시점의 `AttributeError`
로 죽는 안전성은 유지되지만, 정확히 이 ADR 이 없애려는 문제(호출부가 그래프를 다시
타이핑한다)가 그대로 남는다. 대신 이름 하나로 좁히고, 그 대가(오타가 런타임 `KeyError`
로 미뤄지는 것)를 `tests/test_contest_transitions.py` 의 AST 완전성 검사(모든 호출부가
쓰는 이름이 선언과 같은 집합인지)로 좁혔다.

## Consequences

**문자열 이름이 옛 안전성을 잃는다.** 예전에는 오타가 `Contest.Status.X` 속성 접근
실패로 **import 시점**에 죽었다. 지금은 `claim_contest_transition("award-typo", ...)`
가 **그 코드가 실제로 실행되는 요청**에서야 `KeyError` 를 낸다. `tests/
test_contest_transitions.py::test_every_call_site_uses_a_name_the_declaration_
actually_has` 가 그 창을 정적 스캔으로 좁힌다 — 완벽하지 않다(변수로 넘긴 이름은
못 잡는다), 다만 지금 관용구(문자열 리터럴 하나)가 유지되는 한 충분하다.

**AST 정적 스캔 셋(#255/#256/#257) 모두 완전하지 않다.** 각 테스트 파일이 자기
한계를 독스트링에 적는다 — 이 저장소의 관례(설명 주석에서 이름을 언급하는 것과
실제 호출은 다르므로 AST 로 검사한다, `test_no_rescoring_code_path_exists_in_
appeals_app`)를 그대로 따르되, 완전성을 주장하지 않는다.

**`notifications/services.py` 는 아직 감사하지 않았다.** 거기도 `claim_transition`
을 손으로 부르는 자리가 대여섯 개 있어 같은 흩어짐의 조짐이지만, `claimed_at`·채널
폴백 순서 등 이 모듈과 다른 모양이라 하나의 사례에서 일반화하면 둘 다에 안 맞는
추상이 나오기 쉽다. `contests/transitions.py` 의 모듈 독스트링에 그 이름만 남겨
다음 사람이 증거 없이 다시 발견하지 않게 한다.
