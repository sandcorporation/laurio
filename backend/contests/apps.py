from django.apps import AppConfig

from core.adapters import BOOT_CHECK_TAG


class ContestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contests"
    verbose_name = "Contest · 공모전"

    def ready(self) -> None:
        """마감 전이·심사기간 종료 전이를 core.scans 등록부에 스캔으로 등록한다
        (#11/#13, ADR-0003).

        아래 두 규칙의 from_state/to_state/due_field 는 `contests.transitions` 가
        선언한 전이 그래프에서 파생된다(#255) — 그 모듈이 이 두 자리를 포함한 Contest
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

        (예전에 셋째 규칙이 있었다 —
        과제 개설 API가 걷혀(#361) 이 상태에 새로 들어올 길이 없으므로 스캔으로
        등록해 두면 영원히 빈 후보만 돈다. 간선 선언 자체는 `contests.transitions`
        에 남아 있다.)
        """

        from django.core.checks import register

        from . import checks

        # 「공모전 문제」가 건너오는 공유층 카탈로그(#547, ADR-0054) — 강의실은 이 앱을
        # 임포트하지 못하므로 공모전 쪽이 구현을 등록한다.
        from core.contest_catalog import contest_entry_requested, register_contest_catalog

        from .classroom_catalog import ContestClassroomCatalog
        from .classroom_entries import on_contest_entry_requested

        register_contest_catalog(ContestClassroomCatalog())
        # 「공모전에도 내기」(#549) — 강의실이 보낸 내기를 받아 결과 신호로 답한다.
        contest_entry_requested.connect(
            on_contest_entry_requested, dispatch_uid="contests-classroom-entry"
        )

        # LLM_REQUIREMENT_CHAT_ADAPTER_MODE 부팅 가드(#83) — 전이 등록과는 별개
        # 관심사지만, 이 앱의 ready()가 이미 지연 임포트 원칙(모델을 여기서
        # 불러오는 이유)을 지키고 있으므로 같은 자리에 등록한다.
        register(checks.check_llm_requirement_chat_adapter_mode, BOOT_CHECK_TAG)
        # SEARCH_ADAPTER_MODE 부팅 가드(#451) — 같은 자리, 같은 이유.
        register(checks.check_search_adapter_mode, BOOT_CHECK_TAG)

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

        # Contest 수명주기 통지 스캔 다섯(#19, #138) — 예전엔 `notifications` 앱에
        # 있었다(#465): 공유층이 공모전 하나만 아는 코드를 들고 있던 자리라 여기로
        # 옮겼다. 이름·주기·동작은 그대로다 — beat·tick·단건 호출이 보는 이름이
        # 바뀌지 않는다.
        from .lifecycle_notifications import LIFECYCLE_SCANS

        for lifecycle_spec in LIFECYCLE_SCANS:
            register_scan(lifecycle_spec)

        # ContestImage 최적화 — 썸네일·본문용 webp 파생본 (#235, ADR-0031/0032).
        from .image_optimization import CONTEST_IMAGE_OPTIMIZATION_SCAN

        register_scan(CONTEST_IMAGE_OPTIMIZATION_SCAN)

        # 시연 영상 파일 보존 기간 만료 스캔(#262, ADR-0035) — 공모전 전용이라
        # 여기서 등록한다(#270, ADR-0039가 submissions 앱을 공유층으로 옮기며
        # 함께 옮겼다).
        from .submission_retention import DEMO_VIDEO_RETENTION_PURGE_SCAN

        register_scan(DEMO_VIDEO_RETENTION_PURGE_SCAN)

        # 조회수 옮기기 — 바뀐 공모전만 Redis에서 DB로 (#446, spec #444).
        from .view_flush import CONTEST_VIEW_FLUSH_SCAN

        register_scan(CONTEST_VIEW_FLUSH_SCAN)

        # 공모전 검색 전체 재색인 스캔(#450, 부모 #444 스펙) — 단건 색인은
        # 아래 신호 수신자가 저장·변경마다 큐에 넣지만, 이 스캔이 매일 전체를
        # 다시 맞추는 안전망이다.
        from .search_scan import CONTEST_SEARCH_REINDEX_SCAN

        register_scan(CONTEST_SEARCH_REINDEX_SCAN)

        # 공모전 검색 색인 맞추기(#450) — Contest 저장·요구형태 변경·개최자
        # 표시 이름 변경마다 그 공모전(들)을 다시 색인 큐에 넣는다
        # (`contests/indexing.py` 모듈 docstring 참고).
        from django.db.models.signals import m2m_changed, post_save

        from . import indexing
        from .models import Contest

        post_save.connect(
            indexing.contest_saved, sender=Contest, dispatch_uid="contests.indexing.contest_saved"
        )
        m2m_changed.connect(
            indexing.contest_deliverable_types_changed,
            sender=Contest.deliverable_types.through,
            dispatch_uid="contests.indexing.deliverable_types_changed",
        )

        from accounts.models import SponsorProfile

        post_save.connect(
            indexing.sponsor_display_name_saved,
            sender=SponsorProfile,
            dispatch_uid="contests.indexing.sponsor_display_name_saved",
        )
