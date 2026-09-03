"""벤더가 확정하는 돈의 의도(Charge, CONTEXT.md)에 공통인 원시 연산 (#125, #118).

Prize 결제·심사 연장비·Payout 확정·환불·Distribution 몫 지급은 전부 같은 뼈대를
탄다 — 벤더를 부르고, 타임아웃이면 조회로 확정하고, 조건부 UPDATE 로 딱 한 번
이기고, 이겼을 때만 원장에 분개를 남긴다. 그 뼈대의 세 조각을 여기 한 번만 둔다.

- `Outcome` — 벤더 결과의 세 값. PGAdapter 는 문자열을, PayoutAdapter 는
  `TransferOutcome` 을 돌려주므로 호출부가 `Outcome.parse(...)` 한 줄로 번역한다.
  adapter 는 건드리지 않는다(#120 이 adapter 를 고칠 때 이 번역이 사라진다).
- `reconcile_after_timeout` — 타임아웃 뒤의 재확인 호출 **자체가 또 실패할 수
  있다**(#87 코드리뷰 지적 3·4). 그 실패는 "실패했다"가 아니라 "아직 모른다"이므로
  종결시키지 않고 미확정을 돌려준다. 결제 확인·연장비·환불은 이 규율을 각자
  손으로 갖고 있었고, Payout 확정과 Distribution 몫 지급은 **없었다**(두 번째
  타임아웃이 500/스캔 예외로 샜다) — 이 함수의 첫 사용처가 그 둘이다.
- `claim_and_post` — `UPDATE … WHERE status=<이전>` 으로 이긴 호출(rowcount==1)만
  같은 트랜잭션에서 분개를 남기고 `journal_entry_id` 를 되쓴다(ADR-0003·ADR-0004).
  웹훅이 confirm 보다 먼저 와도, 같은 웹훅이 두 번 와도 분개는 한 번이다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

import uuid

from django.db import models, transaction
from django.db.models import QuerySet

from ledger.services import LineInput, post_journal_entry

from .adapters import PGTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Outcome(str, Enum):
    """벤더가 이 의도에 대해 말한 것 — 됐다, 안 됐다, 아직 모른다."""

    PAID = "paid"
    FAILED = "failed"
    PENDING = "pending"

    @classmethod
    def parse(cls, status: str) -> "Outcome":
        """adapter 가 돌려준 문자열("paid" | "failed" | "pending")을 번역한다.

        `TransferOutcome` 은 `.status` 를 넘긴다. 모르는 문자열은 조용히 pending 으로
        뭉개지 않고 예외다 — adapter 계약 위반은 여기서 드러나야 한다.
        """

        try:
            return cls(status)
        except ValueError as exc:
            raise ValueError(f"알 수 없는 벤더 결과 문자열: {status!r}") from exc


def reconcile_after_timeout(query: Callable[[], T], *, on_unknown: T, context: str) -> T:
    """타임아웃 뒤 실제 결과를 조회로 확정하되, 그 조회가 또 실패하면 `on_unknown`.

    `query` 는 순수 조회(adapter.query_status 등)다. 어떤 예외가 나든 — 두 번째
    타임아웃이든, 벤더의 5xx 든, 우리 쪽 파싱 오류든 — "아직 모른다"로 남기고
    로그로 드러낸다. 여기서 실패로 단정하면 실제로는 성공한 이체를 FAILED 로
    적어 돈이 두 번 나가거나 영영 안 나가는 경로가 된다. 웹훅이나 다음 재시도가
    마저 확정한다.
    """

    try:
        return query()
    except Exception as exc:  # noqa: BLE001 - 재확인조차 실패하면 미확정으로 남겨둔다.
        logger.error(
            "%s — 재확인(query)이 실패했다. 실패로 단정하지 않고 미확정으로 남긴다: %s",
            context,
            exc,
        )
        return on_unknown


def claim_and_post(
    queryset: QuerySet,
    *,
    filters: dict[str, Any],
    from_status: str,
    to_status: str,
    status_field: str = "status",
    journal: Callable[[Any], tuple[UUID, str, list[LineInput]]] | None = None,
    journal_field: str = "journal_entry_id",
    on_claimed: Callable[[Any], None] | None = None,
) -> tuple[Any, bool]:
    """`filters` 로 고른 행 하나를 `from_status → to_status` 로 딱 한 번 옮긴다.

    이긴 호출(rowcount==1)만, 같은 트랜잭션 안에서 `journal(row)` 이 만든 분개를
    원장에 남기고 `journal_field` 에 되쓴 뒤 `on_claimed(row)` 를 부른다(부모
    Contest 를 공개하는 것 같은, 이 확정에 딸린 두 번째 조건부 UPDATE 의 자리).
    지면(이미 다른 채널이 확정했거나 재전송이다) 행을 그대로 돌려주고 아무것도
    하지 않는다 — 원장에는 이미 반영되어 있다.

    돌려주는 것은 `(row, claimed)` 다. `queryset` 에 `select_related` 를 걸어
    넘기면 `journal`·`on_claimed` 가 그 관계를 추가 조회 없이 쓴다.
    """

    with transaction.atomic():
        updated = queryset.model.objects.filter(**filters, **{status_field: from_status}).update(
            **{status_field: to_status}
        )
        row = queryset.get(**filters)

        if updated != 1:
            return row, False

        if journal is not None:
            contest_id, memo, lines = journal(row)
            entry = post_journal_entry(contest_id=contest_id, memo=memo, lines=lines)
            queryset.model.objects.filter(pk=row.pk).update(**{journal_field: entry.id})
            setattr(row, journal_field, entry.id)

        if on_claimed is not None:
            on_claimed(row)

    return row, True


class ChargeBase(models.Model):
    """Charge 한 건의 공통 뼈대 — Prize 결제(`payments.Payment`)와 심사 연장비
    (`contests.JudgingExtensionPayment`)가 상속한다 (#126, #118).

    테이블도 필드 이름도 그대로다(마이그레이션 없음). 자식이 주는 것은 이 Charge 종류에
    고유한 둘뿐이다 — `journal()`(이겼을 때 남길 분개의 줄)과 `on_paid()`(확정에 딸려오는
    부모 전이: Contest 공개, 심사기간 연장). 나머지 — 벤더 호출, 타임아웃 재확인, 조건부
    UPDATE, 분개 게시 — 는 `settle_charge`/`apply_vendor_outcome` 가 한 번만 한다.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "요청됨"
        PAID = "paid", "결제완료"
        FAILED = "failed", "결제실패"

    # PG에 전달하는 주문 참조값.
    order_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    # 이 Charge 가 원장에 남긴 분개. 성공 시 정확히 한 번만 채워진다 — 감사용이고, 실제
    # 중복 방지는 status 의 조건부 UPDATE 가 담당한다.
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    @property
    def charged_amount(self) -> int:
        """벤더에 확인을 요청할 때 넘기는 금액(원)."""

        raise NotImplementedError

    def journal(self) -> tuple[UUID, str, list[LineInput]]:
        """(원장 contest_id, memo, 분개 줄) — 이겼을 때만 불린다."""

        raise NotImplementedError

    def on_paid(self) -> None:
        """확정에 딸려오는 부모 전이. 분개와 같은 트랜잭션 안에서, 이겼을 때만 불린다."""


def apply_vendor_outcome(charge_qs: QuerySet, *, order_id, outcome: Outcome):
    """벤더가 말한 결과를 Charge 에 딱 한 번 적용한다 — confirm 응답이든 웹훅이든 재확인이든
    같은 함수로 들어오므로 「순서 무관」이 여기 한 곳에 있다. PENDING 은 아무것도 하지
    않는다 — 함부로 실패 처리하면 나중에 PG 가 성공으로 정산해도 다시 확인되지 않는다.
    """

    if outcome is Outcome.PAID:
        charge, _claimed = claim_and_post(
            charge_qs,
            filters={"order_id": order_id},
            from_status=ChargeBase.Status.REQUESTED,
            to_status=ChargeBase.Status.PAID,
            journal=lambda c: c.journal(),
            on_claimed=lambda c: c.on_paid(),
        )
        return charge
    if outcome is Outcome.FAILED:
        # 실패 경로는 원장에도 부모에도 아무 흔적을 남기지 않는다 — 돈이 움직이지 않았다.
        charge, _claimed = claim_and_post(
            charge_qs,
            filters={"order_id": order_id},
            from_status=ChargeBase.Status.REQUESTED,
            to_status=ChargeBase.Status.FAILED,
        )
        return charge
    return charge_qs.get(order_id=order_id)


def settle_charge(
    charge_qs: QuerySet,
    *,
    order_id,
    adapter,
    simulate: str | None = None,
    payment_key: str | None = None,
):
    """Charge 하나를 벤더에 동기 확인하고 결과를 적용한다.

    **어떤 `transaction.atomic()` 도 열지 않은 채 벤더를 부른다** — 잠금을 쥔 채 외부
    네트워크를 기다리지 않는다. 타임아웃이면 `query_status` 로 확정하고, 그 재확인마저
    실패하면 미확정으로 남긴다(`reconcile_after_timeout`). 벤더의 명시적 거절(`PGError`)은
    그대로 올린다 — 이 Charge 의 문제가 아니라 이 배포의 설정 문제일 수 있어 종결시키면
    안 되고, 호출자가 502 로 바꾼다.

    이미 REQUESTED 가 아니면(다른 채널이 먼저 확정했거나 재전송) 벤더를 부르지 않고 현재
    상태를 돌려준다.
    """

    charge = charge_qs.get(order_id=order_id)
    if charge.status != ChargeBase.Status.REQUESTED:
        return charge

    try:
        raw = adapter.confirm(
            order_id=str(order_id),
            simulate=simulate,
            payment_key=payment_key,
            amount=charge.charged_amount,
        )
    except PGTimeoutError:
        raw = reconcile_after_timeout(
            lambda: adapter.query_status(order_id=str(order_id)),
            on_unknown=Outcome.PENDING.value,
            context=f"결제 확인 재확인(order_id={order_id})",
        )

    return apply_vendor_outcome(charge_qs, order_id=order_id, outcome=Outcome.parse(raw))
