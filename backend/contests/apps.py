from django.apps import AppConfig


class ContestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contests"
    verbose_name = "Contest · 공모전"

    def ready(self) -> None:
        """마감 전이·심사기간 종료 전이를 core.scans 등록부에 스캔으로 등록한다
        (#11/#13, ADR-0003).

        core.scans 등록부에 스캔으로 올라 beat 가 주기적으로, /tick 이 한 바퀴에 스캔한다(#137).
        `claim_transition` 이 이미 `WHERE id=? AND status='<이전상태>'` 형태의 단일
        UPDATE 문으로 rowcount==1 일 때만 통과시키므로, 틱을 두 번 쏴도 각 전이는
        정확히 한 번만 일어난다.

        1. PUBLISHED -> CLOSED — deadline_at 이 지나면 옮긴다. 같은 조건부 UPDATE
           안에서 judging_ends_at(=이 Contest 자신의 deadline_at +
           PlatformPolicy.judging_period_days, #78/ADR-0023)도 함께 채운다(#13)
           — 심사기간은 여기서 시작된다. **반드시 이 행의 deadline_at에서
           파생시킨다** — 스캔 시각(as_of)에서 파생시키면 스캔 주기만큼
           심사기간이 매번 조금씩 늘어나고(ADR-0003이 허용한 "전이가 늦어지는
           것"과 "심사기간 자체가 늘어나는 것"은 다른 문제다), 마감 시각이 서로 다른
           두 Contest가 같은 틱에 우연히 같이 CLOSED로 넘어가면 둘 다 동일한
           judging_ends_at을 받는 사고가 난다(#13 리뷰 지적).
        2. CLOSED -> JUDGING_ENDED — judging_ends_at 이 지나도록 아무도 Award하지
           않은 Contest 를 옮긴다(#13). Award된 Contest 는 이미 AWARDED 상태라 이
           규칙의 from_state(CLOSED) 조건에 애초에 걸리지 않는다 — Award가 이
           스케줄러 전이보다 먼저 일어나도, 늦게 일어나도 서로를 밟지 않는다.
        """

        from django.core.checks import register

        from . import checks

        # LLM_REQUIREMENT_CHAT_ADAPTER_MODE 부팅 가드(#83) — 전이 등록과는 별개
        # 관심사지만, 이 앱의 ready()가 이미 지연 임포트 원칙(모델을 여기서
        # 불러오는 이유)을 지키고 있으므로 같은 자리에 등록한다.
        register(checks.check_llm_requirement_chat_adapter_mode)

        from datetime import timedelta

        from core.scans import register_scan, transition_scan
        from core.transitions import TransitionSpec

        from .models import Contest

        # ctx는 /tick 한 바퀴 동안 모든 스캔이 공유하는 dict다
        # (core.scans.run_all) — 키가 네임스페이스 없이
        # "policy"처럼 뻔하면, 나중에 다른 전이가 같은 memoization 관용구를
        # 복사해 같은 키를 쓰는 순간 등록 순서에 따라 서로의 값을 덮어쓰거나
        # 읽는다(코드리뷰 지적 3 — AttributeError로 스캔이 죽거나, 우연히
        # 같은 속성이 있으면 잘못된 값이 조용히 저장된다). 이 모듈 소유임을
        # 값 자체에 담아 충돌을 구조적으로 막는다.
        _CTX_POLICY_KEY = f"{__name__}:policy"

        def _judging_period_days(ctx: dict) -> int:
            # 이 스캔 실행 한 번 동안 정책을 한 번만 읽는다(#78, ADR-0023) —
            # extra_fields는 CLOSED로 넘어가는 Contest 행마다 호출되므로, 여기서
            # 매번 get_current_policy()를 부르면 쿼리가 행 수만큼 늘어난다.
            # ctx는 core.scans 가 실행 하나에 대해 만들어주는 빈 dict라
            # 이 memoization이 스캔 경계를 정확히 지킨다.
            if _CTX_POLICY_KEY not in ctx:
                from policies.services import get_current_policy

                ctx[_CTX_POLICY_KEY] = get_current_policy()
            return ctx[_CTX_POLICY_KEY].judging_period_days

        register_scan(
            transition_scan(
                TransitionSpec(
                    model=Contest,
                    due_field="deadline_at",
                    from_state=Contest.Status.PUBLISHED,
                    to_state=Contest.Status.CLOSED,
                    state_field="status",
                    extra_fields=lambda contest, now, ctx: {
                        "judging_ends_at": contest.deadline_at
                        + timedelta(days=_judging_period_days(ctx))
                    },
                ),
                name="contest-close",
                batch_size=500,
            )
        )

        register_scan(
            transition_scan(
                TransitionSpec(
                    model=Contest,
                    due_field="judging_ends_at",
                    from_state=Contest.Status.CLOSED,
                    to_state=Contest.Status.JUDGING_ENDED,
                    state_field="status",
                ),
                name="contest-judging-end",
                batch_size=500,
            )
        )
