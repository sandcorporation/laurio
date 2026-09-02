"""부팅 시점 어댑터 검증 (#83, ADR-0007/0020).

`PAYOUT_ADAPTER_MODE`·`SELLER_ADAPTER_MODE`가 배포 환경에서 "fake"도 아니고
실제로 쓸 수도 없으면(임포트 실패·인스턴스화 실패·계약 불충족) 부팅 자체를
거부한다. `storage.checks.check_storage_backend_is_importable`과 같은 원칙 —
지급과 Seller 등록은 시점이 다른 별개의 API라 어댑터도 설정도 따로지만
(payouts.adapters의 설명 참고), 부팅 가드는 같은 앱이 두 개를 나란히 등록한다.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import Error

from core.adapters import check_adapter_mode

from .adapters import PayoutAdapter, SellerAdapter


def check_payout_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="PAYOUT_ADAPTER_MODE", protocol=PayoutAdapter)


def check_seller_adapter_mode(app_configs: Any, **kwargs: Any) -> list[Error]:
    return check_adapter_mode(setting_name="SELLER_ADAPTER_MODE", protocol=SellerAdapter)
