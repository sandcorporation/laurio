"""주기 스캔의 뼈대와 등록부 (#137, #117, ADR-0003).

Contest 는 수명의 대부분을 아무 요청 없이 보내면서 혼자 상태가 바뀌고, 그 전이 하나하나가
돈을 움직인다. 그래서 스케줄러가 주기적으로 「시각이 지난 것」을 스캔하고, 행 처리는 조건부
UPDATE 로만 한다(ADR-0003). 이 저장소에는 그런 스캔 루프가 열일곱 개 있었는데 등록부를 쓰는
것은 셋뿐이었고 나머지는 같은 뼈대 — 후보 쿼리 → `order_by("id")` → 배치 상한 → 시간 예산 →
행별 예외 격리 → 결과 행 — 를 손으로 다시 짰다. 그리고 엔드포인트 8 · Celery task 7 · beat
7 의 대응을 아무것도 강제하지 않아, lifecycle 스캔이 조용히 스케줄에서 빠진 채 배포됐다.

이 module 이 그 둘을 한 곳에 둔다:

- **뼈대**(`run_scan`): `as_of` 한 번 · 정렬된 배치 · 단조 시간 예산 · 행별 예외 격리 ·
  결과 `{scan, as_of, count, failed, rows}`. 각 스캔은 후보 쿼리와 행 하나 처리 함수만 준다 —
  **멱등성은 뼈대의 일이 아니다.** 조건부 UPDATE / 락+존재확인 / `sent_at` 플래그 / 후보 집합
  이탈은 부수효과가 달라 정당하게 다르고, `handle_row` 안에 그대로 산다.
- **등록부**(`SCAN_REGISTRY`): 스캔이 존재하는 유일한 자리. Celery beat 스케줄과 HTTP 라우트
  `/api/internal/scans/{name}` 이 여기서 **파생**되므로 「등록했는데 안 도는」 상태가 표현
  불가능하다. `/api/internal/tick` 은 등록부 전부를 등록 순서로 한 바퀴 도는 수동용 진입점이다
  (staging 운영자의 21일 시나리오 재현).

상태 전이(`core.transitions.TransitionSpec`)는 스캔의 한 종류다 — `transition_scan` 이 그것을
ScanSpec 으로 펼친다(후보 = `filter(state=from, due<=as_of)`, 행 처리 = `claim_transition`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .clock import Clock

logger = logging.getLogger(__name__)

# 뼈대의 기본값. 값은 스캔마다 override 한다 — 규율(정렬·격리·시계·상한·예산)은 override 할 수 없다.
DEFAULT_BATCH_SIZE = 50
# core/tasks.py 의 HTTP 타임아웃(30초) 안에서 끝나야 한다 — 그래서 20초.
DEFAULT_TIME_BUDGET_SECONDS = 20.0
DEFAULT_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class ScanSpec:
    """스캔 하나. 이름이 곧 URL(`/api/internal/scans/{name}`)이고 beat 항목 이름이다."""

    name: str
    # 이번 실행의 후보. QuerySet 을 돌려주면 뼈대가 `order_by("id")[:batch_size]` 를 건다;
    # 이미 정렬·제한된 QuerySet 이나 다른 iterable 을 돌려줘도 된다(그때는 그대로 쓴다).
    candidates: Callable[[Any, dict], Iterable]
    # 행 하나를 처리하고 결과 행(dict)을 돌려준다. None 이면 「이 행은 이번에 아무 일도 없었다」
    # (조건부 UPDATE 에서 졌다 등) — rows 에 넣지 않는다. 예외는 뼈대가 격리해 failed 에 넣는다.
    handle_row: Callable[[Any, Any, dict], dict | None]
    batch_size: int = DEFAULT_BATCH_SIZE
    time_budget_seconds: float = DEFAULT_TIME_BUDGET_SECONDS
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    # 후보 QuerySet 에 뼈대가 거는 정렬 — 기본 id. 예외적으로 due 시각 순이 필요한 스캔이 준다.
    order_by: tuple[str, ...] = ("id",)


SCAN_REGISTRY: dict[str, ScanSpec] = {}

# run_scan 이 이번 실행의 단조 마감시각을 ctx 에 두는 키 — 행 처리 함수가 **행 안쪽**(수신자
# 팬아웃 등)에서도 예산을 확인하고 싶을 때 `budget_exhausted(ctx)` 로 읽는다. 뼈대의 행
# 사이 확인과 같은 시계·같은 마감이다.
_CTX_DEADLINE_KEY = f"{__name__}:deadline"


def budget_exhausted(ctx: dict) -> bool:
    """이번 스캔 실행의 시간 예산이 다 됐는가 — 행 처리 함수가 팬아웃 도중 멈출지 판단할 때."""

    deadline = ctx.get(_CTX_DEADLINE_KEY)
    return deadline is not None and time.monotonic() >= deadline


def register_scan(spec: ScanSpec) -> ScanSpec:
    """등록부에 더한다. 같은 이름을 두 번 등록하면 즉시 터진다 — 두 스캔이 같은 URL·beat 항목을
    두고 조용히 하나가 이기는 일이 없어야 한다."""

    existing = SCAN_REGISTRY.get(spec.name)
    if existing is not None and existing is not spec:
        raise RuntimeError(f"스캔 이름이 겹친다: {spec.name!r}")
    SCAN_REGISTRY[spec.name] = spec
    # 등록부가 곧 스케줄이다 — 더할 때마다 beat 스케줄을 다시 파생한다.
    from config.celery import sync_beat_schedule

    sync_beat_schedule()
    return spec


def _batch(spec: ScanSpec, as_of, ctx: dict) -> list:
    candidates = spec.candidates(as_of, ctx)
    if hasattr(candidates, "order_by") and hasattr(candidates, "query"):
        # QuerySet — 정렬과 상한을 뼈대가 건다(이미 slice 된 QuerySet 은 다시 order_by 할 수
        # 없으므로 그대로 둔다).
        if not candidates.query.is_sliced:
            candidates = candidates.order_by(*spec.order_by)[: spec.batch_size]
        return list(candidates)
    return list(candidates)[: spec.batch_size]


def run_scan(name: str, *, as_of=None, ctx: dict | None = None) -> dict:
    """등록된 스캔 하나를 실행한다.

    - `as_of` 는 한 번만 구해 모든 행에 재사용한다(행마다 `Clock.now()` 를 다시 조회하지 않는다).
    - 배치 상한을 넘는 잔여분은 다음 실행이 마저 처리한다 — ADR-0003 이 「스캔 주기만큼 늦어지는
      건 무해하다」고 규정했으므로 배치를 나누는 것도 같은 허용 범위 안에 있다.
    - 시간 예산은 단조 시계로 재고, 예산이 다 되면 남은 행을 다음 실행에 넘긴다. 첫 행은 예산과
      무관하게 반드시 시도한다 — 그러지 않으면 예산이 빡빡한 환경에서 스캔이 영원히 아무것도 안 한다.
    - 행 하나의 예외는 그 행만 `failed` 에 남기고 계속한다 — `order_by("id")` 스캔에서 예외를
      감싸지 않으면 그 행이 매번 배치 맨 앞에서 다시 걸려 뒤의 정상 건들이 영원히 처리되지 못하는
      poison pill 이 된다.
    - `ctx` 는 이 실행 동안 공유되는 dict — 행마다 다시 읽으면 안 되는 값(정책 등)을 후보·행 처리
      함수가 memoize 할 자리. 뼈대는 그 내용을 모른다.
    """

    spec = SCAN_REGISTRY[name]
    as_of = as_of if as_of is not None else Clock.now()
    ctx = {} if ctx is None else ctx
    deadline = time.monotonic() + spec.time_budget_seconds
    ctx[_CTX_DEADLINE_KEY] = deadline

    rows: list[dict] = []
    failed: list[dict] = []
    for index, row in enumerate(_batch(spec, as_of, ctx)):
        if index > 0 and time.monotonic() >= deadline:
            logger.info("스캔 %s 가 시간 예산(%.1fs)을 다 써 남은 행을 다음 실행에 넘긴다.", name, spec.time_budget_seconds)
            break
        try:
            result = spec.handle_row(row, as_of, ctx)
        except Exception as exc:  # noqa: BLE001 - 한 행의 실패가 배치를 막으면 안 된다.
            logger.exception("스캔 %s: 행(pk=%s) 처리 중 예외, 다음 행으로 계속", name, getattr(row, "pk", None))
            failed.append({"pk": getattr(row, "pk", None), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if result is not None:
            rows.append(result)

    return {
        "scan": name,
        "as_of": as_of.isoformat(),
        "count": len(rows),
        "failed": failed,
        "rows": rows,
    }


def run_all(*, as_of=None) -> dict:
    """등록부 전부를 등록 순서로 한 바퀴 — 각자 자기 예산으로. 수동용(`/api/internal/tick`)이다;
    beat 는 이것을 부르지 않는다(30초 HTTP 타임아웃 안에 못 들 수 있다)."""

    as_of = as_of if as_of is not None else Clock.now()
    ctx: dict = {}
    scans = {name: run_scan(name, as_of=as_of, ctx=ctx) for name in SCAN_REGISTRY}
    rows = [dict(scan=name, **row) for name, result in scans.items() for row in result["rows"]]
    return {
        "as_of": as_of.isoformat(),
        "count": len(rows),
        "rows": rows,
        "failed": [dict(scan=name, **f) for name, result in scans.items() for f in result["failed"]],
        "scans": scans,
    }


def beat_schedule() -> dict:
    """Celery beat 스케줄 — 등록부에서 파생된다. 손으로 쓰는 항목은 없다."""

    return {
        f"scan:{name}": {
            "task": "core.run_scan",
            "schedule": spec.interval_seconds,
            "args": [name],
        }
        for name, spec in SCAN_REGISTRY.items()
    }


def transition_scan(spec, *, name: str, **overrides) -> ScanSpec:
    """`core.transitions.TransitionSpec` 을 스캔 하나로 펼친다 — 후보는 `state=from, due<=as_of`,
    행 처리는 `claim_transition`(이기면 결과 행, 지면 None)."""

    # 모듈 속성으로 부른다(이름을 클로저에 묶지 않는다) — 테스트가 `core.transitions.
    # claim_transition` 을 patch 해 poison pill 을 심을 수 있어야 한다.
    from . import transitions

    def candidates(as_of, ctx):
        return spec.model.objects.filter(
            **{spec.state_field: spec.from_state, f"{spec.due_field}__lte": as_of}
        )

    def handle_row(row, as_of, ctx):
        extra_fields = spec.extra_fields(row, as_of, ctx) if spec.extra_fields is not None else None
        won = transitions.claim_transition(
            spec.model,
            row.pk,
            from_state=spec.from_state,
            to_state=spec.to_state,
            state_field=spec.state_field,
            now=as_of,
            extra_fields=extra_fields,
        )
        if not won:
            return None
        return {
            "model": spec.model.__name__,
            "pk": row.pk,
            "from_state": spec.from_state,
            "to_state": spec.to_state,
        }

    return ScanSpec(name=name, candidates=candidates, handle_row=handle_row, **overrides)
