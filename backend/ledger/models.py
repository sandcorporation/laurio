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


class AppendOnlyQuerySet(models.QuerySet):
    """`Model.objects.filter(...).update(...)`/`.delete()` 대량 조작을 막는다.

    인스턴스의 `save()`/`delete()`만 막아서는 부족하다 — `JournalEntry.objects.filter(pk=1)
    .update(memo="...")`나 `LedgerLine.objects.filter(...).delete()`는 인스턴스 메서드를
    타지 않고 QuerySet이 직접 UPDATE/DELETE를 날린다. 원장은 append-only이므로 이 경로도
    막아야 한다.
    """

    def update(self, **kwargs):
        raise AppendOnlyError(
            f"{self.model.__name__}은(는) append-only라 대량 수정(QuerySet.update)을 "
            "허용하지 않는다. 정정은 반대 분개를 새로 추가하는 방식으로만 한다."
        )

    def delete(self):
        raise AppendOnlyError(
            f"{self.model.__name__}은(는) append-only라 대량 삭제(QuerySet.delete)를 "
            "허용하지 않는다."
        )


class AppendOnlyManager(models.Manager.from_queryset(AppendOnlyQuerySet)):
    pass


class AppendOnlyModel(models.Model):
    """한 번 저장되면 다시 저장(수정)하거나 지울 수 없는 모델.

    DB 레벨 트리거 대신 애플리케이션 레벨에서 막는다 — 이 프로젝트 규모에서는 충분하고,
    운영자용 조작 경로(Django admin)도 별도로 change/delete 권한을 끈다
    (`ledger.admin`). 인스턴스 단위(`save`/`delete`)와 QuerySet 단위(`update`/`delete`)
    양쪽을 모두 막아야 우회 경로가 남지 않는다.
    """

    objects = AppendOnlyManager()

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


def hard_delete_e2e_fixture_rows(queryset: "models.QuerySet") -> tuple[int, dict]:
    """append-only 가드를 우회해 실제로 지운다 — e2e 시드 자신의 픽스처 정리 전용(#240).

    `AppendOnlyQuerySet.delete()`는 실데이터(Score·JournalEntry·LedgerLine)를 보호하려고
    있다. 그런데 `seed_e2e_contests`·`seed_e2e_operator_queues`는 이름 접두어로 격리한
    **자기 자신이 만든** 판정 스냅샷(Score)을 매 재시드마다 지우고 새로 만든다 — 그
    재현성이 이 시드들의 존재 이유다(네임스페이스 격리, #104/#66). Django의 캐스케이드
    collector가 매니저를 거치지 않고 우회하던 것(#240이 막은 그 구멍)과 이 함수는 다르다
    — 이건 **명시적으로, 이 한 곳에서만** 같은 우회를 허락한다.

    **프로덕션 코드는 절대 이 함수를 부르지 않는다.** 호출부가 `management/commands/
    seed_*` 밖이면 그 자체가 리뷰에서 걸려야 한다. `models.QuerySet.delete`를 언바운드로
    직접 호출해 `AppendOnlyQuerySet.delete`의 오버라이드를 건너뛴다.
    """
    return models.QuerySet.delete(queryset)


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
    # OneToOneField — 한 원본은 정확히 한 번만 반대 분개로 정정될 수 있다(NULL은 여러 개
    # 허용되므로 일반 분개끼리는 서로 막지 않는다). ForeignKey(unique=True)는 Django가
    # 바로 이 용도로는 OneToOneField를 쓰라고 경고한다(W342) — CI가 `manage.py check
    # --fail-level WARNING`으로 돌기 때문에 실제로 그렇게 써야 한다.
    reverses = models.OneToOneField(
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
