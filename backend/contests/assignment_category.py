"""Assignment(ADR-0028) 전용 `Category` 기준데이터 (#207).

`Contest.category`는 non-null `PROTECT` FK라 nullable로 바꾸지 않는다(스펙 #197) —
Assignment를 만들 때 이 행이 자동으로 배정된다. Sponsor는 이 값을 고르지 않는다
(`AssignmentCreateIn`에 `category_id`가 없다).

**`is_active=False`로 둔다** — `GET /contests/categories`(공개 목록)는 `is_active=True`만
돌려주므로 이 행이 새지 않고, `create_contest`·`update_draft_contest`도 같은 필터로
Category를 조회하므로(`Category.objects.get(id=..., is_active=True)`) 공모전이 실수로든
의도로든 이 카테고리를 고를 길이 없다 — `contest.category_id == 이 행의 id`가 "이 Contest는
Assignment 다"의 신뢰할 수 있는 신호가 되는 이유다(DRAFT는 공모전과 Assignment가 공유하므로
status만으로는 구별할 수 없다, ADR-0028).

이름은 `prune_e2e_junk`(#183)가 지우는 접두어(`e2e`·`[e2e`)와 겹치지 않는다 — 그 명령이
이 행을 실수로 걷어가면 새 Assignment를 열 때마다 500이 난다.
"""

from __future__ import annotations

from .models import Category

ASSIGNMENT_CATEGORY_NAME = "과제"


def get_assignment_category() -> Category:
    """마이그레이션(`0013_assignment_category`)이 이미 심어 둔 행을 읽기만 한다 — 요청
    경로에서 `get_or_create`를 쓰지 않는 이유는, 이름이 이미 있는데 `is_active`가
    운영자의 다른 조작으로 달라져 있는 경우를 조용히 되살리지 않기 위해서다."""

    return Category.objects.get(name=ASSIGNMENT_CATEGORY_NAME)
