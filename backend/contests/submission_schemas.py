"""공모전 제출물(`ContestSubmission`) 전용 스키마 (#270, ADR-0039).

자료·근거·자가 응답의 공유 모양(`SubmissionAssetOut`·`EvidenceOut` 등)은
`submissions.schemas`에 남아 있다 — 여기 있는 것은 `contest_id`·`developer_id`
가 실리는, 공모전에서만 뜻이 있는 응답이다.
"""

from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import Field

from submissions.schemas import (
    AssetSummaryOut,
    CompletionOut,
    EvidenceOut,
    RequirementResponseIn,
    RequirementResponseOut,
    SubmissionAssetIn,
    SubmissionAssetOut,
)
from submissions.scoring_basis import ScoringBasis

from .submission_participation import NextAction


class ErrorOut(Schema):
    """django-ninja 의 `HttpError` 가 내는 모양 — 4xx 를 생성 타입에 드러낸다."""

    detail: str


class SubmissionIn(Schema):
    assets: list[SubmissionAssetIn] = []
    requirement_responses: list[RequirementResponseIn] = []
    # 무료 공모전 전용(#416, ADR-0048) — 「수상작의 소스는 개최자가 볼 수
    # 있습니다」에 동의했는가. 유료 공모전 제출에는 아무 뜻이 없다(백엔드가
    # 무시한다) — 본인확인이 그 자리를 대신하기 때문이다.
    source_access_consent: bool = False


class SubmissionOut(Schema):
    id: int
    contest_id: int
    developer_id: int
    is_owner: bool
    # 뷰어가 볼 수 없는 종류는 **목록에서 뺀다**(#190). 예전에는 종류마다 필드가
    # 하나씩이라 null로 "존재하지만 안 보임"을 표현할 수 있었지만, 목록에서는
    # 그 구분이 애초에 성립하지 않는다 — 없는 자료와 안 보이는 자료를 구별해 세면
    # 그 수 자체가 감춘 것을 드러낸다.
    assets: list[SubmissionAssetOut]
    requirement_responses: list[RequirementResponseOut]
    completion: CompletionOut
    created_at: datetime
    updated_at: datetime
    # 지금 무엇을 해야/기다려야 하는가 (#247). `MyParticipationOut.next_action`과
    # **같은 함수**(`contests.submission_participation.next_action_for`)에서
    # 나온다 — 판정기를 두 벌로 쓰면 언젠가 갈라지고, 그때 제출 화면은 「내 참가
    # 현황」과 다른 말을 한다. 자기 제출물일 때만 값이 실린다 — `is_owner`가
    # False면 항상 null이다(남의 제출을 볼 수 있는 Sponsor·마감 후 공개 열람
    # 경로에는 노출하지 않는다).
    next_action: NextAction | None = None
    # 무료 공모전 소스 열람 동의 시각(#416) — 유료 공모전이면 항상 null이다.
    source_access_consent_at: datetime | None = None


class MyParticipationOut(Schema):
    """「내 참가 현황」의 한 행 (#74).

    도메인 상태를 그대로 늘어놓지 않는다 — `next_action` 하나가 "지금 무엇을
    해야 하는가" 에 먼저 답하고, 나머지는 그 행을 알아보기 위한 최소한이다.
    상세는 각자의 화면이 보여준다.
    """

    submission_id: int
    contest_id: int
    contest_title: str
    prize: int
    deadline_at: datetime
    # **`str` 이 아니라 enum 이어야 한다.** 이 값을 enum 으로 두기로 한 유일한
    # 근거가 "값이 하나 늘면 생성된 타입에도 늘고 `tsc --noEmit` 이 프론트의
    # 누락된 분기를 빌드타임에 잡는다" 인데, `str` 로 두면 타입체커가 볼 것이
    # 없어 그 근거가 통째로 사라진다(실제로 처음에 `str` 로 썼다가 생성된
    # 타입이 `next_action: string` 으로 나오는 것을 보고 고쳤다).
    next_action: NextAction
    submitted_at: datetime
    # 무료 공모전인가(#417, ADR-0048) — 화면이 이의제기·지급 링크를 감추는
    # 근거다. 이의제기·지급은 무료 공모전에 절차 자체가 없다.
    is_free: bool = False

    @staticmethod
    def resolve_submission_id(obj) -> int:
        return obj.id

    @staticmethod
    def resolve_contest_title(obj) -> str:
        return obj.contest.title

    @staticmethod
    def resolve_prize(obj) -> int:
        return obj.contest.prize

    @staticmethod
    def resolve_is_free(obj) -> bool:
        return obj.contest.is_free

    @staticmethod
    def resolve_deadline_at(obj):
        return obj.contest.deadline_at

    @staticmethod
    def resolve_submitted_at(obj):
        return obj.created_at

    @staticmethod
    def resolve_next_action(obj) -> str:
        from .submission_participation import next_action_for

        return next_action_for(obj)


class MyParticipationPageOut(Schema):
    """「내 참가 현황」 한 페이지 (#152) — 운영자 지급 큐의 `OperatorPayoutPageOut`
    (payouts/schemas.py, #151)과 같은 모양이다.

    `count` 는 **전체** 건수다(이 페이지의 길이가 아니다). `next` 는 「마지막으로
    본 행 다음부터」를 가리키는 커서이고, 더 없으면 null 이다 — 「더 있는가」를
    받은 수와 전체 건수의 비교가 아니라 **다음 커서의 유무**로 판정한다(#150 이
    적은 증상 중 하나다).
    """

    items: list[MyParticipationOut]
    count: int
    next: str | None


class PublicSubmissionOut(Schema):
    """Developer 공개 프로필 아카이브 한 항목 (#11, ADR-0014).

    마감된 Contest의 데모·영상만 담는다 — 소스·저장소·test_account는 이 스키마
    자체에 없다("존재하지만 안 보임"이 아니라 애초에 필드가 없다). ADR-0014의
    "마감 후" 칸에 있는 건 데모·영상뿐이다.
    """

    submission_id: int
    contest_id: int
    contest_title: str
    # `demo_video`·`demo_url` 자료만 담긴다(#190) — `source`·`repository`는
    # 이 목록에 절대 들어오지 않고, 원소 타입에 `test_account`가 없다.
    assets: list[AssetSummaryOut]
    created_at: datetime


class DeveloperPublicProfileOut(Schema):
    developer_id: int
    display_name: str
    bio: str
    submissions: list[PublicSubmissionOut]


# --- Sponsor 비교 화면 (#13) --------------------------------------------------
#
# Sponsor가 앱을 전부 설치해보지 않고도 Requirement 체크리스트를 축으로
# Submission들을 1차로 거를 수 있게 한다(User Story 45). 소스는 이 스키마 어디에도
# 없다 — Award 전까지 Sponsor에게 열리지 않는다(ADR-0014).


class ComparisonEntryOut(Schema):
    submission_id: int
    developer_id: int
    developer_display_name: str
    is_met: bool
    note: str
    evidence: list[EvidenceOut]
    is_linked: bool


class RequirementComparisonOut(Schema):
    requirement_id: int
    text: str
    grade: str
    #: 배점 1~10 — 완성도에만 쓴다(#904). 마감 뒤에도 `PATCH …/requirements/{id}/points` 로 고친다.
    points: int
    entries: list[ComparisonEntryOut]


class QualityItemOut(Schema):
    """완성도 항목 한 줄(#884, ADR-0072) — Requirement 하나의 0~5 와 근거. 라벨은 매긴 때의 스냅샷이다."""

    item_id: int
    label: str
    required: bool
    score: int
    reasoning: str
    #: 지금 배점(1~10)과 항목 점수(0~5 ÷ 5 × 배점) — #904, ADR-0073.
    points: int
    item_points: float
    #: 가산 항목(#905) — AI 가 아니라 개최자가 마감 뒤 매긴다. `reasoning` 자리에 개최자의 한 줄 메모가 온다.
    bonus: bool = False
    #: 가산을 아직 매기지 않았으면 거짓(0점). AI 항목은 늘 참.
    rated: bool = True


class BonusScoreOut(Schema):
    """제출 하나 × 가산 Requirement 하나의 개최자 점수(#905) — 매기지 않았으면 `rated=False`·0점."""

    requirement_id: int
    score: int
    memo: str
    rated: bool


class BonusScoreIn(Schema):
    """개최자가 매기는 가산 점수 — 0~5 정수와 한 줄 메모(선택). 같은 칸에 다시 보내면 덮어쓴다."""

    score: int = Field(ge=0, le=5)
    memo: str = Field(default="", max_length=200)


class SubmissionQualityOut(Schema):
    """제출 하나의 완성도(#884·#904). 상금·Score 와 무관한 AI 의 참고 의견이고 이의 대상이 아니다.
    화면은 「`total` / `max_total`점」(소수 첫째 자리), 등수는 `raw_total`(정수 Σ 0~5 × 배점)로 매긴다 —
    읽을 때 지금 배점으로 계산한다(ADR-0073). `completeness`·`weighted_score`·`max_weighted_score` 는 옛 화면
    호환 칸이다."""

    total: float
    max_total: int
    raw_total: int
    completeness: float
    weighted_score: int
    max_weighted_score: int
    items: list[QualityItemOut]


class ComparisonQualityOut(SubmissionQualityOut):
    """개최자 비교 화면 몫 — 완성도가 매겨진 제출들 사이의 「완성도 순위」(같은 가중 점수는 같은 등수)."""

    rank: int


class ComparisonSubmissionOut(Schema):
    submission_id: int
    developer_id: int
    developer_display_name: str
    # 데모·영상 자료만 담긴다(#190). 원소 타입에 `test_account`가 없다 — 이
    # 스키마는 다중화 이전에도 그 필드를 내지 않았고, Sponsor가 로그인 정보를
    # 보는 자리는 단건 조회(`SubmissionOut`)다.
    assets: list[AssetSummaryOut]
    completion: CompletionOut
    # 완성도(#884) — 아직 매기지 않았으면(Score 전·자동 0%·실패) null.
    quality: ComparisonQualityOut | None = None
    # 가산 Requirement 마다의 개최자 점수(#905) — 완성도 기록이 없어도 매길 수 있게 따로 싣는다.
    bonus_scores: list[BonusScoreOut] = []


class ContestComparisonOut(Schema):
    contest_id: int
    submissions: list[ComparisonSubmissionOut]
    requirements: list[RequirementComparisonOut]


class ScoredAssetOut(Schema):
    """채점에 실제로 쓰인 자산 하나 (#191, ADR-0027).

    이의를 제기하는 사람과 심판하는 사람이 "같은 것을 보고" 이야기하려면 무엇을
    근거로 채점했는지가 보여야 한다 — 소스가 여럿이 되면서 그중 무엇이 실제로
    쓰였는지가 더 이상 자명하지 않다. `commit_sha`는 `kind=repository` 자산에만
    붙고(#193), 그 전까지는 항상 null이다.
    """

    asset_id: int
    kind: str
    label: str
    commit_sha: str | None = None


class OwnScoreOut(Schema):
    """Developer 가 자기 Submission 의 채점 결과를 볼 때 받는 것 (#74).

    운영자가 심판 근거로 보는 `appeals.schemas.ScoreSnapshotOut` 과 필드가 같다 —
    이의를 제기하는 사람과 심판하는 사람이 **같은 것을 보고** 이야기해야 하기
    때문이다. 한쪽만 보는 값이 있으면 이의는 서로 다른 근거를 두고 오간다.

    **`prompt` 는 없다.** 프롬프트에는 본인 소스가 통째로 임베드되어 있어
    (`scoring._build_prompt`) 본인에게 보인다고 유출은 아니지만, 응답 크기에
    상한이 사라진다 — 이 저장소는 상한 없는 필드가 4xx 가 나야 할 자리에서 500 을
    내는 것을 이미 겪었다(#72). 소스를 다시 보는 경로는 따로 있다(ADR-0022).

    `percentage` 는 문자열이다. 배분 컷라인이 쓰는 것과 같은 십진값이라, float 로
    내리면 화면이 보여준 값과 돈을 가른 값이 갈릴 수 있다.

    **`reasoning`은 저장된 원문 그대로가 아니다(#246).** AI가 실제로 판정했으면
    `Score.reasoning`(Requirement별 근거)을 그대로 낸다. 자동 0% 둘(ADR-0030
    "채점 입력 없음"·ADR-0031 "채점 실패 상한")만 `scoring_basis`에 맞춰 직렬화
    시점에 새로 만든 문장 **하나**로 바꾼다 — 저장된 문구에는 ADR 번호와 내부
    임계값(5회, 6시간)이 그대로 박혀 있고 `Score`는 append-only라(ADR-0006) 그
    문구 자체를 고칠 방법이 없다. 운영자가 보는 `appeals.schemas.
    ScoreSnapshotOut`은 이 변환을 거치지 않고 원문을 그대로 낸다 — 이의 심판이
    ADR-0030과 ADR-0031을 정확히 구별해야 하는 감사 기록이기 때문이다. **이것은
    "같은 것을 본다"는 두 스키마의 원칙을 어기는 것이 아니다** — 어느 쪽이든
    "AI가 판정하지 않았다"와 "누가 책임인가"라는 같은 사실을 말한다. 참가자
    쪽은 그 사실을 문서 참조 없이 한 문장으로, 운영자 쪽은 감사에 필요한 원문
    그대로 Requirement별로 반복해 말한다는 표현만 다르다(#244가 알림 발송 실패
    사유에 대해 세운 것과 같은 모양 — 저장된 문자열을 소독하지 않고 청중을
    구조로 가른다, `notifications.api._recipient_facing_reason`).
    """

    percentage: str
    model_version: str
    reasoning: list[dict]
    # 채점의 성격을 기계가 읽을 수 있는 값으로 말한다(#246 AC) — 프론트가
    # `model_version` 문자열을 다시 파싱해 "AI가 판정했는가"를 추측하지 않게
    # 한다. `Score`에 저장된 것에서만 파생된다(`scoring_basis_for`) — 새
    # 컬럼도 기존 행에 대한 마이그레이션도 없다.
    scoring_basis: ScoringBasis
    created_at: datetime
    # 이의 창이 언제 닫히는지. 기한을 만들어 놓고 화면에 적지 않으면 그 기한은
    # 달력을 들고 계산한 사람에게만 유리한 함정이 된다. 심사기간이 없는 Contest
    # 면 None 이고, 그때는 창이 닫히지 않는다.
    appeal_deadline: datetime | None = None
    # 지금 낼 수 있는가. `appeals.api.create_appeal` 의 전제와 **같은 함수**에서
    # 나온다 — 조건을 두 벌로 쓰면 언젠가 갈라지고, 그때 화면은 이의를 권해놓고
    # API 가 거절한다.
    can_appeal: bool = False
    # 무료 공모전인가(#417, ADR-0048) — `can_appeal`이 false인 이유가 「기한이
    # 지났다」인지 「애초에 이의제기 절차가 없다」인지 화면이 갈라 말하는 근거다.
    is_free: bool = False
    # 채점에 실제로 쓰인 자산 목록 (#191). 소스가 여럿이 되면서 "무엇을 보고
    # 채점했는가"가 이의 창의 전제 중 하나가 됐다.
    scored_assets: list[ScoredAssetOut] = []
    # 채점 직전 저장소 도달 가능성 재확인 기록 (#219, ADR-0030) —
    # [{"asset_id", "checked_at", "is_public", "source", "detail"}, ...]. 재확인이
    # 일어나지 않은 채점(소스만으로 충분했거나 저장소가 없는 제출)에는 빈
    # 리스트다. "내 저장소는 공개였는데 왜 0%인가"라는 이의가 추측이 되지 않게
    # 한다 — `SubmissionAsset.is_public_checked_at`은 그 뒤 스캔이 계속 덮어쓰지만
    # 이 필드는 Score와 함께 불변으로 고정된다.
    repository_reachability_check: list[dict] = []
    # 본인 제출의 완성도(#884, ADR-0072) — 아직 매기지 않았으면 null. **등수는 없다** — 등수는 남의
    # 제출과 견준 값이라 제출자에게 나가지 않는다. 이의 대상이 아니다(`can_appeal` 은 Score 만 본다).
    quality: SubmissionQualityOut | None = None

    @staticmethod
    def resolve_quality(obj):
        from core.quality_review import quality_view
        from scoring.quality import bonus_scores, points_by_requirement

        review = getattr(obj.submission, "quality_review", None)
        if review is None:
            return None
        contest_id = obj.submission.contest_id
        bonus = bonus_scores(contest_id, [obj.submission.id])[obj.submission.id]
        return quality_view(review.items, points_by_requirement(contest_id), bonus)

    @staticmethod
    def resolve_scored_assets(obj) -> list[dict]:
        from submissions.scored_assets import resolve_scored_assets

        return resolve_scored_assets(obj.scored_assets)

    @staticmethod
    def resolve_appeal_deadline(obj):
        return obj.submission.contestsubmission.contest.judging_ends_at

    @staticmethod
    def resolve_can_appeal(obj) -> bool:
        from core.clock import Clock

        submission = obj.submission
        if getattr(submission, "appeal", None) is not None:
            return False
        contest = submission.contestsubmission.contest
        if contest.is_free:
            # 무료 공모전에는 이의제기 절차 자체가 없다(#417, ADR-0048) —
            # `appeals.api.create_appeal`이 같은 이유로 404를 낸다. 조건을
            # 두 벌로 쓰지 않는다.
            return False
        return contest.appeal_window_open(Clock.now())

    @staticmethod
    def resolve_is_free(obj) -> bool:
        return obj.submission.contestsubmission.contest.is_free

    @staticmethod
    def resolve_percentage(obj) -> str:
        # `Decimal` 을 그대로 두면 JSON 에서 float 가 된다 — 배분 컷라인이 쓰는
        # 것과 같은 십진값이므로 자릿수를 잃지 않게 문자열로 내린다.
        return str(obj.percentage)

    @staticmethod
    def resolve_scoring_basis(obj) -> ScoringBasis:
        from submissions.scoring_basis import scoring_basis_for

        return scoring_basis_for(obj.model_version)

    @staticmethod
    def resolve_reasoning(obj) -> list[dict]:
        from submissions.scoring_basis import participant_facing_reasoning

        return participant_facing_reasoning(
            model_version=obj.model_version, reasoning=obj.reasoning
        )


# --- Sponsor 지표 화면 (#107, 부모 #105) ---------------------------------------
#
# 「제출을 하나씩 열어보는 것뿐」이던 Sponsor 에게 자기 Contest 의 건강을
# 보여준다. **이 화면이 뒤 티켓들의 자리이기도 하다** — #107 은 일자별 누적
# 참가작 수만 세우고, 이어지는 티켓들(#108: Requirement 충족 분포·제출 채움률
# 분포, #109: 조회수·전환율)이 `ContestMetricsOut` 에 필드를 하나씩 더 얹는다.
# 그래서 지표마다 새 스키마 클래스 하나 + `ContestMetricsOut` 필드 하나가 느는
# 모양을 유지한다 — 기존 필드를 바꾸지 않는다.
#
# **Score 는 이 파일 어디에도 없다.** Sponsor 에게 점수를 감추는 것은 의도된
# 설계다(ADR-0006/0014) — 비교 화면 스키마(`ContestComparisonOut`)에 Score
# 필드가 없는 것과 같은 이유로, 집계 화면도 Score 를 조회하지 않는다.
#
# **개별 Submission 을 새로 노출하지 않는다.** developer_id·submission_id 같은
# 식별자는 아래 어느 스키마에도 없다 — 나오는 것은 항상 **수**뿐이다.


class DailyParticipationOut(Schema):
    """하루 치 참가 — 그 날짜까지의 누적 Submission 수 (#107).

    판정은 백엔드가 한다: 화면이 Submission 목록을 받아 스스로 날짜별로 묶지
    않는다. `date` 는 `YYYY-MM-DD` — Asia/Seoul 기준 하루다.
    """

    date: str
    cumulative_count: int


class RequirementFulfillmentOut(Schema):
    """Requirement 하나를 몇 명이 충족했는가 (#108).

    분모는 **이 Contest 의 전체 Submission 수**다 — 그 Requirement 에 자가
    응답을 아예 남기지 않은 Submission 도 「충족하지 못함」으로 센다. 채점이
    증거 없는 자가 응답을 미달로 보는 것(ADR-0014)과 같은 원칙이다.

    **사람이 아니라 일에 대한 정보다.** `developer_id`도 어느 Submission이
    응답했는지도 여기 없다 — 나오는 것은 이 Requirement의 충족 건수뿐이다.

    **표본이 작으면 이 집계가 익명이 아니다.** Submission 이 1~2건일 때
    "1명 중 1명이 충족" 은 그 사람의 자가 응답 그대로다. 지금은 Sponsor 가
    어차피 개별 Submission 을 볼 수 있어(`compare_submissions`) 이 지표가 새로
    드러내는 것이 없지만, **이 지표를 공개로 옮기려 할 때는 그대로 함정이
    된다** — 그때는 최소 표본 수 같은 장치가 먼저 필요하다(#108, 이 티켓은 그
    장치를 구현하지 않는다).
    """

    requirement_id: int
    text: str
    grade: str
    met_count: int
    total_submission_count: int


class CompletionDistributionOut(Schema):
    """제출 채움률 분포 — 데모·시연 영상·테스트 계정이 붙은 Submission 비율 (#108).

    `submissions.schemas.CompletionOut` 이 Submission 한 건에 대해 매기는 세
    boolean(has_demo_video·has_demo_url·has_test_account)을 Contest 전체로
    집계한 것이다. 참가작들이 실제로 확인 가능한 상태인지 가늠하는 신호일
    뿐 — 강제 항목은 아니다(소스만 필수다).
    """

    total_submission_count: int
    demo_video_count: int
    demo_url_count: int
    test_account_count: int
    # #190 — 저장소를 붙인 Submission 수. 위 셋과 같은 "하나라도 있는가"의 집계다.
    repository_count: int = 0


class ViewMetricsOut(Schema):
    """조회수와 전환율 — 「본 사람 대비 낸 사람」(#109, 부모 #105).

    `view_count`는 `Contest.view_count`(DB)다(#446) — 조회 자체는 여전히
    `contests.view_tracking`이 Redis에서 실시간으로 세지만(공개 상세는
    트래픽이 가장 많은 화면이라 조회마다 Contest 행을 갱신하면 경합이
    생긴다), 이 값은 `contests.view_flush` 옮기기 스캔이 10분마다 옮겨
    놓은 값이다 — 공개 목록·랜딩 큐레이션이 읽는 값과 같아서, 개최자가
    지표 화면과 공개 카드에서 다른 숫자를 보지 않는다. 이 스키마에도
    개별 방문자를 가리키는 필드는 없다 — Contest 전체의 조회수 하나뿐이다.

    `conversion_rate`는 `total_submission_count / view_count`다. 조회가
    0이면 0으로 나누지 않고 `None`을 낸다 — "아직 데이터가 없음"과 "전환율
    0%"은 다른 것이라, 화면이 그 둘을 구별해 그릴 수 있어야 한다.
    """

    view_count: int
    conversion_rate: float | None


class ContestMetricsOut(Schema):
    contest_id: int
    total_submission_count: int
    daily_participation: list[DailyParticipationOut]
    # #108 — 필수·선택 구별은 각 항목의 `grade` 필드가 담는다. 순서는
    # Requirement.Meta.ordering(`order`, `id`)을 그대로 따른다 — 심사 비교
    # 화면·제출 폼과 같은 순서라 Sponsor 가 다른 화면과 대조하기 쉽다.
    requirement_fulfillment: list[RequirementFulfillmentOut]
    completion_distribution: CompletionDistributionOut
    # #109 — 조회수와 전환율.
    view_metrics: ViewMetricsOut
