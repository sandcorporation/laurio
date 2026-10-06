from __future__ import annotations

from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class ClassroomConfig(AppConfig):
    name = "classroom"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # 강의실 채점 스캔(#287) — 등록부에 올라 beat가 주기적으로 돌린다.
        # `scoring.apps.ScoringConfig.ready()`와 같은 패턴이다.
        from django.core.checks import register

        from core.scans import register_scan

        from . import checks
        from .scoring import CLASSROOM_SUBMISSION_SCORING_SCAN

        register_scan(CLASSROOM_SUBMISSION_SCORING_SCAN)
        # 공모전 문제(#548, ADR-0054) — 공개 중인 무료 공모전의 원본이 바뀌면 그 공모전을
        # 들여온 문제가 따라간다. 신호는 공유층에 있어 공모전 앱을 임포트하지 않는다.
        from core.contest_catalog import contest_source_changed

        from .contest_problems import on_contest_source_changed

        contest_source_changed.connect(
            on_contest_source_changed, dispatch_uid="classroom.contest_problems.source_changed"
        )
        # 「공모전에도 내기」(#549) — 공모전 쪽의 결과를 그 시도에 남긴다.
        from core.contest_catalog import contest_entry_resolved

        from .contest_entries import on_contest_entry_resolved

        contest_entry_resolved.connect(
            on_contest_entry_resolved, dispatch_uid="classroom.contest_entries.resolved"
        )
        # 연결된 앱(ADR-0052, #512) — 90일 동안 쓰지 않은 허락을 끊고, 아무도 허락하지
        # 않은 등록을 걷는다. 탈퇴·휴면이면 그 자리에서 끊는다(`accounts.signals`).
        from accounts.signals import user_became_dormant, user_withdrawn

        from .connected_app_signals import revoke_on_dormancy, revoke_on_withdrawal
        from .oauth import CONNECTED_APP_EXPIRY_SCAN, UNUSED_CLIENT_SCAN

        register_scan(CONNECTED_APP_EXPIRY_SCAN)
        register_scan(UNUSED_CLIENT_SCAN)
        user_withdrawn.connect(revoke_on_withdrawal, dispatch_uid="classroom-connected-app-withdrawal")
        user_became_dormant.connect(revoke_on_dormancy, dispatch_uid="classroom-connected-app-dormancy")
        # 공동 강사(#563) — 탈퇴하면 공동 강사인 클래스에서 떠나기와 같은 정리로 빠진다.
        from .co_instructors import leave_all_on_withdrawal

        user_withdrawn.connect(leave_all_on_withdrawal, dispatch_uid="classroom-co-instructor-withdrawal")
        # 어댑터 모드 부팅 가드(#340, ADR-0043) — `core.apps.CoreConfig.ready()`와
        # 같은 이유로 여기서 등록한다(django.setup() 이후에만 평가돼야 한다).
        register(checks.check_classroom_scoring_adapter_mode, BOOT_CHECK_TAG)
