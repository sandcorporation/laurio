from django.apps import AppConfig


class DistributionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "distributions"
    verbose_name = "Distribution · 무응답 1/N 배분"

    def ready(self) -> None:
        # 배분 생성·몫 지급 스캔 둘(#16, #140) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .services import DISTRIBUTION_SCANS

        for spec in DISTRIBUTION_SCANS:
            register_scan(spec)

        # 이의 화면이 묻는 「배분을 막고 있나」(#1086) — `appeals.ports`
        from appeals.ports import DISTRIBUTION_HOLD

        from .services import is_holding_distribution

        DISTRIBUTION_HOLD.register(is_holding_distribution)

        # 공모전 배분 대기 조건이 보는 「배분 없음」(#1102) — 공모전 앱이 `distribution` 관계를 직접 적지 않게.
        from contests.ports import NO_DISTRIBUTION_FILTER

        from .participation import no_distribution_q

        NO_DISTRIBUTION_FILTER.register(no_distribution_q)

        # 배분 결과 알림 복구 스캔(#19, #138) — #1086 에서 contests 에서 옮겼다(이름 그대로)
        from .notice_recovery import NOTICE_RECOVERY_SCAN

        register_scan(NOTICE_RECOVERY_SCAN)
