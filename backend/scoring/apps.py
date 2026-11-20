from django.apps import AppConfig


class ScoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scoring"
    verbose_name = "Score · AI 채점"

    def ready(self) -> None:
        # 공모전 앱이 묻는 채점 쪽 둘(#1086) — `contests.ports`
        from contests.ports import POINTS_BY_REQUIREMENT, SIZE_HELD_FILTER

        from .quality import points_by_requirement
        from .size_hold import size_held_q

        POINTS_BY_REQUIREMENT.register(points_by_requirement)
        SIZE_HELD_FILTER.register(size_held_q)

        # 어댑터 부팅 가드(check_llm_adapter_mode)는 core.apps.CoreConfig.ready()가
        # 등록한다(#274) — 검사 대상(LLMScoringAdapter)이 core.llm_scoring으로
        # 옮겨가면서 검사도 함께 옮겨갔다. `scoring.checks`는 재노출만 남아 있다.

        # 채점 스캔(#12, #139) — 등록부에 올라 beat 가 주기적으로 돌린다.
        from core.scans import register_scan

        from .quality import SUBMISSION_QUALITY_SCAN
        from .services import SIZE_HOLD_EXPIRY_SCAN, SUBMISSION_SCORING_SCAN

        register_scan(SUBMISSION_SCORING_SCAN)
        # 「크기 초과」 보류가 심사 종료까지 풀리지 않으면 자동 0%(#989 A2).
        register_scan(SIZE_HOLD_EXPIRY_SCAN)
        # 완성도 스캔(#884, ADR-0072) — Score 가 생긴 제출을 뒤따라 집는다. Score 흐름과 따로 돈다.
        register_scan(SUBMISSION_QUALITY_SCAN)
        # 에이전트 채점 실행기 계약(#1085) — 공유층(`core.agent_scoring`)이 실행 틀을 import 하지 않고 여기서 받는다.
        from core.agent_ports import AGENT_GRADER

        from . import agent_runner

        AGENT_GRADER.register(agent_runner)

        # 공모전 API 가 묻는 채점·완성도·가산 자리(#1086) — `contests.ports`
        from contests import ports

        from .quality import bonus_scores, ranked_reviews, save_bonus_score
        from .services import upload_source_over_budget

        ports.UPLOAD_SOURCE_OVER_BUDGET.register(upload_source_over_budget)
        ports.RANKED_REVIEWS.register(ranked_reviews)
        ports.BONUS_SCORES.register(bonus_scores)
        ports.SAVE_BONUS_SCORE.register(save_bonus_score)

        # 공모전 판정·저장소 스캔이 보는 채점 사실(#1102) — 아래 앱이 `score` 관계를 직접 적지 않게.
        from repositories.ports import STILL_TO_SCORE

        from . import participation

        ports.IS_SCORED.register(participation.is_scored)
        ports.NEXT_ACTION_RELATIONS.register("scoring", participation.NEXT_ACTION_RELATIONS)
        ports.OWN_SCORE_RELATIONS.register("scoring", participation.OWN_SCORE_RELATIONS)
        STILL_TO_SCORE.register(participation.still_to_score)
