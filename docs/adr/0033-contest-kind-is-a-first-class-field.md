# Contest.kind는 일급 필드다 — 과제 판정을 규율에서 구조로 (ADR-0028 개정)

Status: Superseded by ADR-0044 (2026-09-13 결정)

ADR-0028은 "Contest의 종류가 둘일 수 있다"를 새 테이블이 아니라 `Contest.Status` 값 둘로
풀었다. 그런데 그 ADR은 "이 Contest가 어느 종류인가"라는, 더 근본적인 질문에는 답을
남기지 않았다 — 그 답은 구현 당시 `Contest.is_assignment`라는 프로퍼티가 대신 만들었고,
`category_id`가 예약된 Assignment `Category` 행(`0013_assignment_category`, `is_active=False`)과
같은지로 판정했다. `DRAFT`를 공모전과 Assignment가 공유해(ADR-0028) status만으로는
구별할 수 없었기 때문에 그때는 그것이 유일하게 신뢰할 수 있는 신호였다.

**그 구조가 실제로 사고를 냈다(#207).** `_get_owned_draft_contest`가 `status != DRAFT`만
보는 바람에, 자격만 받고 본인확인은 하지 않은 Sponsor가 `POST /assignments` →
`PATCH /api/contests/{id}`(상금·카테고리 주입) → `POST /api/payments`로 상금 걸린 실제
공개 공모전을 열 수 있었다. `is_assignment`의 독스트링이 스스로 "새 호출부는 이 프로퍼티를
통해서만 판정한다"고 적어 뒀지만, 그것은 **규율**이었다 — 기억을 요구했고, 세 번 흩어져
있다 실제로 한 번 빠졌다.

## 결정

`Contest`에 생성 시점에 정해지는 `kind`(`CONTEST` / `ASSIGNMENT`) 필드를 더한다.
`contests.api.create_contest`·`contests.assignment_api.create_assignment`가 각각
`Contest.Kind.CONTEST`·`Contest.Kind.ASSIGNMENT`를 명시적으로 찍고, 이후 어떤 API도
이 값을 고치지 않는다. `Contest.is_assignment`는 이제 `self.kind ==
self.Kind.ASSIGNMENT` 하나만 본다 — 조회도, 캐시도, 예약된 기준행에 대한 의존도 없다.

카테고리 비교로 종류를 판정하던 자리(`ContestQuerySet.appeal_window_open`·
`contests.assignment_api._get_owned_assignment`의 `category=` 필터·
`contests/api.py`의 `.exclude(category=...)`)를 전부 `kind`로 바꾼다. `is_assignment`
프로퍼티가 이제 유일한 판정 표현이고, 그 프로퍼티 자체가 필드 하나를 그대로 반영하므로
"통해서만 판정하라"는 규율이 더 이상 필요하지 않다 — 다른 방식으로 판정하는 것 자체가
더 번거롭다.

`get_assignment_category()`는 남는다 — `Contest.category`가 non-null `PROTECT` FK라
Assignment를 만들 때 여전히 실제 `Category` 행을 꽂아야 한다(스펙 #197). 다만 그 함수의
`lru_cache`가 기대던 안전 조건이 바뀐다: 예전에는 "이 행이 절대 안 바뀐다"가 **식별
신호**의 안전 조건이었다(#231이 이 행을 편집하는 화면을 만들면 그 신호가 깨진다). 이제
`kind`가 식별을 대신하므로, 이 캐시는 "FK에 꽂을 행을 매번 다시 조회하지 않는다"는
성능 최적화로만 남는다.

## Considered Options

**`Classification`(질문 하나 = enum 모든 값 → 답, `core/classification.py`)에 `kind`를
포함한 합성 키를 쓴다.** `PAYABLE`·`EDITABLE` 같은 분류가 `(status, kind)` 쌍마다 답하게
되면 "과제에 대해 구성적으로 False"를 그 표 자체가 보장한다. 그런데 이 저장소의
`Classification`은 지금 `status` 하나만의 순수 함수이고 14개 분류·스캔 21개가 그 계약에
기대고 있다 — 합성 키로 바꾸면 그 전부를 다시 써야 하고, 정작 `kind`가 실제로 갈라야
하는 분류는 소수(`PAYABLE`·`EDITABLE`·`REOPENABLE` 등 결제·상금 관련)뿐이다. 이 티켓은
**모양만** 바꾸는 리팩터(#213 범위)이므로 채택하지 않는다 — 대신 `is_assignment`가
그 소수의 자리마다 `Classification`의 답 옆에서 함께 확인되는 지금 모양을 유지한다.

**`kind`를 API 응답에 노출해 프론트가 직접 분기한다.** #213은 백엔드 판정 구조만
다루고, 화면이 이미 `Contest.Status.*`로 필요한 문구를 받고 있어 지금 새 필드를
노출할 소비자가 없다. 필요해지면 그때 스키마에 더한다.

## Consequences

**`get_assignment_category()`가 없는 행에 대한 방어는 그대로 없다.** `kind`가 없앤
것은 "이 행이 식별 신호로 쓰인다"는 위험이지 "이 행이 사라지면 500이 난다"는 위험이
아니다 — `Contest.category`가 non-null FK인 한 Assignment 생성은 여전히 실제
`Category` 행을 요구한다. 그 방어는 별도 티켓감으로 남는다(#213 "함께 정리할 것").

**`kind`는 `editable=False`로 표시했지만 DB 제약이 아니다.** 이 저장소에 Django admin이
없으므로(ADR-0019) `editable=False`가 실제로 막는 자리는 없다 — "이 값을 바꿀 화면은
없다"는 의도를 코드에 남겨 두는 주석에 가깝다. 값을 실제로 지키는 것은 어떤 API
스키마도 `kind`를 받지 않는다는 사실이다(`ContestUpdateIn`·`AssignmentUpdateIn` 어디에도
없다).

**#231(운영자가 Category를 편집한다)의 전제가 성립한다.** 이제 예약된 Assignment
`Category` 행을 운영자가 이름을 고치거나 감춰도 "이 Contest가 과제인가"라는 판정은
전혀 흔들리지 않는다 — 그 판정이 이 행을 더 이상 보지 않기 때문이다. #231은 그래도
이 행 자체를 그 화면에서 편집·복구하지 못하게 별도로 막는다(운영자가 실수로 다른
용도의 "과제" 카테고리를 새로 살리는 것을 막기 위해서다 — 판정 안전성과는 다른 이유).
