from __future__ import annotations

from django.apps import AppConfig


class AwardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "awards"
    verbose_name = "Award · 선정"

    def ready(self) -> None:
        # 공모전 앱이 묻는 선정 질의 둘(#1086) — `contests.ports`
        from contests.ports import AWARDED_SPONSOR_USER_ID, IS_SUBMISSION_AWARDED

        from .services import is_submission_awarded, sponsor_user_id_if_awarded

        AWARDED_SPONSOR_USER_ID.register(sponsor_user_id_if_awarded)
        IS_SUBMISSION_AWARDED.register(is_submission_awarded)

        # 연결된 앱의 「선정」이 화면 API 와 같은 길을 탄다(#870, #1086) — `contests.ports`
        from contests.ports import AWARD_SUBMISSION

        def award_submission(contest, submission_id: int) -> None:
            from .api import award_contest_submission

            award_contest_submission(contest, submission_id)

        AWARD_SUBMISSION.register(award_submission)

        # 공모전 판정·운영자 무료 목록이 보는 선정 사실(#1102) — 공모전 앱이 `award` 관계를 직접 적지 않게.
        from contests import ports

        from . import participation

        ports.AWARDED_SUBMISSION_ID.register(participation.awarded_submission_id)
        ports.FREE_CONTEST_WINNER.register(participation.free_contest_winner)
        ports.NEXT_ACTION_RELATIONS.register("awards", participation.NEXT_ACTION_RELATIONS)
        ports.FREE_CONTEST_RELATIONS.register("awards", participation.FREE_CONTEST_RELATIONS)

        # 선정 결과 알림 복구 스캔(#19, #138) — #1086 에서 contests 에서 옮겼다(이름 그대로)
        from core.scans import register_scan

        from .notice_recovery import NOTICE_RECOVERY_SCAN

        register_scan(NOTICE_RECOVERY_SCAN)
