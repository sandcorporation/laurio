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
경계 예외 표시를 요구한다).
"""

from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def _enqueue_one(contest_id: int) -> None:
    def _delay() -> None:
        from .tasks import index_contest

        # **큐에 못 넣는 것이 Contest 저장을 실패시키면 안 된다**(2026-09-21).
        # `on_commit` 콜백에서 난 예외는 `transaction.atomic()` 의 출구로 새어
        # 나가 요청이 통째로 500 이 된다 — 브로커(Redis)가 잠깐 없을 때
        # **공모전을 고치지도 공개하지도 못하게** 된다. 실제로 그렇게 났다
        # (#473 통합 검증 중, 브로커 없는 임시 서버에서 `PATCH /api/contests/1`
        # 이 500 이고 수정이 롤백됐다).
        #
        # 검색은 없어도 서비스가 도는 자리다 — 목록 API 는 색인이 죽어 있으면
        # DB 검색으로 물러나고(`contests.search.search_contests`), 매일 도는
        # `contest-search-reindex` 스캔이 빠진 문서를 다시 채운다. 그래서 여기서는
        # 삼키고 기록만 남긴다 — 알림 팬아웃이 호출자의 응답을 막지 않는 것과
        # 같은 원칙이다(`notifications.services`).
        try:
            index_contest.delay(contest_id)
        except Exception:  # noqa: BLE001 - 색인 큐잉 실패가 저장을 되돌리면 안 된다.
            logger.exception("Contest(pk=%s) 색인 큐잉 실패 — 저장 자체는 끝났다", contest_id)

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
            # 위 `_enqueue_one` 과 같은 이유로 삼킨다 — 개최자 표시 이름 하나를
            # 바꾸다 브로커가 없어 저장이 통째로 실패하면 안 된다.
            try:
                index_contest.delay(contest_id)
            except Exception:  # noqa: BLE001 - 색인 큐잉 실패가 저장을 되돌리면 안 된다.
                logger.exception("Contest(pk=%s) 색인 큐잉 실패 — 저장 자체는 끝났다", contest_id)

    transaction.on_commit(_enqueue_all)
