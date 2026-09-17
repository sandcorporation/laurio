"""공모전 검색 색인을 전체 재색인한다 (#450, 부모 #444 스펙 "전체 재색인 관리 명령").

`core.scans.SCAN_REGISTRY`의 `contest-search-reindex` 스캔과 같은 동작
(`get_search_adapter().rebuild()`)을 사람이 직접 한 번 돌리고 싶을 때 쓴다 —
운영자가 색인이 어긋났다고 판단했을 때(부모 스펙 "필요하면 명령 하나로 전체를
다시 만들고 싶다") tick·beat를 기다리지 않는다.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from contests.search import get_search_adapter


class Command(BaseCommand):
    help = "공모전 검색 색인을 전체 재색인한다(어댑터가 fake면 기록만 다시 채운다)."

    def handle(self, *args, **options) -> None:
        get_search_adapter().rebuild()
        self.stdout.write(self.style.SUCCESS("공모전 검색 색인을 전체 재색인했습니다."))
