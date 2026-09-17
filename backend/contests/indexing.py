"""공모전 검색 색인을 맞추는 신호 수신자 (#450, 부모 #444 스펙).

Contest·그 카테고리·요구형태·개최자 표시 이름이 바뀌면 트랜잭션 커밋 뒤
`contests.tasks.index_contest`를 큐에 넣는다 — `contests/apps.py`의 `ready()`가
이 함수들을 `post_save`/`m2m_changed`에 연결한다. 모델을 이 모듈 최상단에서
불러오지 않는 이유는 다른 앱들의 `ready()`와 같다: 앱 레지스트리가 준비되기
전(설정 로딩 시점)에 모델을 참조하면 `AppRegistryNotReady`로 죽는다.

**개최자 표시 이름이 바뀌면 그 개최자의 공모전 전부를 다시 큐에 넣는다** —
검색 문서 필드(`sponsor_display_name`)가 Contest가 아니라
`accounts.SponsorProfile`에 살기 때문이다(부모 스펙 "Contest·그 카테고리·
요구형태·개최자 표시 이름이 바뀌면"). `SponsorProfile`은 공유층(accounts)의
모델이고 이 파일은 기능 앱(contests)에 있으므로, 참조 방향은 앱 경계 테스트가
허용하는 쪽이다(`tests/test_app_boundaries.py` — 기능 앱이 공유층을 부르는
것은 막히지 않는다. 반대 방향, 공유층이 기능 앱을 부르는 것만
`APP-BOUNDARY-EXCEPTION`을 요구한다).
"""

from __future__ import annotations

from django.db import transaction


def _enqueue_one(contest_id: int) -> None:
    def _delay() -> None:
        from .tasks import index_contest

        index_contest.delay(contest_id)

    transaction.on_commit(_delay)


def contest_saved(sender, instance, **kwargs) -> None:
    """`Contest.save()` 이후 — 제목·카테고리·상태 등 어느 필드가 바뀌었든
    다시 색인한다. 같은 값으로 다시 색인해도 멱등이므로 "정말 바뀐
    필드인가"를 가리지 않는다 — 그 판정 비용이 색인 자체보다 비싸다."""

    _enqueue_one(instance.id)


def contest_deliverable_types_changed(sender, instance, action, **kwargs) -> None:
    """`Contest.deliverable_types`(M2M)는 `post_save`를 타지 않는다 — 요구형태
    선택이 바뀌면 검색 문서의 `deliverable_type_names`도 갈리므로 따로 듣는다."""

    if action not in {"post_add", "post_remove", "post_clear"}:
        return
    _enqueue_one(instance.id)


def sponsor_display_name_saved(sender, instance, **kwargs) -> None:
    sponsor_id = instance.id

    def _enqueue_all() -> None:
        from .models import Contest
        from .tasks import index_contest

        contest_ids = Contest.objects.filter(sponsor_id=sponsor_id).values_list("id", flat=True)
        for contest_id in contest_ids:
            index_contest.delay(contest_id)

    transaction.on_commit(_enqueue_all)
