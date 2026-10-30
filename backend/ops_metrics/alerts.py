"""운영 경보(#830) — celery beat 가 1분마다 규칙을 검사하고, 울릴 때와 해소될 때 디스코드로 한 번씩 보낸다.

oracle prometheus `alerts.yml` 에 있던 codemit 규칙을 옮겼다(사이트 다운·호스트 자원·컨테이너 재시작은 밖의
감시가 맡는다).

**입력 = DB 집계 행 + 아직 옮겨지지 않은 Redis 분 해시.** 「N분」 창은 **지금 분(쓰는 중)과 그 앞의 N−1 개
닫힌 분**이다. 지금 분을 넣는 이유: `> 0` 규칙(쿼터·인증)이 첫 거부가 난 그 분에 울려야 하고(flush 를 기다리면
1분 늦다), prometheus 의 `increase(x[10m])` 도 「지금」에서 끝나는 창이었다. N−1 개만 더하는 이유: 지금 분이
부분이라 창이 N분을 넘지 않게 — 10분 전에 끝난 일이 한 번 더 울리지 않는다. 창 안의 분마다 DB 행과 Redis
해시를 **둘 다** 더한다: flush 가 아직 못 옮긴 닫힌 분, 그리고 이미 옮긴 분에 늦게 닿은 기록(다음 flush 가 같은
행에 더할 몫)이 Redis 에 있다. flush 의 `take` 가 원자적이라 같은 값을 두 곳에서 세는 일은 없다 — 옮기는 그
찰나(읽어 지운 뒤 DB 에 쓰기 전)에는 오히려 덜 센다(다음 검사에 돌아온다). Redis 를 읽지 못하면 DB 만 본다.

**지속** = 조건이 연속으로 참인 검사 수(`AlertState.streak`). 거짓이 한 번 끼면 0 으로 돌아간다.

**보내기.** 울리기 시작할 때 「발생」, 해소될 때 「해소」를 한 번 보낸다 — 이미 울리는 규칙은 다시 보내지
않는다. 보내지 못하면 경고 로그를 남기고 `pending_notice` 에 들고 있다가 다음 검사가 다시 보낸다. 「발생」이
닿기 전에 해소되면 둘 다 버린다(받은 적 없는 경보의 해소를 알릴 까닭이 없다). 웹훅 설정이 비면 보내지 않고
상태만 기록한다. 겹쳐 돈 검사는 트랜잭션 advisory 잠금을 못 잡으면 건너뛴다 — 같은 알림을 두 번 보내지 않는다.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Callable

import requests
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum

from core.llm_metrics import QUEUE_WAIT_BOUNDS

from . import recorder
from .flush import _buckets, _grouped
from .models import AlertState, LlmMinute, LlmQueueMinute
from .quantile import add_counts, histogram_quantile
from .recorder import LLM, LLM_QUEUE, minute_key, minute_of
from .store import get_store

logger = logging.getLogger("codemit.ops_metrics")

#: 겹친 검사를 막는 advisory 잠금 번호(아무 값이나 고정 — 다른 곳과 겹치지 않으면 된다).
_LOCK_ID = 830_000_001
#: 가장 긴 창(LLMAuthRejected 30분).
_LONGEST_MINUTES = 30
#: 큐 대기를 보는 제품.
_QUEUE_PRODUCT = "classroom"


@dataclass
class Inputs:
    """한 번의 검사가 보는 값 — 분(epoch 초)마다 결과별 호출 수와 큐 대기 칸, 그리고 grader 의 마지막 신호."""

    now: float
    current: int
    calls: dict[int, Counter] = field(default_factory=dict)
    queue: dict[int, list[int]] = field(default_factory=dict)
    grader_beat: int | None = None

    def _minutes(self, length: int) -> range:
        return range(self.current - (length - 1) * 60, self.current + 1, 60)

    def results(self, length: int) -> Counter:
        total: Counter = Counter()
        for minute in self._minutes(length):
            total.update(self.calls.get(minute, Counter()))
        return total

    def queue_buckets(self, length: int) -> list[int]:
        counts: list[int] = []
        for minute in self._minutes(length):
            counts = add_counts(counts, self.queue.get(minute, []))
        return counts


@dataclass(frozen=True)
class Reading:
    firing: bool
    value: str
    threshold: str


@dataclass(frozen=True)
class Rule:
    name: str
    #: 울리려면 조건이 연속으로 참이어야 하는 검사 수(1분마다 한 번).
    for_checks: int
    read: Callable[[Inputs], Reading]


def _count_rule(result: str, minutes: int, *, at_least: int) -> Callable[[Inputs], Reading]:
    sign = "> 0" if at_least == 1 else f"≥ {at_least}"

    def read(inputs: Inputs) -> Reading:
        n = inputs.results(minutes)[result]
        return Reading(n >= at_least, f"{n}회", f"{sign}회 / {minutes}분")

    return read


def _timeout_ratio(inputs: Inputs) -> Reading:
    calls = inputs.results(15)
    total = sum(calls.values())
    timeouts = calls["timeout"]
    ratio = timeouts / total if total else 0.0
    return Reading(total > 0 and ratio > 0.2, f"{ratio:.0%} ({timeouts}/{total})", "> 20% / 15분, 5분 지속")


def _queue_slow(inputs: Inputs) -> Reading:
    p95 = histogram_quantile(0.95, QUEUE_WAIT_BOUNDS, inputs.queue_buckets(10))
    value = "대기 없음" if p95 is None else f"p95 {p95:.0f}초"
    return Reading(p95 is not None and p95 > 300, value, "p95 > 300초 / 10분, 10분 지속")


def _grader_down(inputs: Inputs) -> Reading:
    if inputs.grader_beat is None:
        return Reading(True, "신호 없음", "3분 넘게 신호 없음")
    age = max(0, int(inputs.now) - inputs.grader_beat)
    return Reading(age > 180, f"마지막 신호 {age}초 전", "3분 넘게 신호 없음")


RULES: tuple[Rule, ...] = (
    Rule("LLMTimeoutRatioHigh", 5, _timeout_ratio),
    Rule("LLMQuotaExhausted", 1, _count_rule("quota_exhausted", 10, at_least=1)),
    Rule("LLMRateLimited", 1, _count_rule("rate_limited", 10, at_least=5)),
    Rule("LLMAuthRejected", 1, _count_rule("auth", 30, at_least=1)),
    Rule("ClassroomScoringQueueSlow", 10, _queue_slow),
    Rule("GraderDown", 1, _grader_down),
)


# --- 입력 모으기 ----------------------------------------------------------------------------


def gather(now: float) -> Inputs:
    current = minute_of(now)
    first = current - (_LONGEST_MINUTES - 1) * 60
    inputs = Inputs(now=now, current=current)
    since = datetime.fromtimestamp(first, tz=dt_timezone.utc)

    rows = LlmMinute.objects.filter(minute__gte=since).values("minute", "result").annotate(n=Sum("calls")).order_by()
    for row in rows:
        inputs.calls.setdefault(int(row["minute"].timestamp()), Counter())[row["result"]] += row["n"]
    for row in LlmQueueMinute.objects.filter(minute__gte=since, product=_QUEUE_PRODUCT).only("minute", "wait_buckets"):
        minute = int(row.minute.timestamp())
        inputs.queue[minute] = add_counts(inputs.queue.get(minute, []), list(row.wait_buckets))

    try:
        _add_unflushed(inputs, first)
    except Exception as exc:  # noqa: BLE001 - Redis 가 멈춰도 DB 몫으로 검사는 돈다
        logger.warning("운영 경보: Redis 의 아직 옮기지 않은 분을 읽지 못해 DB 만 본다: %s", type(exc).__name__)
    inputs.grader_beat = recorder.last_beat("grader")
    return inputs


def _add_unflushed(inputs: Inputs, first: int) -> None:
    store = get_store()
    size = len(QUEUE_WAIT_BOUNDS) + 1
    for minute in range(first, inputs.current + 1, 60):
        for (_product, _model, result), metrics in _grouped(store.read(minute_key(LLM, minute)), 3).items():
            if metrics.get("n"):
                inputs.calls.setdefault(minute, Counter())[result] += metrics["n"]
    for minute in range(inputs.current - 9 * 60, inputs.current + 1, 60):
        groups = _grouped(store.read(minute_key(LLM_QUEUE, minute)), 1)
        metrics = groups.get((_QUEUE_PRODUCT,))
        if metrics:
            inputs.queue[minute] = add_counts(inputs.queue.get(minute, []), _buckets(metrics, size))


# --- 디스코드 --------------------------------------------------------------------------------


def post_webhook(url: str, content: str) -> None:
    """디스코드 웹훅으로 한 줄을 보낸다 — 2xx 가 아니면 던진다. 시험이 이 함수를 갈아끼운다."""

    response = requests.post(url, json={"content": content}, timeout=settings.OPS_ALERT_DISCORD_TIMEOUT_SECONDS)
    response.raise_for_status()


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "1분 미만"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes}분"
    return f"{hours}시간 {minutes}분" if minutes else f"{hours}시간"


def message(state: AlertState, kind: str) -> str:
    if kind == AlertState.Status.FIRING:
        parts = [state.value, f"기준 {state.threshold}"]
        origin = settings.OPERATOR_WEB_ORIGIN.rstrip("/")
        if origin:
            parts.append(f"{origin}/ops")
        return f"🔥 [Codemit] {state.rule} 발생 — " + " · ".join(parts)
    lasted = (state.resolved_at - state.started_at).total_seconds() if state.resolved_at and state.started_at else 0
    return f"✅ [Codemit] {state.rule} 해소 — {_duration(lasted)} 지속"


def _deliver(state: AlertState) -> None:
    url = settings.OPS_ALERT_DISCORD_WEBHOOK_URL
    if not state.pending_notice:
        return
    if not url:
        state.pending_notice = ""
        return
    try:
        post_webhook(url, message(state, state.pending_notice))
    except Exception as exc:  # noqa: BLE001 - 다음 검사가 다시 보낸다
        # 주소가 예외 문장에 섞일 수 있어 종류만 남긴다.
        logger.warning("운영 경보 %s 의 %s 알림을 보내지 못해 다음 검사에서 다시 보낸다: %s", state.rule, state.pending_notice, type(exc).__name__)
        return
    state.pending_notice = ""


# --- 검사 ------------------------------------------------------------------------------------


def _step(state: AlertState, rule: Rule, reading: Reading, at: datetime) -> None:
    state.last_checked_at = at
    if not reading.firing:
        state.streak = 0
        if state.status == AlertState.Status.FIRING:
            state.status = AlertState.Status.RESOLVED
            state.resolved_at = at
            # 「발생」이 닿기 전이면 해소도 보내지 않는다.
            state.pending_notice = "" if state.pending_notice == AlertState.Status.FIRING else AlertState.Status.RESOLVED
        return
    state.streak += 1
    state.value, state.threshold = reading.value, reading.threshold
    if state.status != AlertState.Status.FIRING and state.streak >= rule.for_checks:
        state.status = AlertState.Status.FIRING
        state.started_at = at
        state.resolved_at = None
        state.pending_notice = AlertState.Status.FIRING


def check_alerts(*, now: datetime) -> dict[str, str] | None:
    """규칙을 한 번 검사하고 규칙 → 상태를 돌려준다. 다른 검사가 돌고 있으면 None."""

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [_LOCK_ID])
            if not cursor.fetchone()[0]:
                return None
        inputs = gather(now.timestamp())
        AlertState.objects.bulk_create([AlertState(rule=rule.name) for rule in RULES], ignore_conflicts=True)
        states = {state.rule: state for state in AlertState.objects.filter(rule__in=[r.name for r in RULES])}
        for rule in RULES:
            state = states[rule.name]
            _step(state, rule, rule.read(inputs), now)
            _deliver(state)
            state.save()
        return {name: str(state.status) for name, state in states.items()}


def firing() -> list[AlertState]:
    """지금 울리는 경보 — 오래 울린 것부터(운영자 API)."""

    names = [rule.name for rule in RULES]
    return list(AlertState.objects.filter(status=AlertState.Status.FIRING, rule__in=names).order_by("started_at", "rule"))
