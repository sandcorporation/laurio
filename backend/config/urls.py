"""URLconf.

**Django admin 은 마운트되지 않는다** (#46, ADR-0019). admin 은 모델 행을 직접
편집할 수 있어서, Appeal·AppealRuling 을 그 화면에서 고칠 수 있는 한 감사 추적에는
우회로가 열린 채로 남는다. 사람이 판단하는 행위는 `/api/operator/*` 로만 한다.
"""

from django.urls import path

from config.api import api
from core.metrics import metrics_view

urlpatterns = [
    path("api/", api.urls),
    # 감시 스택이 긁는 자리(2026-09-21) — 내부 이름으로 온 요청에만 답한다(core/metrics.py).
    path("metrics", metrics_view),
]
