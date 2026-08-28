from django.apps import AppConfig


class ContestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contests"
    verbose_name = "Contest · 공모전"

    def ready(self) -> None:
        """마감 전이·심사기간 종료 전이를 core.transitions 레지스트리에 등록한다
        (#11/#13, ADR-0003).

        core.transitions.run_due_transitions 가 스케줄러 틱마다 이 규칙들을 스캔한다.
        `claim_transition` 이 이미 `WHERE id=? AND status='<이전상태>'` 형태의 단일
        UPDATE 문으로 rowcount==1 일 때만 통과시키므로, 틱을 두 번 쏴도 각 전이는
        정확히 한 번만 일어난다.

        1. PUBLISHED -> CLOSED — deadline_at 이 지나면 옮긴다. 같은 조건부 UPDATE
           안에서 judging_ends_at(=마감 + JUDGING_PERIOD_DAYS)도 함께 채운다(#13) —
           심사기간은 여기서 시작된다.
        2. CLOSED -> JUDGING_ENDED — judging_ends_at 이 지나도록 아무도 Award하지
           않은 Contest 를 옮긴다(#13). Award된 Contest 는 이미 AWARDED 상태라 이
           규칙의 from_state(CLOSED) 조건에 애초에 걸리지 않는다 — Award가 이
           스케줄러 전이보다 먼저 일어나도, 늦게 일어나도 서로를 밟지 않는다.
        """

        from datetime import timedelta

        from django.conf import settings

        from core.transitions import TransitionSpec, register_transition

        from .models import Contest

        register_transition(
            TransitionSpec(
                model=Contest,
                due_field="deadline_at",
                from_state=Contest.Status.PUBLISHED,
                to_state=Contest.Status.CLOSED,
                state_field="status",
                extra_fields=lambda now: {
                    "judging_ends_at": now + timedelta(days=settings.JUDGING_PERIOD_DAYS)
                },
            )
        )

        register_transition(
            TransitionSpec(
                model=Contest,
                due_field="judging_ends_at",
                from_state=Contest.Status.CLOSED,
                to_state=Contest.Status.JUDGING_ENDED,
                state_field="status",
            )
        )
