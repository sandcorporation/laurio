from django.apps import AppConfig


class ContestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contests"
    verbose_name = "Contest · 공모전"

    def ready(self) -> None:
        """마감 전이·심사기간 종료 전이를 core.scans 등록부에 스캔으로 등록한다
        (#11/#13, ADR-0003).

        아래 세 규칙의 from_state/to_state/due_field 는 `contests.transitions` 가
        선언한 전이 그래프에서 파생된다(#255) — 그 모듈이 이 세 자리를 포함한 Contest
        상태 전이 전체가 사는 한 곳이다.

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
        3. ASSIGNMENT_OPEN -> ASSIGNMENT_CLOSED(#207, ADR-0028) — deadline_at 이
           지나면 옮긴다. extra_fields 가 없다 — Assignment 에는 심사기간·Award·
           Distribution 이 전혀 없으므로 judging_ends_at 을 채울 이유가 없다(계속
           null 로 남는다). 채점 스캔(Contest.Status.SCOREABLE)이 이 상태를 집어
           Score 를 남기는 것으로 수명이 끝난다 — CLOSED 로 가는 공모전 전이와
           같은 뼈대를 쓰지만 다음 단계로 이어지는 전이가 없다는 점이 다르다.
        """

        from django.core.checks import register

        from . import checks

        # LLM_REQUIREMENT_CHAT_ADAPTER_MODE 부팅 가드(#83) — 전이 등록과는 별개
        # 관심사지만, 이 앱의 ready()가 이미 지연 임포트 원칙(모델을 여기서
        # 불러오는 이유)을 지키고 있으므로 같은 자리에 등록한다.
        register(checks.check_llm_requirement_chat_adapter_mode)

        from datetime import timedelta

        from core.scans import register_scan, transition_scan
        from policies.scope import current_policy

        from .transitions import contest_transition_spec

        def _judging_period_days() -> int:
            # 스캔 실행당 한 번 읽는다(#78, ADR-0023) — 정책 스코프는 뼈대가 연다(#145).
            return current_policy().judging_period_days

        # 세 TransitionSpec 은 이제 `contests.transitions` 의 선언에서 파생된다(#255) —
        # from_state/to_state/due_field 를 여기서 다시 적지 않는다. 그 선언이 이 그래프가
        # 사는 한 곳이다.
        register_scan(
            transition_scan(
                contest_transition_spec(
                    "contest-close",
                    extra_fields=lambda contest, now, ctx: {
                        "judging_ends_at": contest.deadline_at
                        + timedelta(days=_judging_period_days())
                    },
                ),
                name="contest-close",
                batch_size=500,
            )
        )

        register_scan(
            transition_scan(
                contest_transition_spec("contest-judging-end"),
                name="contest-judging-end",
                batch_size=500,
            )
        )

        # "assignment-close" 스캔은 여기서 등록하지 않는다(#361) — 과제 라우터
        # (`contests.assignment_api`)가 걷혀 DRAFT -> ASSIGNMENT_OPEN 으로 옮길
        # 방법 자체가 없다. 그 스캔을 그대로 등록해 두면 영원히 빈 후보만 도는
        # 스캔이 하나 남는다(#358 user story 11). 간선 선언(`contests.transitions`
        # 의 "assignment-close")은 지우지 않는다 — `Contest.Status.ASSIGNMENT_OPEN`
        # /`ASSIGNMENT_CLOSED`가 아직 모델에 남아 있어(다음 티켓의 몫) 그래프
        # 자체는 그대로 self-consistent해야 한다. 자세한 사정은
        # `contests.transitions`의 `SCAN_EDGES_INTENTIONALLY_UNREGISTERED` 독스트링.

        # ContestImage 최적화 — 썸네일·본문용 webp 파생본 (#235, ADR-0031/0032).
        from .image_optimization import CONTEST_IMAGE_OPTIMIZATION_SCAN

        register_scan(CONTEST_IMAGE_OPTIMIZATION_SCAN)

        # 시연 영상 파일 보존 기간 만료 스캔(#262, ADR-0035) — 공모전 전용이라
        # 여기서 등록한다(#270, ADR-0039가 submissions 앱을 공유층으로 옮기며
        # 함께 옮겼다).
        from .submission_retention import DEMO_VIDEO_RETENTION_PURGE_SCAN

        register_scan(DEMO_VIDEO_RETENTION_PURGE_SCAN)
