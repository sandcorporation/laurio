"""시간 기반 상태 전이 메커니즘 (ADR-0003).

핵심 불변식: 전이는 항상 `UPDATE ... WHERE id=? AND state='이전상태'` 형태의 조건부
UPDATE 로만 수행하고, rowcount 가 1일 때만 "전이가 실제로 일어났다"고 본다. 워커가
몇 개로 겹쳐 같은 틱을 동시에 처리해도, 두 번째 이후의 UPDATE 는 WHERE 절이 더 이상
매치하지 않아 rowcount 0으로 끝나므로 정확히 한 번만 통과한다.

`register_transition` 으로 "이 모델의 이 상태는, due_field 가 지나면, 저 상태로
간다"는 규칙을 등록해두면 `run_due_transitions` 가 주기적으로 이를 스캔해 전이시킨다.
개별 모델이 이 레지스트리를 쓰지 않고 `claim_transition` 만 직접 재사용해도 된다
(예: notifications 앱의 야간 지연 발송 큐가 이 방식을 쓴다).
"""

from dataclasses import dataclass

from django.db import models

from .clock import Clock


def claim_transition(
    model: type[models.Model],
    pk,
    *,
    from_state: str,
    to_state: str,
    state_field: str = "state",
) -> bool:
    """조건부 UPDATE 한 번을 수행한다. rowcount 가 1이면 True.

    두 번째 호출부터는 WHERE 절의 `state_field=from_state` 가 더 이상 매치하지 않으므로
    False 를 돌려준다 — 이것이 "두 번 쏴도 한 번만 통과한다"의 실체다.
    """

    updated = model.objects.filter(pk=pk, **{state_field: from_state}).update(
        **{state_field: to_state}
    )
    return updated == 1


@dataclass(frozen=True)
class TransitionSpec:
    model: type[models.Model]
    due_field: str
    from_state: str
    to_state: str
    state_field: str = "state"


TRANSITION_REGISTRY: list[TransitionSpec] = []


def register_transition(spec: TransitionSpec) -> TransitionSpec:
    TRANSITION_REGISTRY.append(spec)
    return spec


def run_due_transitions(as_of=None) -> list[dict]:
    """등록된 모든 전이 규칙에 대해 "시각이 지난 것"을 스캔하고 조건부 UPDATE로 옮긴다.

    같은 as_of 로 두 번 불러도(=틱을 연속으로 두 번 쏴도) 각 행은 정확히 한 번만
    결과 목록에 나타난다.
    """

    as_of = as_of or Clock.now()
    results: list[dict] = []

    for spec in TRANSITION_REGISTRY:
        due_ids = list(
            spec.model.objects.filter(
                **{spec.state_field: spec.from_state, f"{spec.due_field}__lte": as_of}
            ).values_list("pk", flat=True)
        )
        for pk in due_ids:
            if claim_transition(
                spec.model,
                pk,
                from_state=spec.from_state,
                to_state=spec.to_state,
                state_field=spec.state_field,
            ):
                results.append(
                    {
                        "model": spec.model.__name__,
                        "pk": pk,
                        "from_state": spec.from_state,
                        "to_state": spec.to_state,
                    }
                )

    return results


# ScheduledStateDemo 스캐폴딩을 레지스트리에 등록한다. 실제 모델이 들어오면
# 각자의 apps.py ready() 에서 같은 방식으로 register_transition 을 호출하면 된다.
from .models import ScheduledStateDemo  # noqa: E402

register_transition(
    TransitionSpec(
        model=ScheduledStateDemo,
        due_field="due_at",
        from_state=ScheduledStateDemo.State.PENDING,
        to_state=ScheduledStateDemo.State.DONE,
    )
)
