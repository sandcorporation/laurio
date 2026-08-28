from django.apps import AppConfig


class ContestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contests"
    verbose_name = "Contest · 공모전"

    def ready(self) -> None:
        """마감 전이를 core.transitions 레지스트리에 등록한다 (#11, ADR-0003).

        core.transitions.run_due_transitions 가 스케줄러 틱마다 이 규칙을 스캔해
        deadline_at 이 지난 PUBLISHED Contest 를 조건부 UPDATE 로 CLOSED 로 옮긴다.
        `claim_transition` 이 이미 `WHERE id=? AND status='published'` 형태의 단일
        UPDATE 문으로 rowcount==1 일 때만 통과시키므로, 틱을 두 번 쏴도 전이는
        정확히 한 번만 일어난다.
        """

        from core.transitions import TransitionSpec, register_transition

        from .models import Contest

        register_transition(
            TransitionSpec(
                model=Contest,
                due_field="deadline_at",
                from_state=Contest.Status.PUBLISHED,
                to_state=Contest.Status.CLOSED,
                state_field="status",
            )
        )
