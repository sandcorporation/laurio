from __future__ import annotations

from datetime import datetime

from ninja import Schema

from .participation import NextAction
from pydantic import Field


class EvidenceIn(Schema):
    kind: str
    value: str = Field(max_length=500)


class EvidenceOut(Schema):
    kind: str
    value: str


class RequirementResponseIn(Schema):
    requirement_id: int
    is_met: bool = False
    # RequirementResponse.note와 같은 길이(#10 리뷰 지적) — 스키마가 막지 않으면
    # DB CHECK(varchar(1000))이 대신 걸려 422 대신 500(DataError)이 난다.
    note: str = Field(default="", max_length=1000)
    evidence: list[EvidenceIn] = []


class RequirementResponseOut(Schema):
    requirement_id: int
    is_met: bool
    note: str
    evidence: list[EvidenceOut]
    # Evidence가 하나도 연결되지 않은 자가 응답인지 (ADR-0014 — 미연결은 거부가
    # 아니라 표시만 한다. 점수화는 #12 소관).
    is_linked: bool


class SubmissionIn(Schema):
    # 아래 세 max_length는 각각 submissions.models.Submission의 같은 필드와
    # 길이를 맞춘다(#10 리뷰 지적) — 스키마가 막지 않으면 DB CHECK가 대신 걸려
    # 422 대신 500(DataError)이 난다.
    source_object_key: str = Field(max_length=600)
    demo_video_object_key: str | None = Field(default=None, max_length=600)
    demo_url: str | None = Field(default=None, max_length=2000)
    test_account: str | None = Field(default=None, max_length=500)
    requirement_responses: list[RequirementResponseIn] = []


class CompletionOut(Schema):
    """시연 영상·데모 URL·테스트 계정·Evidence 연결 상태를 요약한 완성도 지표.

    강제 항목은 아무 것도 없다 — 소스만 필수다. 이 지표는 신호일 뿐이다.
    """

    has_demo_video: bool
    has_demo_url: bool
    has_test_account: bool
    total_requirement_count: int
    linked_requirement_count: int
    unlinked_requirement_count: int


class SubmissionOut(Schema):
    id: int
    contest_id: int
    developer_id: int
    is_owner: bool
    # 뷰어가 볼 수 없는 필드는 값을 지우지 않고 아예 null로 내려 "존재하지만 안 보임"과
    # "비어 있음"을 구분한다.
    source_object_key: str | None
    demo_video_object_key: str | None
    demo_url: str | None
    test_account: str | None
    requirement_responses: list[RequirementResponseOut]
    completion: CompletionOut
    created_at: datetime
    updated_at: datetime


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
    def resolve_deadline_at(obj):
        return obj.contest.deadline_at

    @staticmethod
    def resolve_submitted_at(obj):
        return obj.created_at

    @staticmethod
    def resolve_next_action(obj) -> str:
        from .participation import next_action_for

        return next_action_for(obj)


class PublicSubmissionOut(Schema):
    """Developer 공개 프로필 아카이브 한 항목 (#11, ADR-0014).

    마감된 Contest의 데모·영상만 담는다 — 소스·test_account는 이 스키마 자체에
    없다("존재하지만 안 보임"이 아니라 애초에 필드가 없다). ADR-0014의 "마감 후"
    칸에 있는 건 데모·영상뿐이다.
    """

    submission_id: int
    contest_id: int
    contest_title: str
    demo_video_object_key: str | None
    demo_url: str | None
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
    entries: list[ComparisonEntryOut]


class ComparisonSubmissionOut(Schema):
    submission_id: int
    developer_id: int
    developer_display_name: str
    demo_video_object_key: str | None
    demo_url: str | None
    completion: CompletionOut


class ContestComparisonOut(Schema):
    contest_id: int
    submissions: list[ComparisonSubmissionOut]
    requirements: list[RequirementComparisonOut]


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
    """

    percentage: str
    model_version: str
    reasoning: list[dict]
    created_at: datetime
    # 이의 창이 언제 닫히는지. 기한을 만들어 놓고 화면에 적지 않으면 그 기한은
    # 달력을 들고 계산한 사람에게만 유리한 함정이 된다. 심사기간이 없는 Contest
    # 면 None 이고, 그때는 창이 닫히지 않는다.
    appeal_deadline: datetime | None = None
    # 지금 낼 수 있는가. `appeals.api.create_appeal` 의 전제와 **같은 함수**에서
    # 나온다 — 조건을 두 벌로 쓰면 언젠가 갈라지고, 그때 화면은 이의를 권해놓고
    # API 가 거절한다.
    can_appeal: bool = False

    @staticmethod
    def resolve_appeal_deadline(obj):
        return obj.submission.contest.judging_ends_at

    @staticmethod
    def resolve_can_appeal(obj) -> bool:
        from core.clock import Clock

        submission = obj.submission
        if getattr(submission, "appeal", None) is not None:
            return False
        return submission.contest.appeal_window_open(Clock.now())

    @staticmethod
    def resolve_percentage(obj) -> str:
        # `Decimal` 을 그대로 두면 JSON 에서 float 가 된다 — 배분 컷라인이 쓰는
        # 것과 같은 십진값이므로 자릿수를 잃지 않게 문자열로 내린다.
        return str(obj.percentage)


# --- Sponsor 지표 화면 (#107, 부모 #105) ---------------------------------------
#
# 「제출을 하나씩 열어보는 것뿐」이던 Sponsor 에게 자기 Contest 의 건강을
# 보여준다. **이 화면이 뒤 티켓들의 자리이기도 하다** — #107 은 일자별 누적
# 참가작 수만 세우고, 이어지는 티켓들(#108: Requirement 충족 분포·제출 완성도
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
    """제출 완성도 분포 — 데모·시연 영상·테스트 계정이 붙은 Submission 비율 (#108).

    `submissions.schemas.CompletionOut` 이 Submission 한 건에 대해 매기는 세
    boolean(has_demo_video·has_demo_url·has_test_account)을 Contest 전체로
    집계한 것이다. 참가작들이 실제로 확인 가능한 상태인지 가늠하는 신호일
    뿐 — 강제 항목은 아니다(소스만 필수다).
    """

    total_submission_count: int
    demo_video_count: int
    demo_url_count: int
    test_account_count: int


class ViewMetricsOut(Schema):
    """조회수와 전환율 — 「본 사람 대비 낸 사람」(#109, 부모 #105).

    `view_count`는 `contests.view_tracking.get_view_count`가 캐시에서 읽은
    값이다 — 관계형 DB의 Contest 행이 아니다(공개 상세는 트래픽이 가장
    많은 화면이라 조회마다 그 행을 갱신하면 경합이 생긴다). 이 스키마에도
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


class ErrorOut(Schema):
    """django-ninja 의 `HttpError` 가 내는 모양 — 4xx 를 생성 타입에 드러낸다."""

    detail: str
