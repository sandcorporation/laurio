"""시간 기반 상태 전이 메커니즘 (ADR-0003).

핵심 불변식: 전이는 항상 `UPDATE ... WHERE id=? AND state='이전상태'` 형태의 조건부
UPDATE 로만 수행하고, rowcount 가 1일 때만 "전이가 실제로 일어났다"고 본다. 워커가
몇 개로 겹쳐 같은 틱을 동시에 처리해도, 두 번째 이후의 UPDATE 는 WHERE 절이 더 이상
매치하지 않아 rowcount 0으로 끝나므로 정확히 한 번만 통과한다.

`register_transition` 으로 "이 모델의 이 상태는, due_field 가 지나면, 저 상태로
간다"는 규칙을 등록해두면 `run_due_transitions` 가 주기적으로 이를 스캔해 전이시킨다.
개별 모델이 이 레지스트리를 쓰지 않고 `claim_transition` 만 직접 재사용해도 된다
(예: notifications 앱의 야간 지연 발송 큐가 이 방식을 쓴다).

시각은 호출 스코프(틱 한 번, 요청 한 번)당 한 번만 `Clock.now()` 로 구하고, 그 값을
`now=` 로 넘겨써야 한다 — 스캔 대상 행마다 새로 조회하면 SELECT 가 행 수만큼 쌓인다.
`now` 를 생략하면 이 함수가 대신 `Clock.now()` 를 한 번 불러 채운다(단독 호출 편의용).
"""

from dataclasses import dataclass

from django.db import models

from .clock import Clock

# 틱 한 번에 스캔·전이시키는 최대 행 수. 인덱스가 있어도 무제한 스캔은 백로그가 쌓였을
# 때 틱 요청 자체를 타임아웃(core/tasks.py 의 30초)으로 몰아넣는다. 배치를 넘는 잔여
# 분량은 다음 틱이 마저 처리한다 — ADR-0003 이 이미 "스캔 주기만큼 늦어지는 건 무해하다"
# 고 규정했으므로, 배치를 나누는 것도 같은 허용 범위 안에 있다.
DEFAULT_BATCH_SIZE = 500


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


TRANSITION_REGISTRY: list[TransitionSpec] = []


def register_transition(spec: TransitionSpec) -> TransitionSpec:
    TRANSITION_REGISTRY.append(spec)
    return spec


def run_due_transitions(as_of=None) -> list[dict]:
    """등록된 모든 전이 규칙에 대해 "시각이 지난 것"을 스캔하고 조건부 UPDATE로 옮긴다.

    같은 as_of 로 두 번 불러도(=틱을 연속으로 두 번 쏴도) 각 행은 정확히 한 번만
    결과 목록에 나타난다. `as_of` 는 이 호출 전체에서 한 번만 구해 모든 행에 재사용한다
    (Clock.now() 를 행마다 다시 조회하지 않는다).
    """

    as_of = as_of or Clock.now()
    results: list[dict] = []

    for spec in TRANSITION_REGISTRY:
        due_ids = list(
            spec.model.objects.filter(
                **{spec.state_field: spec.from_state, f"{spec.due_field}__lte": as_of}
            ).values_list("pk", flat=True)[:DEFAULT_BATCH_SIZE]
        )
        for pk in due_ids:
            if claim_transition(
                spec.model,
                pk,
                from_state=spec.from_state,
                to_state=spec.to_state,
                state_field=spec.state_field,
                now=as_of,
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
