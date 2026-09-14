from __future__ import annotations

from datetime import datetime
from typing import Annotated

from ninja import Field, Schema

from .grading_guidelines import GRADING_GUIDELINE_TEXT_MAX_LENGTH


class ErrorOut(Schema):
    detail: str


#: 참여자가 클래스에서 불릴 이름의 검증 규칙(#280) — 가입 때(`JoinIn`)와
#: 나중에 스스로 바꿀 때(`MemberRenameIn`, #372) 둘 다 이 정의 하나를
#: 쓴다, 규칙이 갈라지지 않도록.
ClassMemberDisplayName = Annotated[str, Field(min_length=1, max_length=100)]


class ClassIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    #: 강사가 이 클래스에서 불릴 이름(#299) — 비워서 만들 수 없다. 가입
    #: 미리보기에 강사 이메일 대신 뜬다.
    instructor_display_name: str = Field(min_length=1, max_length=100)


class ClassPatchIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    #: 클래스 설정에서 고친다(#299). 필드를 생략하면 바꾸지 않는다 — 기존
    #: PATCH 관례 그대로다.
    instructor_display_name: str | None = Field(default=None, min_length=1, max_length=100)
    default_model: str | None = None
    #: 채점 토큰 예산 상한(#295). 필드를 생략하면(`None`) 바꾸지 않는다 —
    #: 기존 PATCH 관례 그대로다. 이 API에는 "다시 무제한으로 되돌리는" 값이
    #: 없다 — 그 요구가 아직 없어 짓지 않는다.
    token_budget: int | None = Field(default=None, ge=1)
    #: 경고 알림을 보낼 임계, 예산 대비 백분율(1~100, #295).
    token_budget_warning_threshold_percent: int | None = Field(default=None, ge=1, le=100)


class PublishedTemplateSummaryOut(Schema):
    """이 클래스/문제를 원본으로 하는, 지금 살아 있는(내리지 않은) 템플릿
    하나(#333) — 있으면 새로고침해도 공개 상태(공유 링크·「내리기」)가 이
    자리에서 그대로 보인다. 없으면 `None`이라 화면이 공개 폼을 보여준다."""

    share_code: str
    publisher_display_name: str
    created_at: datetime


class ClassOut(Schema):
    id: int
    name: str
    #: 빈 문자열이면(#299) 이 필드가 생기기 전에 만들어진 클래스다 — 가입
    #: 미리보기가 그 줄을 생략한다.
    instructor_display_name: str
    join_code: str
    created_at: datetime
    default_model: str
    has_openai_key: bool
    openai_key_masked: str | None = None
    #: 키가 있을 때만 뜻이 있다("verified"|"unverified"|"rejected") — 키가
    #: 없으면 `None`이다(#354). `Class.ScoringKeyStatus`의 값 그대로다.
    openai_key_status: str | None = None
    #: 강사가 보관했는가(#294) — 참이면 새 가입·새 제출이 닫히고 읽기만
    #: 남는다. `archived_at`이 아니라 이 값을 내려주는 이유는 화면이 정확한
    #: 시각을 쓰지 않기 때문이다(진행중/보관 여부만 갈라 보이면 된다).
    archived: bool = False
    #: `None`이면 무제한(#295) — 강사가 아직 예산을 정하지 않았다는 뜻이다.
    token_budget: int | None = None
    token_budget_warning_threshold_percent: int
    #: 지금까지 실제로 쓴 토큰 누적합.
    token_usage_total: int
    #: `token_budget - token_usage_total` — 예산이 없으면(무제한) `None`이다.
    token_budget_remaining: int | None = None
    #: 지금 채점이 예산 때문에 멈춰 있는가 — 강사 화면이 이 값 하나로
    #: "채점 정지 중" 배지를 낸다.
    token_budget_exhausted: bool = False
    #: 이 클래스의 어느 문제에도 제출이 하나라도 있는가(#330). 삭제 가능
    #: 여부를 화면이 문제·제출물 목록을 합쳐 스스로 셈하지 않도록 백엔드가
    #: 판정해 내려준다 — `DELETE .../classes/{id}`도 같은 사실로 거절한다.
    has_submissions: bool = False
    #: 이 클래스를 원본으로 하는, 지금 살아 있는 클래스 템플릿(#333). 없으면
    #: `None`이다 — 클래스 설정 화면이 이 값으로 공개 폼과 공개된 상태를
    #: 새로고침 뒤에도 정확히 가른다.
    published_template: PublishedTemplateSummaryOut | None = None


class OpenAIKeyIn(Schema):
    api_key: str = Field(min_length=1, max_length=400)


class JoinedClassOut(Schema):
    """「내가 참여자로 들어간 클래스」한 줄(#328) — 강사 전용 `ClassOut`과
    달리 `join_code`·OpenAI 키·토큰 예산을 싣지 않는다: 그 값들은 강사만의
    것이라 참여자가 자기 가입 목록을 볼 때 남의 클래스 관리 정보를 함께
    받으면 안 된다."""

    id: int
    name: str
    #: 강사가 이 클래스에서 불릴 이름으로 정한 값(#299). 빈 문자열이면
    #: `JoinPreviewOut`과 같은 이유로 생략 대상이다 — 화면이 판단한다.
    instructor_display_name: str
    joined_at: datetime
    #: 보관된 클래스인가(#294) — 참이면 새 가입·새 제출은 닫혔지만 지난
    #: 기록은 그대로 읽힌다.
    archived: bool = False
    #: 강사가 내보냈는가(#281) — 참이어도 행은 지워지지 않고 지난 시도·판정은
    #: 그대로 읽힌다(`member_expelled`와 같은 신호, #300). 새 제출만 막힌다.
    expelled: bool = False


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
    #: 강사가 하나 이상 고른 형식(#373) — 빈 목록·모르는 값은 422다.
    submission_formats: list[str]
    #: 만들기 화면에서 함께 적는 체크리스트 항목(#315) — 순서가 그대로
    #: `ChecklistItem.order`가 된다. 비어 있으면 지금처럼 항목 없는 초안이
    #: 생긴다.
    checklist_items: list[ChecklistItemIn] = []
    #: 이 문제만의 채점 모델(#327). 빈 문자열이면 클래스 기본값을 따른다 —
    #: 화면의 「클래스 기본값을 따릅니다」가 보내는 값이 그것이다. 편집
    #: 화면(#285)에만 있던 것을 만들기로 당겨 온다: 마크다운 에디터(#324)로
    #: 긴 설명을 쉽게 쓰게 되면서, 기본값(가장 작은 컨텍스트)으로 열린 뒤에야
    #: 고칠 수 있다는 것이 더 자주 물리게 됐다.
    model: str = ""
    #: 채점 지침 단계(#386, CONTEXT.md 「채점 지침」) —
    #: "strict"|"normal"|"lenient"|"custom" 중 하나. 기본은 "normal"이다.
    #: 모르는 값은 422다.
    grading_strictness: str = "normal"
    #: `grading_strictness`가 "custom"일 때의 강사 문장. 그 밖의 단계에서
    #: 보내도 API가 무시하고 빈 문자열로 저장한다 — 두 칸이 어긋난 상태를
    #: 구조로 막는다.
    grading_guideline_text: str = Field(default="", max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH)
    #: True면 만든 직후 바로 연다(「만들고 바로 열기」, #315). 필수 항목이
    #: 하나도 없으면(열기 엔드포인트와 같은 규칙) 요청 전체가 거부되고
    #: 문제도 생기지 않는다.
    open: bool = False


class ProblemPatchIn(Schema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    #: 필드를 생략하면(`None`) 바꾸지 않는다 — 기존 PATCH 관례 그대로다.
    #: 보내면 빈 목록·모르는 값은 422다(#373).
    submission_formats: list[str] | None = None
    #: 빈 문자열을 보내면 문제 자신의 모델을 지우고 클래스 기본값을
    #: 따르게 한다 — `None`(필드 생략)은 "바꾸지 않는다"는 기존 PATCH
    #: 관례 그대로다.
    model: str | None = None
    #: 필드를 생략하면(`None`) 바꾸지 않는다. 보내면 `ProblemIn`과 같은
    #: 규칙(#386) — 모르는 값·빈 직접 입력 문장은 422다.
    grading_strictness: str | None = None
    #: 필드를 생략하면(`None`) 바꾸지 않는다. `grading_strictness`가
    #: (이번 요청이나 기존 값으로) "custom"이 아니게 되면 이 값은 저장
    #: 시점에 빈 문자열로 덮인다.
    grading_guideline_text: str | None = Field(
        default=None, max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH
    )


class ProblemOut(Schema):
    id: int
    classroom_id: int
    title: str
    description: str
    #: 강사가 받기로 고른 형식들(#373) — 소스·저장소의 비어 있지 않은
    #: 부분집합.
    submission_formats: list[str]
    status: str
    order: int
    #: 이 문제 자신의 값. 빈 문자열이면 클래스 기본값을 따른다는 뜻이다.
    model: str
    #: 실제로 채점에 쓰일 값 — `model`이 비어 있으면 클래스의 `default_model`.
    effective_model: str
    #: 채점 지침 단계(#386) — "strict"|"normal"|"lenient"|"custom".
    grading_strictness: str
    #: `grading_strictness`가 "custom"일 때만 채워지고, 그 밖의 단계에서는
    #: 언제나 빈 문자열이다(저장 시점에 이미 그렇게 정규화된다).
    grading_guideline_text: str
    checklist_items: list[ChecklistItemOut] = []
    #: 이 문제를 한 번이라도 통과한 참여자 수(#289, CONTEXT.md 「달성률」) —
    #: 강사 본인과 내보내진 참여자는 빼고 센다.
    passed_count: int = 0
    #: 달성률의 분모 — 강사 본인·내보내진 참여자를 뺀 참여자 수.
    member_count: int = 0
    #: `passed_count / member_count`. 분모가 0이면 `None`이다 — 화면이 그때
    #: "0%"가 아니라 "아직 없음"으로 말하도록 0.0과 구별한다(#289 AC).
    pass_rate: float | None = None
    #: 이 문제를 원본으로 하는, 지금 살아 있는 문제 템플릿(#333) —
    #: `ClassOut.published_template`과 같은 이유·같은 모양.
    published_template: PublishedTemplateSummaryOut | None = None


class ProblemReorderIn(Schema):
    problem_ids: list[int]


class JoinPreviewOut(Schema):
    #: 로그인한 사람이 곧장 문제 목록으로 이동할 때 쓸 id(#300). 가입 여부와
    #: 무관하게 항상 채워진다 — 가입하면 어차피 `JoinResultOut.class_id`로
    #: 같은 값을 다시 받으므로 숨길 이유가 없다.
    class_id: int
    class_name: str
    #: 강사가 이 클래스에서 불릴 이름으로 정한 값(#299) — 강사 이메일은
    #: 응답 어디에도 싣지 않는다. `None`이면(이 필드가 생기기 전에 만들어진
    #: 클래스, 아직 강사가 정하지 않음) 화면이 이 줄 자체를 생략한다.
    instructor_display_name: str | None = None
    problem_count: int
    participant_count: int
    #: 보관된 클래스인가(#294). 죽은 링크(404)와 달리 미리보기 자체는 계속
    #: 보여준다 — "고장"이 아니라 "끝났다"로 읽혀야 하기 때문이다. 참이면
    #: 화면이 가입 폼 대신 안내문을 보여준다.
    archived: bool = False
    #: 지금 로그인한 사람이 이미 이 클래스의 참여자인가(#300) — **내보내진
    #: 사람도 참이다**, 행이 지워지지 않으므로(`ClassMember.expelled_at`
    #: docstring). 로그인하지 않았으면 항상 거짓이다. 참이면 화면이 이름 입력
    #: 폼을 건너뛰고 곧장 문제 목록으로 보낸다 — 이미 정한 이름은 바뀌지
    #: 않고, 다시 가입되지도 않는다(가입 요청 자체를 보내지 않으므로).
    already_joined: bool = False


class JoinIn(Schema):
    display_name: ClassMemberDisplayName


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


class MemberRenameIn(Schema):
    display_name: ClassMemberDisplayName


class MemberRenameOut(Schema):
    display_name: str


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
    submission_formats: list[str]
    #: 채점 지침 단계(#388, CONTEXT.md 「채점 지침」) — 참여자도 어떤 기준으로
    #: 판정되는지 알고 제출해야 한다(#385 User Story 18).
    grading_strictness: str
    #: `grading_strictness`가 "custom"일 때만 채워진다.
    grading_guideline_text: str
    checklist_items: list[ChecklistItemOut] = []
    #: 이 문제를 한 번이라도 통과한 적이 있는가(#288, CONTEXT.md 「통과」) —
    #: 최신 시도가 아니라 시도 전체에 대한 OR다. 한 번 통과하면 나중에 다시
    #: 내서 미통과가 나와도 계속 참이다.
    passed: bool = False


class ClassroomSubmissionIn(Schema):
    #: 이 시도에서 고른 형식(#373) — 문제의 허용 목록에 있어야 한다, 없으면
    #: 422다. 문제가 형식을 하나만 열어 뒀어도 화면이 그 값을 그대로 보낸다
    #: — 참여자가 고르는 단계가 없을 뿐 페이로드는 항상 명시한다.
    submission_format: str
    #: `submission_format`이 소스면 storage가 발급한 object_key, 저장소면
    #: GitHub URL.
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
    #: "no_api_key" | "budget_exhausted" | `None`. `status`가 "pending"일 때만
    #: 채워진다 — 강사가 채점 키를 아직 설정하지 않았으면(#346) 예산과 무관하게
    #: "no_api_key", 키는 있는데 예산이 바닥났으면(#295) "budget_exhausted"다.
    #: 둘 다 참여자가 스스로 어쩔 수 없는 사유라 문구도 "당신 잘못이 아니고
    #: 다시 낼 필요도 없다"는 같은 모양을 낸다 — 둘을 가르는 것은 강사가 무엇을
    #: 해야 풀리는가(키를 넣는다/예산을 늘린다)뿐이다.
    pending_reason: str | None = None


class ClassroomProblemSubmissionsOut(Schema):
    #: 이 문제가 속한 클래스의 이름(#372 후속) — `ClassroomMyProblemsOut.class_name`
    #: 과 같은 이유로 싣는다.
    class_name: str
    problem: ClassroomProblemMineOut
    submissions: list[ClassroomSubmissionOut]
    #: 이 요청을 보낸 참여자가 강사에게 내보내졌는가(#300). 참이면 화면이
    #: 제출 수단을 아예 숨기고 그 이유를 말해 준다 — 시도는 지우지 않으므로
    #: `submissions`는 그대로 채워진다.
    member_expelled: bool = False
    #: 이 클래스가 보관됐는가(#294, #338). 참이면 화면이 제출 수단을 숨기고
    #: 수업이 끝났다는 이유를 보여준다 — `member_expelled`와 같은 신호 자리.
    #: 새 제출만 막힌다(`create_classroom_submission`의 403이 실제 문).
    archived: bool = False


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
    #: "passed" | "attempted_not_passed" | "no_api_key" | "scoring" |
    #: "not_submitted" — 통과 이력을 그린다(최신 시도가 아니다, #290 AC).
    #: 우선순위는 이 순서대로다: 한 번이라도 통과했으면 다른 시도의 결과와
    #: 무관하게 "passed"다. "no_api_key"는 그 클래스에 채점 키가 아예 없어
    #: 미채점 시도가 애초에 후보에도 못 드는 경우다(#346) — "scoring"(정말
    #: 채점을 기다리는 중)과 다르게, 이 셀은 강사가 채점 키를 넣기 전까지는
    #: 절대 바뀌지 않는다.
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
    #: 참여자용 `ClassroomSubmissionOut.pending_reason`과 같은 값·같은 이유
    #: (#346) — 강사도 "학생이 안 낸 것"과 "냈는데 강사 본인이 키를 안 넣어
    #: 멈춘 것"을 구별해야 한다.
    pending_reason: str | None = None


class ClassroomProblemListItemOut(Schema):
    """참여자의 문제 목록 한 줄(#288) — 통과/미통과가 한눈에 보이도록 문제
    상세보다 훨씬 좁다."""

    id: int
    title: str
    submission_formats: list[str]
    passed: bool


class ClassroomMyProblemsOut(Schema):
    """참여자의 문제 목록 응답(#372) — 그 화면 위쪽의 인라인 이름 편집 칸이
    쓸 지금 이름과, 편집 칸 자체를 숨길지 판단할 신호 둘을 함께 싣는다.
    `member_display_name`은 참여자 본인의 이름 변경(`PATCH .../members/me`)
    직후 이 목록을 다시 불러오면 곧장 새 값을 반영한다 — 비정규화가 없다."""

    #: 이 클래스의 이름(#372 후속) — 화면 눈썹이 「클래스」 대신 어느 클래스인지
    #: 말한다. 참여자는 강사용 클래스 상세를 부를 수 없어 이 응답이 싣는다.
    class_name: str
    member_display_name: str
    #: 내보내진 참여자인가(#300, #372 AC) — 참이면 화면이 이름 편집 칸을
    #: 내지 않는다. `get_my_problem`의 `member_expelled`와 같은 신호다.
    member_expelled: bool
    #: 보관된 클래스인가(#294, #372 AC) — 참이면 화면이 이름 편집 칸을
    #: 내지 않는다. `get_my_problem`의 `archived`와 같은 신호다.
    archived: bool
    problems: list[ClassroomProblemListItemOut]


class ProblemCopyIn(Schema):
    target_class_id: int


class ImportableProblemOut(Schema):
    """새 문제 화면의 「이미 있는 문제로 시작하기」 시트, 「내 다른
    클래스에서」 탭 한 줄(#326) — 강사 본인이 **다른** 클래스에 가진
    문제다. 고르면 `POST /classes/{class_id}/problems/{problem_id}/copy`로
    지금 클래스에 그대로 복사한다(`ProblemCopyIn`) — 새 엔드포인트가
    아니라 #292의 그 복사를 반대 방향(받는 쪽)에서 부르는 것뿐이다."""

    id: int
    classroom_id: int
    classroom_name: str
    title: str
    description: str
    submission_formats: list[str]
    checklist_items: list[ProblemTemplateChecklistItemOut] = []


# --- 템플릿 (#316/#318/#320) -----------------------------------------------------


class PublishTemplateIn(Schema):
    #: 계정 표시 이름을 끌어오지 않는다 — 공개할 때 직접 적는다(#316 AC).
    publisher_display_name: str = Field(min_length=1, max_length=100)


class ProblemTemplateChecklistItemOut(Schema):
    label: str
    required: bool
    order: int


class ProblemTemplateOut(Schema):
    id: int
    share_code: str
    title: str
    description: str
    submission_formats: list[str]
    publisher_display_name: str
    created_at: datetime
    taken_down: bool = False
    checklist_items: list[ProblemTemplateChecklistItemOut] = []
    #: 보는 사람이 올린 사람 본인인가 — 화면이 「신고」 대신 「내리기」를
    #: 보여줄지 정하는 자리(#320 AC "자기 템플릿은 신고 대상이 아니다").
    is_mine: bool = False


class ProblemTemplateListItemOut(Schema):
    """검색 목록 한 줄(#318 AC) — 제목·올린 사람·올린 날짜만."""

    share_code: str
    title: str
    publisher_display_name: str
    created_at: datetime


class ImportTemplateIn(Schema):
    target_class_id: int


class ReportTemplateIn(Schema):
    reason: str = Field(min_length=1, max_length=1000)


class ReportResultOut(Schema):
    reported: bool = True


class ReportedTemplateOut(Schema):
    """운영자 신고 목록 한 줄(#320 AC "내용·신고 사유·신고 수")."""

    id: int
    title: str
    description: str
    submission_formats: list[str]
    publisher_display_name: str
    report_count: int
    report_reasons: list[str]
    taken_down: bool


class ModerationDecisionIn(Schema):
    decision: str  # "takedown" | "dismiss" — appeals.schemas.AppealRulingIn과 같은 관용구
    note: str = Field(min_length=1, max_length=2000)


# --- 클래스 템플릿 (#319) -----------------------------------------------------


class ClassTemplateProblemOut(Schema):
    title: str
    description: str
    submission_formats: list[str]
    order: int
    checklist_items: list[ProblemTemplateChecklistItemOut] = []


class ClassTemplateOut(Schema):
    id: int
    share_code: str
    name: str
    publisher_display_name: str
    created_at: datetime
    taken_down: bool = False
    problems: list[ClassTemplateProblemOut] = []
    #: 미리보기가 가져오기 전에 몇 개의 문제가 들어 있는지를 바로 말해주는
    #: 자리(#319 AC) — `len(problems)`와 같은 값이다.
    problem_count: int = 0
    is_mine: bool = False


class ClassTemplateListItemOut(Schema):
    """검색 목록 한 줄 — `ProblemTemplateListItemOut`과 같은 모양이다."""

    share_code: str
    name: str
    publisher_display_name: str
    created_at: datetime


class ImportClassTemplateIn(Schema):
    #: 가져가는 사람이 새 클래스에 붙일 이름(#319 AC "이름을 정할 수 있다") —
    #: 원본 이름을 그대로 쓰지 않는다.
    name: str = Field(min_length=1, max_length=200)
