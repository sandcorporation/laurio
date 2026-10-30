"""1분 집계 행(#827). 원시 호출 행은 쌓지 않는다 — 한 분·한 라벨 묶음이 한 행이다.

**라벨은 `core.llm_metrics` 그대로다**(닫힌 집합, 사용자·클래스 id 없음). 히스토그램은 그 모듈의 경계와
같은 버킷별 수를 **누적이 아닌 칸별 수**로 든다 — 길이는 경계 수 + 1(마지막 칸이 +Inf). 분위수는
`ops_metrics.quantile` 이 prometheus `histogram_quantile` 과 같은 선형 보간으로 계산한다.
"""

from __future__ import annotations

from django.db import models


class LlmMinute(models.Model):
    """한 분 동안의 LLM 채점 호출 — 제품 · 모델 · 결과마다 한 행."""

    #: 그 분의 시작 시각(UTC).
    minute = models.DateTimeField()
    product = models.CharField(max_length=16)
    model = models.CharField(max_length=64)
    result = models.CharField(max_length=24)
    calls = models.BigIntegerField(default=0)
    #: `llm_metrics.DURATION_BOUNDS` 칸별 수(+Inf 칸 포함).
    duration_buckets = models.JSONField(default=list)
    duration_sum_ms = models.BigIntegerField(default=0)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["minute", "product", "model", "result"], name="ops_llm_minute_labels_unique"),
        ]


class LlmQueueMinute(models.Model):
    """한 분 동안의 강의실 채점 큐 대기와 동시 채점 최댓값 — 제품마다 한 행(지금은 강의실뿐이다)."""

    minute = models.DateTimeField()
    product = models.CharField(max_length=16)
    waits = models.BigIntegerField(default=0)
    #: `llm_metrics.QUEUE_WAIT_BOUNDS` 칸별 수(+Inf 칸 포함).
    wait_buckets = models.JSONField(default=list)
    wait_sum_ms = models.BigIntegerField(default=0)
    #: 그 분에 본 동시 채점(벤더를 기다리는 호출) 수의 최댓값.
    in_flight_max = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["minute", "product"], name="ops_llm_queue_minute_unique"),
        ]


class RequestMinute(models.Model):
    """한 분 동안의 백엔드 HTTP 요청(#828) — 메서드 · URL 패턴 · 상태코드마다 한 행. `/metrics` 는 세지 않는다."""

    minute = models.DateTimeField()
    method = models.CharField(max_length=8)
    #: `resolver_match.route`(패턴, 실제 경로가 아니다) — 맞는 것이 없으면 `unmatched`.
    route = models.CharField(max_length=200)
    status = models.PositiveSmallIntegerField()
    requests = models.BigIntegerField(default=0)
    #: `core.metrics.DURATION_BOUNDS` 칸별 수(+Inf 칸 포함).
    duration_buckets = models.JSONField(default=list)
    duration_sum_ms = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["minute", "method", "route", "status"], name="ops_request_minute_labels_unique"),
        ]


class AlertState(models.Model):
    """운영 경보 규칙 하나의 지금 상태(#830) — 규칙마다 한 행이고 검사가 그 자리에서 고친다(이력은 두지 않는다).

    `streak` 은 조건이 연속으로 참이었던 검사 수다 — 규칙의 「지속」(예 5분)은 이것이 그 횟수에 닿을 때다.
    `pending_notice` 는 아직 디스코드에 닿지 못한 알림(`firing`/`resolved`, 없으면 빈 칸) — 다음 검사가 다시 보낸다.
    """

    class Status(models.TextChoices):
        FIRING = "firing"
        RESOLVED = "resolved"

    rule = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RESOLVED)
    streak = models.PositiveIntegerField(default=0)
    #: 마지막으로 울리기 시작한 시각 — 한 번도 울리지 않았으면 null.
    started_at = models.DateTimeField(null=True)
    last_checked_at = models.DateTimeField(null=True)
    #: 마지막으로 해소된 시각 — 울리는 중이면 null.
    resolved_at = models.DateTimeField(null=True)
    #: 마지막 검사의 값과 기준 — 화면·메시지에 그대로 쓰는 문자열(단위 포함).
    value = models.CharField(max_length=100, blank=True, default="")
    threshold = models.CharField(max_length=100, blank=True, default="")
    pending_notice = models.CharField(max_length=16, blank=True, default="")
