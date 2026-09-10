from __future__ import annotations

from datetime import datetime

from ninja import Field, Schema


class ErrorOut(Schema):
    detail: str


class ClassIn(Schema):
    name: str = Field(min_length=1, max_length=200)


class ClassPatchIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    default_model: str | None = None


class ClassOut(Schema):
    id: int
    name: str
    join_code: str
    created_at: datetime
    default_model: str
    has_openai_key: bool
    openai_key_masked: str | None = None
    #: 강사가 보관했는가(#294) — 참이면 새 가입·새 제출이 닫히고 읽기만
    #: 남는다. `archived_at`이 아니라 이 값을 내려주는 이유는 화면이 정확한
    #: 시각을 쓰지 않기 때문이다(진행중/보관 여부만 갈라 보이면 된다).
    archived: bool = False


class OpenAIKeyIn(Schema):
    api_key: str = Field(min_length=1, max_length=400)


class ScoringModelOut(Schema):
    id: str
    label: str
    context_window: int


class JoinLinkOut(Schema):
    join_code: str


class ChecklistItemIn(Schema):
    label: str = Field(min_length=1, max_length=200)
    required: bool = True


class ChecklistItemPatchIn(Schema):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    required: bool | None = None


class ChecklistItemOut(Schema):
    id: int
    label: str
    required: bool
    order: int


class ChecklistReorderIn(Schema):
    item_ids: list[int]


class ProblemIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    submission_format: str


class ProblemPatchIn(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    submission_format: str | None = None
    #: 빈 문자열을 보내면 문제 자신의 모델을 지우고 클래스 기본값을
    #: 따르게 한다 — `None`(필드 생략)은 "바꾸지 않는다"는 기존 PATCH
    #: 관례 그대로다.
    model: str | None = None


class ProblemOut(Schema):
    id: int
    classroom_id: int
    title: str
    description: str
    submission_format: str
    status: str
    order: int
    #: 이 문제 자신의 값. 빈 문자열이면 클래스 기본값을 따른다는 뜻이다.
    model: str
    #: 실제로 채점에 쓰일 값 — `model`이 비어 있으면 클래스의 `default_model`.
    effective_model: str
    checklist_items: list[ChecklistItemOut] = []
    #: 이 문제를 한 번이라도 통과한 참여자 수(#289, CONTEXT.md 「달성률」) —
    #: 강사 본인과 내보내진 참여자는 빼고 센다.
    passed_count: int = 0
    #: 달성률의 분모 — 강사 본인·내보내진 참여자를 뺀 참여자 수.
    member_count: int = 0
    #: `passed_count / member_count`. 분모가 0이면 `None`이다 — 화면이 그때
    #: "0%"가 아니라 "아직 없음"으로 말하도록 0.0과 구별한다(#289 AC).
    pass_rate: float | None = None


class ProblemReorderIn(Schema):
    problem_ids: list[int]


class JoinPreviewOut(Schema):
    class_name: str
    instructor_email: str
    problem_count: int
    participant_count: int
    #: 보관된 클래스인가(#294). 죽은 링크(404)와 달리 미리보기 자체는 계속
    #: 보여준다 — "고장"이 아니라 "끝났다"로 읽혀야 하기 때문이다. 참이면
    #: 화면이 가입 폼 대신 안내문을 보여준다.
    archived: bool = False


class JoinIn(Schema):
    display_name: str = Field(min_length=1, max_length=100)


class JoinResultOut(Schema):
    class_id: int
    class_name: str
    display_name: str


class MemberOut(Schema):
    id: int
    display_name: str
    joined_at: datetime
    expelled: bool
    is_instructor: bool


class ClassroomProblemMineOut(Schema):
    """참여자가 보는 문제 하나(#286) — 강사 전용 `ProblemOut`과 달리 `status`가
    없다(참여자는 열린 문제만 이 자리에 닿으므로 구별할 이유가 없다).

    이름이 `Classroom` 접두어를 든다 — `contests.submission_schemas.
    ProblemOut`은 없지만 `SubmissionIn`·`SubmissionOut`은 있고, django-ninja가
    OpenAPI 컴포넌트 이름을 클래스명 그대로 쓰기 때문에 겹치면 조용히 한쪽을
    덮어써 공개 앱의 생성 타입이 깨진다(실제로 한 번 그랬다 — `pnpm --dir
    frontend typecheck`가 잡았다). 이 파일의 다른 `Submission*` 스키마도 같은
    이유로 전부 `Classroom` 접두어를 든다."""

    id: int
    classroom_id: int
    title: str
    description: str
    submission_format: str
    checklist_items: list[ChecklistItemOut] = []
    #: 이 문제를 한 번이라도 통과한 적이 있는가(#288, CONTEXT.md 「통과」) —
    #: 최신 시도가 아니라 시도 전체에 대한 OR다. 한 번 통과하면 나중에 다시
    #: 내서 미통과가 나와도 계속 참이다.
    passed: bool = False


class ClassroomSubmissionIn(Schema):
    #: `submission_format`이 소스면 storage가 발급한 object_key, 저장소면
    #: GitHub URL — 종류는 Problem이 이미 정해 두었으므로 페이로드에 다시
    #: 싣지 않는다(공모전의 다중 자료 배열과 다른 점).
    value: str = Field(min_length=1, max_length=2000)
    #: 업로드 발급 시 받은 content-type(#241과 같은 이유) — 소스가 아니면
    #: 무시한다. 다운로드 파일명의 확장자를 유도한다.
    content_type: str | None = None


class ClassroomChecklistVerdictOut(Schema):
    checklist_item_id: int
    is_met: bool
    reasoning: str


class ClassroomScoreOut(Schema):
    """채점 스냅샷 하나(#287) — `classroom.models.ClassroomScore`를 그대로
    비춘다. append-only라 이 값은 한 번 나오면 바뀌지 않는다."""

    model_version: str
    reasoning: list[ClassroomChecklistVerdictOut]
    created_at: datetime


class ClassroomSubmissionOut(Schema):
    id: int
    problem_id: int
    attempt_number: int
    submission_format: str
    value: str
    #: 소스 제출에만 채워진다 — 저장소는 `value` 자체가 이미 열어 볼 수 있는
    #: URL이라 별도 다운로드가 필요 없다. 파일명은 제출자 본인의 User 정보를
    #: 따른다(강의실 참여자는 DeveloperProfile이 없다, #286 AC).
    download_url: str | None = None
    created_at: datetime
    #: "pending"(아직 채점되지 않았다) 또는 "scored"(채점이 끝났다) — 화면이
    #: 「채점 중」을 구별하는 유일한 근거다(#287 AC). Score 유무만으로 정하므로
    #: 키가 없어 채점을 시작조차 못 한 시도도 "pending"이다 — 그 이유는 화면이
    #: 클래스의 `has_openai_key`를 함께 봐서 구별한다.
    status: str
    score: ClassroomScoreOut | None = None
    #: 이 시도 하나가 통과인가 — 채점된 필수 체크리스트 항목을 전부
    #: 충족했는가(#288). 미채점("pending")이면 항상 거짓이다.
    passed: bool = False


class ClassroomProblemSubmissionsOut(Schema):
    problem: ClassroomProblemMineOut
    submissions: list[ClassroomSubmissionOut]


class ClassroomProblemStatsOut(Schema):
    """참여자 × 문제 격자의 열 머리와 달성률 행(#290) — 문제 중심 탭의
    `ProblemOut`과 같은 `passed_count`·`member_count`·`pass_rate`를 그대로
    옮긴다(같은 계산 함수를 재사용해 두 화면이 어긋나지 않는다, AC "달성률
    행의 값이 문제 중심 탭의 값과 정확히 같다")."""

    id: int
    title: str
    passed_count: int
    member_count: int
    pass_rate: float | None = None


class ClassroomGridCellOut(Schema):
    problem_id: int
    #: "passed" | "attempted_not_passed" | "scoring" | "not_submitted" —
    #: 통과 이력을 그린다(최신 시도가 아니다, #290 AC). 우선순위는 이
    #: 순서대로다: 한 번이라도 통과했으면 다른 시도의 결과와 무관하게
    #: "passed"다.
    status: str


class ClassroomGridMemberOut(Schema):
    id: int
    display_name: str
    is_instructor: bool
    expelled: bool
    cells: list[ClassroomGridCellOut]


class ClassroomRosterGridOut(Schema):
    problems: list[ClassroomProblemStatsOut]
    members: list[ClassroomGridMemberOut]
class ClassroomInstructorSubmissionOut(Schema):
    """강사가 보는 시도 하나(#291) — 참여자용 `ClassroomSubmissionOut`과 같은
    모양에 `member_id`·`member_display_name`을 더한다. 강사는 자기 시도가
    아니라 클래스 전체를 훑어보므로 어느 참여자의 것인지가 함께 실려야
    한다."""

    id: int
    problem_id: int
    member_id: int
    member_display_name: str
    attempt_number: int
    submission_format: str
    value: str
    #: 소스 제출에만 채워진다(참여자용과 같은 이유) — 파일명은 참여자 이름과
    #: 시도 번호로 구별된다(#291 AC), 참여자 본인 이메일이 아니다.
    download_url: str | None = None
    created_at: datetime
    status: str
    score: ClassroomScoreOut | None = None
    passed: bool = False


class ClassroomProblemListItemOut(Schema):
    """참여자의 문제 목록 한 줄(#288) — 통과/미통과가 한눈에 보이도록 문제
    상세보다 훨씬 좁다."""

    id: int
    title: str
    submission_format: str
    passed: bool
class ProblemCopyIn(Schema):
    target_class_id: int
