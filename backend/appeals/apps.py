from django.apps import AppConfig


class AppealsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "appeals"
    verbose_name = "Appeal · 이의제기"

    def ready(self) -> None:
        # 공모전 판정이 보는 이의 사실(#1102) — 공모전 앱이 `appeal` 관계를 직접 적지 않게.
        from contests import ports

        from .participation import RELATIONS, appeal_state

        ports.APPEAL_STATE.register(appeal_state)
        ports.NEXT_ACTION_RELATIONS.register("appeals", RELATIONS)
        ports.OWN_SCORE_RELATIONS.register("appeals", RELATIONS)
