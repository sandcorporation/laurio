from __future__ import annotations

from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class PayoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payouts"
    verbose_name = "Payout · 지급 실행"

    def ready(self) -> None:
        # 공모전 앱이 묻는 지급 쪽 둘(#1086) — `contests.ports`
        from contests.ports import PAYOUT_ACTION, SPONSORED_CONTEST_QUERYSET

        from .participation import payout_action
        from .sponsor_contests import sponsored_contest_queryset

        PAYOUT_ACTION.register(payout_action)
        SPONSORED_CONTEST_QUERYSET.register(sponsored_contest_queryset)
        # 지급 단계(`payout_action`)가 보는 인수 행을 「다음 행동」 목록이 함께 당긴다(#1102)
        from contests.ports import NEXT_ACTION_RELATIONS

        from .participation import NEXT_ACTION_RELATIONS as PAYOUT_RELATIONS

        NEXT_ACTION_RELATIONS.register("payouts", PAYOUT_RELATIONS)

        from django.core.checks import register

        from . import checks

        register(checks.check_payout_adapter_mode, BOOT_CHECK_TAG)
        register(checks.check_seller_adapter_mode, BOOT_CHECK_TAG)

        # 「지급이 당신을 기다린다」 스캔(#169) — 등록부에 올라 틱 한 바퀴에 함께 돈다.
        from core.scans import register_scan

        from .notifications import PAYOUT_NOTIFICATION_SCANS
        from .recovery import SELLER_REGISTRATION_RECOVERY_SCANS

        for spec in PAYOUT_NOTIFICATION_SCANS:
            register_scan(spec)

        # 접수되지 않은 Seller 등록의 자력 회복 스캔(#178).
        for spec in SELLER_REGISTRATION_RECOVERY_SCANS:
            register_scan(spec)

        # 배분 몫 지급(#1086 — distributions 에서 옮겼다). distributions 가 INSTALLED_APPS 에서 앞이라
        # `distribution-create` 다음에 등록된다 — 수동 tick(`run_all`)이 생성 → 지급 순서를 지킨다.
        from .distribution_payouts import DISTRIBUTION_PAYOUT_SCANS

        for spec in DISTRIBUTION_PAYOUT_SCANS:
            register_scan(spec)

        # 탈퇴 판정 중 지급 몫(#1086) — 공유층 `accounts.withdrawal` 이 지급을 import 하지 않게.
        from accounts.ports import DEVELOPER_PAYOUT_IN_PROGRESS, DEVELOPER_TRANSACTION_BASIS

        from .withdrawal import developer_has_payout_in_progress, developer_transaction_basis

        DEVELOPER_PAYOUT_IN_PROGRESS.register(developer_has_payout_in_progress)
        DEVELOPER_TRANSACTION_BASIS.register(developer_transaction_basis)
