"""복식부기 원장 (ADR-0004).

모든 금전 이동은 `JournalEntry`(분개) 하나와 그에 딸린 `LedgerLine`(전표 라인) 여럿으로
기록된다. 차변(전체 debit) 합과 대변(전체 credit) 합이 같아야만 분개가 성립하며, 그 검증은
`ledger.services.post_journal_entry`에서 트랜잭션으로 수행한다(모델 레이어는 스스로를
검증하지 않는다 — 검증 실패 시 아예 아무 것도 저장되지 않아야 하기 때문).

원장은 append-only다: 기존 분개·라인은 절대 수정·삭제할 수 없다. 정정이 필요하면 반대
분개(`reverses`)를 새로 추가한다. 원본은 그대로 남는다.
"""

from __future__ import annotations

from django.db import models


class AppendOnlyError(Exception):
    """append-only 모델에 대한 수정·삭제 시도."""


class AppendOnlyModel(models.Model):
    """한 번 저장되면 다시 저장(수정)하거나 지울 수 없는 모델.

    DB 레벨 트리거 대신 애플리케이션 레벨에서 막는다 — 이 프로젝트 규모에서는 충분하고,
    운영자용 조작 경로(Django admin)도 별도로 change/delete 권한을 끈다
    (`ledger.admin`).
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError(
                f"{type(self).__name__}은(는) append-only라 기존 행을 수정할 수 없다. "
                "정정은 반대 분개를 새로 추가하는 방식으로만 한다."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError(
            f"{type(self).__name__}은(는) append-only라 삭제할 수 없다."
        )


class Account(models.TextChoices):
    """계정과목 (ADR-0004).

    원천징수 예수금은 국세청에 낼 남의 돈이므로 반드시 별도 계정으로 분리한다(ADR-0008).
    """

    SPONSOR_DEPOSIT = "sponsor_deposit", "발주자 예치금"
    DEVELOPER_PAYABLE = "developer_payable", "개발자 미지급금"
    PLATFORM_FEE_REVENUE = "platform_fee_revenue", "플랫폼 수수료 수익"
    WITHHOLDING_TAX_PAYABLE = "withholding_tax_payable", "원천징수 예수금"
    PG_FEE_EXPENSE = "pg_fee_expense", "PG 수수료 비용"


class EntrySide(models.TextChoices):
    DEBIT = "debit", "차변"
    CREDIT = "credit", "대변"


class JournalEntry(AppendOnlyModel):
    """분개 한 건.

    `contest_id`는 아직 존재하지 않는 `Contest` 모델(#8)을 가리키는 불투명 식별자다.
    FK가 아니라 UUID 값으로만 들고 있고, #8이 실제 관계를 붙인다.
    """

    contest_id = models.UUIDField(db_index=True)
    memo = models.CharField(max_length=255, blank=True, default="")
    reverses = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="reversed_by",
        on_delete=models.PROTECT,
        help_text="이 분개가 정정하는 원본 분개. 원본은 수정되지 않고 그대로 남는다.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - admin 표시용
        return f"JournalEntry({self.pk}, contest={self.contest_id})"


class LedgerLine(AppendOnlyModel):
    """분개 한 건을 이루는 전표 라인. 계정과목 하나 + 차/대변 + 금액."""

    entry = models.ForeignKey(JournalEntry, related_name="lines", on_delete=models.PROTECT)
    account = models.CharField(max_length=32, choices=Account.choices)
    side = models.CharField(max_length=8, choices=EntrySide.choices)
    # 원 단위 정수만 다룬다(ADR-0004) — float·Decimal 소수부 없음.
    amount = models.PositiveBigIntegerField()

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover - admin 표시용
        return f"{self.get_side_display()} {self.get_account_display()} {self.amount}"
