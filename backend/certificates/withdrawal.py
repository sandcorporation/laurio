"""탈퇴한 받는 사람의 상장(#1130, 스펙 #1071 G6).

탈퇴는 계정이 아니라 신원 값을 파기한다(`docs/legal/personal-data.md` 파기 표). 상장 행(번호·상·발급일)은
남기고, 받는 사람 이름과 그 이름이 박힌 발급 PDF 를 즉시 파기하며 확인 페이지를 닫는다.

PDF 객체는 탈퇴가 커밋된 뒤 지운다. 지우지 못해도 탈퇴는 막지 않는다 — 행이 이미 그 키를 놓았으므로
화면·API 어디서도 그 파일에 닿지 않고, 남은 객체는 키와 함께 오류 로그(GlitchTip)로 남겨 손으로 걷는다.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from storage.adapters import Bucket, get_storage_adapter

from .models import Certificate

logger = logging.getLogger(__name__)


def _delete_pdfs(keys: list[str]) -> None:
    adapter = get_storage_adapter()
    for key in keys:
        try:
            adapter.delete_object(key, bucket=Bucket.PRIVATE)
        except Exception:  # 저장소 오류의 종류를 가리지 않는다 — 탈퇴는 이미 끝났다
            logger.exception("탈퇴한 받는 사람의 상장 PDF 를 지우지 못했다: %s", key)


def hide_on_withdrawal(sender, user, **kwargs) -> None:
    mine = Certificate.objects.filter(recipient=user)
    keys = [key for key in mine.values_list("pdf_object_key", flat=True) if key]
    mine.filter(recipient_hidden_at__isnull=True).update(recipient_hidden_at=timezone.now())
    mine.update(recipient_name="", pdf_object_key="")
    if keys:
        transaction.on_commit(lambda: _delete_pdfs(keys))
