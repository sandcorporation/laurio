"""시간 기반 상태 전이 메커니즘 (ADR-0003).

핵심 불변식: 전이는 항상 `UPDATE ... WHERE id=? AND state='이전상태'` 형태의 조건부
UPDATE 로만 수행하고, rowcount 가 1일 때만 "전이가 실제로 일어났다"고 본다. 워커가
몇 개로 겹쳐 같은 틱을 동시에 처리해도, 두 번째 이후의 UPDATE 는 WHERE 절이 더 이상
매치하지 않아 rowcount 0으로 끝나므로 정확히 한 번만 통과한다.

`TransitionSpec` 으로 "이 모델의 이 상태는, due_field 가 지나면, 저 상태로 간다"는 규칙을
적고 `core.scans.transition_scan` 으로 스캔 등록부에 올리면 주기적으로 스캔돼 전이된다(#137).
개별 모델이 그 규칙 없이 `claim_transition` 만 직접 재사용해도 된다(예: notifications 앱의
야간 지연 발송 큐).

시각은 호출 스코프(틱 한 번, 요청 한 번)당 한 번만 `Clock.now()` 로 구하고, 그 값을
`now=` 로 넘겨써야 한다 — 스캔 대상 행마다 새로 조회하면 SELECT 가 행 수만큼 쌓인다.
`now` 를 생략하면 이 함수가 대신 `Clock.now()` 를 한 번 불러 채운다(단독 호출 편의용).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from django.db import models

from .clock import Clock


def claim_transition(
    model: type[models.Model],
    pk,
    *,
    from_state: str,
    to_state: str,
    state_field: str = "state",
    now=None,
    extra_fields: dict[str, object] | None = None,
) -> bool:
    """조건부 UPDATE 한 번을 수행한다. rowcount 가 1이면 True.

    두 번째 호출부터는 WHERE 절의 `state_field=from_state` 가 더 이상 매치하지 않으므로
    False 를 돌려준다 — 이것이 "두 번 쏴도 한 번만 통과한다"의 실체다.

    `.update()` 는 QuerySet.update() 이므로 모델의 `auto_now` 필드(예: updated_at)를
    자동으로 갱신해주지 않는다(auto_now 는 `Model.save()` 경로에서만 동작한다). 이
    메커니즘을 재사용하는 모든 모델이 그 문제를 각자 겪지 않도록, 여기서 auto_now
    필드를 찾아 주입된 시각으로 명시적으로 채운다.

    `extra_fields`는 상태 전이와 **같은** 조건부 UPDATE 문 안에서 함께 써야 하는
    추가 컬럼을 위한 것이다(예: notifications 앱이 QUEUED 재진입 시각을 상태와
    같이 찍어야, 그 값을 근거로 "선점됐는데 멈춘" 행을 나중에 재선점할 수 있다).
    별도의 `.update()` 호출로 나누면 그 사이의 예외가 상태만 바뀌고 시각은 못
    바뀐 반쪽짜리 결과를 남길 수 있다 — 하나의 UPDATE 문이므로 그 틈이 없다.
    """

    now = now if now is not None else Clock.now()

    update_fields: dict[str, object] = {state_field: to_state}
    if extra_fields:
        update_fields.update(extra_fields)
    for field in model._meta.get_fields():
        if getattr(field, "auto_now", False):
            update_fields[field.name] = now

    updated = model.objects.filter(pk=pk, **{state_field: from_state}).update(**update_fields)
    return updated == 1


@dataclass(frozen=True)
class TransitionSpec:
    model: type[models.Model]
    due_field: str
    from_state: str
    to_state: str
    state_field: str = "state"
    # 전이와 같은 조건부 UPDATE 문 안에서 함께 찍어야 하는 추가 컬럼(예: #13이 마감
    # 전이와 같은 UPDATE로 judging_ends_at을 채우는 것). 대상 행 자신과 as_of를
    # 받는다 — 값이 행마다 다를 수 있기 때문이다(#13 리뷰 지적: judging_ends_at은
    # 이 행의 deadline_at에서 파생돼야지, 스캔 배치 전체가 공유하는 as_of에서
    # 파생되면 안 된다 — 그러면 마감 시각이 서로 다른 두 Contest가 같은 틱에
    # 우연히 같이 걸렸다는 이유만으로 동일한 judging_ends_at을 받는다).
    #
    # 세 번째 인자는 스캔 실행 한 번 동안 공유되는 `ctx` dict 다(core.scans.run_scan, #78) —
    # extra_fields가 정책값처럼 행마다 다시 조회하면 안 되는 값을 memoize할 자리다. `/tick`
    # (run_all)은 모든 스캔이 같은 ctx 를 공유하므로 키는 소유 모듈을 담아야 한다 —
    # 예: `f"{__name__}:policy"`(`contests/apps.py`가 쓰는 관용구).
    extra_fields: Callable[[models.Model, datetime, dict], dict[str, object]] | None = None


# ScheduledStateDemo 스캐폴딩을 스캔 등록부에 등록한다(#137). 실제 모델은 각자의 apps.py
# ready() 에서 `register_scan(transition_scan(TransitionSpec(...), name=...))` 로 같은 일을 한다.
from .models import ScheduledStateDemo  # noqa: E402
from .scans import register_scan, transition_scan  # noqa: E402

register_scan(
    transition_scan(
        TransitionSpec(
            model=ScheduledStateDemo,
            due_field="due_at",
            from_state=ScheduledStateDemo.State.PENDING,
            to_state=ScheduledStateDemo.State.DONE,
        ),
        name="scheduled-state-demo",
        batch_size=500,
    )
)
