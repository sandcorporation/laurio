"""Assignment(ADR-0028) 전용 `Category` 기준데이터 (#207).

`Contest.category`는 non-null `PROTECT` FK라 nullable로 바꾸지 않는다(스펙 #197) —
Assignment를 만들 때 이 행이 자동으로 배정된다. Sponsor는 이 값을 고르지 않는다
(`AssignmentCreateIn`에 `category_id`가 없다).

**`is_active=False`로 둔다** — `GET /contests/categories`(공개 목록)는 `is_active=True`만
돌려주므로 이 행이 새지 않고, `create_contest`·`update_draft_contest`도 같은 필터로
Category를 조회하므로(`Category.objects.get(id=..., is_active=True)`) 공모전이 실수로든
의도로든 이 카테고리를 고를 길이 없다.

**"이 Contest는 Assignment다"의 판정에는 더 이상 쓰이지 않는다(#213, ADR-0033).**
`Contest.kind`가 생성 시점에 그 답을 직접 갖고 있으므로, `contest.category_id`를 이 행의
id와 비교하는 코드는 이제 저장소에 없다 — 이 함수는 오직 `Contest.category`(non-null FK)에
꽂을 실제 행을 구하는 용도로만 남는다. 그래서 `get_assignment_category`가 없는 행에
대해 방어가 없다는 문제(`.get()`이 그대로 `Category.DoesNotExist`를 올린다)는 여전히
남아 있다 — `kind` 필드가 없앤 것은 "이 캐시가 이 행이 절대 안 바뀐다는 전제에 기댄
식별 신호"라는 위험이지, 이 행 자체가 사라질 위험이 아니다.

이름은 `prune_e2e_junk`(#183)가 지우는 접두어(`e2e`·`[e2e`)와 겹치지 않는다 — 그 명령이
이 행을 실수로 걷어가면 새 Assignment를 열 때마다 500이 난다.
"""

from __future__ import annotations

from functools import lru_cache

from .models import Category

ASSIGNMENT_CATEGORY_NAME = "과제"


@lru_cache(maxsize=1)
def get_assignment_category() -> Category:
    """마이그레이션(`0013_assignment_category`)이 이미 심어 둔 행을 읽기만 한다 — 요청
    경로에서 `get_or_create`를 쓰지 않는 이유는, 이름이 이미 있는데 `is_active`가
    운영자의 다른 조작으로 달라져 있는 경우를 조용히 되살리지 않기 위해서다.

    **프로세스당 한 번만 조회한다**(`storage/adapters/s3.py`의 `lru_cache(maxsize=1)`와
    같은 관용구) — 이 행은 마이그레이션이 한 번 심고 나면 절대 바뀌지 않는다(이름을
    바꿀 운영자 화면도, 지울 경로도 없다). `contests.assignment_api.create_assignment`가
    새 Assignment를 만들 때마다 이 함수를 부르므로(#213 이전에는
    `contests.models.Contest.is_assignment`도 인스턴스마다, 때로는 목록 한 화면에서
    행마다 불렀다), 캐시가 없으면 매번 쿼리가 나간다. 이 행이 실제로 바뀌는 유일한
    경로는 손으로 마이그레이션을 다시 쓰는 것뿐이고, 그런 변경은 어차피 프로세스
    재시작을 동반한다.
    """

    return Category.objects.get(name=ASSIGNMENT_CATEGORY_NAME)
