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
    #: 채점 모델이 추론 모델일 때만 뜻이 있는 기본 추론 강도(#402) —
    #: "low"|"medium"|"high". 필드를 생략하면 바꾸지 않는다.
    default_reasoning_effort: str | None = None
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
    #: `default_model`이 추론 모델(GPT-5 이후)인가(#402) — 화면이 이 값
    #: 하나로 「추론 강도」 칸을 보일지 정한다(모델 목록 조회와 무관하게
    #: 언제나 이 서버 값을 따른다, Testing Decisions 「프론트」).
    default_model_is_reasoning: bool = False
    #: 채점 모델이 추론 모델일 때만 뜻이 있는 기본 추론 강도(#402) —
    #: "low"|"medium"|"high".
    default_reasoning_effort: str
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
    #: 토큰 단위 컨텍스트 윈도 — 모르는 모델은 `None`이다(#401 AC "크기
    #: 미확인").
    context_window: int | None = None
    #: GPT-5 이후 세대인가(#402) — 화면이 이 값으로 「추론 강도」 칸을
    #: 보일지 정한다.
    is_reasoning_model: bool = False


class ScoringModelCatalogOut(Schema):
    """클래스 기준 채점 모델 선택지(#401) — 기존 전역 `GET
    /classroom/scoring-models`를 대신한다. `source`가 "fallback"이면
    `unavailable_reason`("no_api_key"|"fetch_failed")이 함께 실려 화면이
    안내 한 줄을 보인다."""

    models: list[ScoringModelOut]
    source: str
    unavailable_reason: str | None = None


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
    #: 이 문제만의 추론 강도(#402). 빈 문자열이면 클래스 기본값을 따른다 —
    #: `model`과 같은 모양. 채점 모델이 추론 모델이 아니면 저장은 되어도
    #: 채점에는 쓰이지 않는다.
    reasoning_effort: str = ""
    #: 채점 지침 단계(#386, CONTEXT.md 「채점 지침」) —
    #: "strict"|"normal"|"lenient"|"custom" 중 하나. 기본은 "normal"이다.
    #: 모르는 값은 422다.
    grading_strictness: str = "normal"
    #: `grading_strictness`가 "custom"일 때의 강사 문장. 그 밖의 단계에서
    #: 보내도 API가 무시하고 빈 문자열로 저장한다 — 두 칸이 어긋난 상태를
    #: 구조로 막는다.
    grading_guideline_text: str = Field(default="", max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH)
    #: 문법 검사 기본 항목 「소스에 문법 오류가 없다」의 켜짐 여부(#410,
    #: CONTEXT.md 「문법 검사」). 기본은 켜짐이다 — 의사코드처럼 실행되는
    #: 코드가 아닌 문제라면 강사가 끌 수 있다.
    syntax_check_enabled: bool = True
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
    #: 빈 문자열을 보내면 문제 자신의 추론 강도를 지우고 클래스 기본값을
    #: 따르게 한다 — `model`과 같은 관례(#402). `None`(필드 생략)은
    #: 바꾸지 않는다.
    reasoning_effort: str | None = None
    #: 필드를 생략하면(`None`) 바꾸지 않는다. 보내면 `ProblemIn`과 같은
    #: 규칙(#386) — 모르는 값·빈 직접 입력 문장은 422다.
    grading_strictness: str | None = None
    #: 필드를 생략하면(`None`) 바꾸지 않는다. `grading_strictness`가
    #: (이번 요청이나 기존 값으로) "custom"이 아니게 되면 이 값은 저장
    #: 시점에 빈 문자열로 덮인다.
    grading_guideline_text: str | None = Field(
        default=None, max_length=GRADING_GUIDELINE_TEXT_MAX_LENGTH
    )
    #: 필드를 생략하면(`None`) 바꾸지 않는다. 보내면 그 값으로 켜고 끈다
    #: (#410) — 켜고 꺼도 이미 매긴 판정은 바뀌지 않는다(ADR-0006).
    syntax_check_enabled: bool | None = None
    #: 공모전 문제의 수업용 안내(#548). 공모전 문제가 아니면 422다.
    instructor_note: str | None = Field(default=None, max_length=5000)


class ProblemTransitionOut(Schema):
    """전이 표(`classroom.problem_transitions`) 한 줄(#440) — 강사용 문제
    응답이 「지금 상태에서 나갈 수 있는 전이」를 이 모양으로 싣는다. 지금
    그래프는 상태마다 나가는 간선이 하나뿐이라 `ProblemOut.
    available_transitions`는 언제나 원소 하나짜리 목록이다."""

    #: "open" | "hide" | "reopen".
    name: str
    #: 이 전이가 성공하면 도달하는 상태.
    to_state: str
    #: `None`이면 지금 바로 부를 수 있다. 아니면 "archived"(클래스가
    #: 보관됨) | "no_required_item"(필수 체크리스트 항목이 하나도 없음).
    blocked_reason: str | None = None


class ProblemContestOut(Schema):
    """공모전 문제가 따라가는 공모전의 지금 상태(#548) — 강의실은 공모전 앱을 모르므로
    공유층 카탈로그가 답한 것만 싣는다."""

    contest_id: int
    #: 지금 「공모전에도 내기」를 받는가 — 공개 중 · 마감 전 · 개최자가 허용 중.
    accepts_entries: bool
    deadline_at: datetime | None = None


class ImportableContestOut(Schema):
    """들여올 수 있는 무료 공모전 한 줄(#548)."""

    contest_id: int
    title: str
    deadline_at: datetime
    requirement_count: int


class ImportContestIn(Schema):
    contest_id: int


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
    #: `effective_model`이 추론 모델(GPT-5 이후)인가(#402) — 화면이 이
    #: 값으로 「추론 강도」 칸을 보일지 정한다.
    effective_model_is_reasoning: bool = False
    #: 이 문제 자신의 추론 강도(#402). 빈 문자열이면 클래스 기본값을
    #: 따른다는 뜻이다 — `model`/`effective_model`과 같은 모양.
    reasoning_effort: str = ""
    #: 실제로 채점에 쓰일 추론 강도 — `reasoning_effort`가 비어 있으면
    #: 클래스의 `default_reasoning_effort`. 채점 모델이 추론 모델이 아니면
    #: 이 값은 채점에 쓰이지 않는다.
    effective_reasoning_effort: str = ""
    #: 벤더가 이 문제의 채점 모델을 그 클래스의 키로 거부했는가(#403) —
    #: 참이면 어느 시도도 채점되지 않는다. 강사가 모델을 바꾸면(이 문제
    #: 자신의 값이든 클래스 기본값이든, 이 문제가 그 값을 물려받는 한)
    #: 다시 거짓으로 돌아온다.
    scoring_model_rejected: bool = False
    #: 채점 지침 단계(#386) — "strict"|"normal"|"lenient"|"custom".
    grading_strictness: str
    #: `grading_strictness`가 "custom"일 때만 채워지고, 그 밖의 단계에서는
    #: 언제나 빈 문자열이다(저장 시점에 이미 그렇게 정규화된다).
    grading_guideline_text: str
    #: 문법 검사 기본 항목 「소스에 문법 오류가 없다」의 켜짐 여부(#408,
    #: CONTEXT.md 「문법 검사」). 기본은 켜짐이고, 강사는 끌 수만 있다(#410).
    syntax_check_enabled: bool = True
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
    #: 이 문제를 지금 지울 수 있는가(#430/#431, ADR-0050) — 화면은 시도를
    #: 세지 않고 이 칸만 본다(`ClassOut.has_submissions`와 같은 관용구,
    #: 반대 극성: 저쪽은 "있으면 막는다", 이쪽은 "없으면 연다"). 기본값은
    #: 거짓이다(fail-closed) — `_serialize_problem`이 언제나 실제 판정값을
    #: 명시하지만, 혹시 다른 생성 경로가 이 칸을 빠뜨려도 삭제 버튼이
    #: 함부로 뜨지 않는 쪽으로 넘어진다.
    deletable: bool = False
    #: 지금 상태에서 나갈 수 있는 전이와 각자 막힌 이유(#440,
    #: `classroom.problem_transitions.available_transitions`) — 수정
    #: 화면은 이 목록으로 열기·숨기기·다시 열기 버튼을 그리고, 화면 안에서
    #: 상태별 버튼을 다시 계산하지 않는다.
    available_transitions: list[ProblemTransitionOut] = []
    #: 공모전 문제면 그 공모전의 지금 상태(#548), 아니면 None.
    contest: ProblemContestOut | None = None
    #: 공모전 문제의 수업용 안내(#548).
    instructor_note: str = ""


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
    #: 이름 칸 기본값으로 쓸 제안 이름(#390) — 로그인한 사람의 카카오
    #: 닉네임이다. 로그인하지 않았거나 닉네임이 비어 있으면(동의하지 않음,
    #: 카카오가 아닌 제공자) `None`이다 — 화면은 그때 이름 칸을 그냥 비워
    #: 둔다.
    suggested_name: str | None = None


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
    없다. 열린 문제와, 낸 적 있는 숨긴 문제 둘 다 이 자리에 닿지만(#405) 그
    구별은 `ClassroomProblemSubmissionsOut.submit_blocked_reason`(#439)이
    대신 진다 — 이 조각 자체는 여전히 상태를 모른다.

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
    #: 공모전 문제면 그 공모전의 지금 상태(#548), 아니면 None.
    contest: ProblemContestOut | None = None
    #: 공모전 문제의 수업용 안내(#548).
    instructor_note: str = ""
    #: 채점 지침 단계(#388, CONTEXT.md 「채점 지침」) — 참여자도 어떤 기준으로
    #: 판정되는지 알고 제출해야 한다(#385 User Story 18).
    grading_strictness: str
    #: `grading_strictness`가 "custom"일 때만 채워진다.
    grading_guideline_text: str
    #: 문법 검사 기본 항목의 켜짐 여부(#408) — 참이면 참여자 화면이 체크리스트
    #: 맨 앞에 「소스에 문법 오류가 없다」와 「기본」 표시를 둔다.
    syntax_check_enabled: bool = True
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


class ClassroomSyntaxCheckFindingOut(Schema):
    """파서가 실제로 찾은 구문 오류 하나(#408) — 어느 파일 몇 번째 줄에서
    무슨 오류인지."""

    path: str
    line: int | None = None
    message: str


class ClassroomSyntaxCheckOut(Schema):
    """문법 검사 기본 항목의 판정 하나(#408, CONTEXT.md 「문법 검사」) —
    `ClassroomScore.syntax_check_result`를 그대로 비춘다. append-only라 이
    값도 한 번 나오면 바뀌지 않는다."""

    is_met: bool
    reasoning: str
    #: "parser" | "ai" — 파서가 판정했는지 AI가 판정했는지(#409).
    judged_by: str
    findings: list[ClassroomSyntaxCheckFindingOut] = []


class ClassroomScoreOut(Schema):
    """채점 스냅샷 하나(#287) — `classroom.models.ClassroomScore`를 그대로
    비춘다. append-only라 이 값은 한 번 나오면 바뀌지 않는다."""

    model_version: str
    reasoning: list[ClassroomChecklistVerdictOut]
    #: 문법 검사 기본 항목의 판정(#408) — 채점 시점에 그 문제의 기본 항목이
    #: 꺼져 있었으면 `None`이다.
    syntax_check: ClassroomSyntaxCheckOut | None = None
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
    #: "no_api_key" | "budget_exhausted" | "model_rejected" | `None` —
    #: `classroom.pending_scoring.pending_reason`이 이 우선순위(키 → 모델 →
    #: 예산)로 정한다(#434). `status`가 "pending"일 때만 채워진다 — 강사가
    #: 채점 키를 아직 설정하지 않았으면(#346) 예산과 무관하게 "no_api_key",
    #: 키는 멀쩡한데 이 문제의 채점 모델을 그 키로 못 쓰면(#403)
    #: "model_rejected", 키·모델 둘 다 멀쩡한데 예산이 바닥났으면(#295)
    #: "budget_exhausted"다. 셋 다 참여자가 스스로 어쩔 수 없는 사유라
    #: 문구도 "당신 잘못이 아니고 다시 낼 필요도 없다"는 같은 모양을 낸다
    #: (참여자 화면은 "model_rejected"를 "no_api_key"와 같은 안내로
    #: 보여준다 — #403 AC "참여자에게는 기존 「채점하지 못함」 안내를
    #: 보인다") — 강사 화면만 셋을 다르게 말하며, 강사가 무엇을 해야
    #: 풀리는가(키를 넣는다/예산을 늘린다/모델을 바꾼다)가 다를 뿐이다.
    pending_reason: str | None = None


class ClassroomProblemSubmissionsOut(Schema):
    #: 이 문제가 속한 클래스의 이름(#372 후속) — `ClassroomMyProblemsOut.class_name`
    #: 과 같은 이유로 싣는다.
    class_name: str
    problem: ClassroomProblemMineOut
    submissions: list[ClassroomSubmissionOut]
    #: 이 요청을 보낸 사람이 지금 새로 낼 수 없는 이유 하나, 낼 수 있으면
    #: `None`(#439). "archived"(클래스가 보관됨) | "expelled"(내보내짐) |
    #: "hidden"(강사가 이 문제를 숨김) | "viewing_as_instructor"(강사가 학생
    #: 화면으로 보는 중) 중 하나다 — 우선순위는 보관 → 내보냄 → 숨김이고
    #: (`classroom.participation.participant_submit_blocked_reason`), 강사
    #: 보기는 그 셋과 겹치지 않는 별도 판정이다. 예전의 네 불리언
    #: (`member_expelled`·`archived`·`problem_hidden`·`viewing_as_instructor`)을
    #: 이 값 하나로 합쳤다 — 화면이 우선순위를 다시 계산하지 않는다. 지난
    #: 시도는 이 값과 무관하게 `submissions`에 그대로 남는다 — 막히는 것은
    #: 새 제출뿐이다.
    submit_blocked_reason: str | None = None
    #: `submit_blocked_reason`이 "viewing_as_instructor"일 때만 채워지는 문제
    #: 상태("draft"|"open"|"hidden") — 띠가 몇 줄을 더 말할지 이 값으로
    #: 정한다. 참여자 시점에는 언제나 `None`이다(참여자에게는 상태 구분이
    #: 필요 없다는 것이 이미 `ClassroomProblemMineOut`의 설계다).
    instructor_problem_status: str | None = None
    #: 이 화면을 그 클래스의 **강사가** 열었는가(2026-09-17, #429 개정).
    #: 예전에는 `submit_blocked_reason == "viewing_as_instructor"` 하나가 「강사가
    #: 보는 중」과 「그래서 낼 수 없다」를 함께 뜻했는데, 열린 문제에는 강사도
    #: 낼 수 있게 되면서 둘이 갈렸다 — 띠(「학생 화면으로 보고 있다」)는 이
    #: 값으로, 제출 잠금은 `submit_blocked_reason`으로 정한다.
    viewing_as_instructor: bool = False


class ClassroomProblemStatsOut(Schema):
    """참여자 × 문제 격자의 열 머리와 달성률 행(#290) — 문제 중심 탭의
    `ProblemOut`과 같은 `passed_count`·`member_count`·`pass_rate`를 그대로
    옮긴다(같은 계산 함수를 재사용해 두 화면이 어긋나지 않는다, AC "달성률
    행의 값이 문제 중심 탭의 값과 정확히 같다")."""

    id: int
    title: str
    #: 초안·열림·숨김(#405) — 명단 격자에도 「숨김」 표시가 남아야 한다
    #: (CONTEXT.md 「Problem」).
    status: str
    passed_count: int
    member_count: int
    pass_rate: float | None = None


class ClassroomGridCellOut(Schema):
    problem_id: int
    #: "passed" | "attempted_not_passed" | "needs_setup" | "scoring" |
    #: "not_submitted" — 통과 이력을 그린다(최신 시도가 아니다, #290 AC).
    #: 우선순위는 이 순서대로다: 한 번이라도 통과했으면 다른 시도의 결과와
    #: 무관하게 "passed"다. "needs_setup"(#434)은 그 클래스에 채점 키가
    #: 아예 없거나 거부됐거나(#346, #355), 이 문제의 채점 모델이 거부돼
    #: (#403) 미채점 시도가 애초에 후보에도 못 드는 경우다 —
    #: "scoring"(정말 채점을 기다리는 중, 예산 소진 포함)과 다르게, 이
    #: 셀은 강사가 직접 손대기 전까지는 절대 바뀌지 않는다
    #: (`classroom.pending_scoring.needs_setup`).
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
    #: 강사가 숨겼지만(#405) 이 참여자가 한 번이라도 낸 문제들 — 통과
    #: 여부와 함께 `problems`와 따로 싣는다(#406). 낸 적 없는 숨긴 문제는
    #: 여기도 `problems`도 싣지 않는다 — 존재 자체가 숨겨진다. 다시 열리면
    #: 이 목록에서 빠지고 `problems`로 돌아간다.
    hidden_problems: list[ClassroomProblemListItemOut] = []


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
    #: 문법 검사 기본 항목의 켜짐 여부(#410) — 복사하면 그대로 옮겨간다.
    syntax_check_enabled: bool = True
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
    #: 공개 시점 원본의 채점 지침(#389, CONTEXT.md 「채점 지침」) — 가져가기
    #: 전에 어떤 기준으로 채점될지 미리 본다.
    grading_strictness: str
    #: grading_strictness가 "custom"일 때만 채워진다.
    grading_guideline_text: str
    #: 문법 검사 기본 항목의 공개 시점 켜짐 여부(#410) — 가져가기 전에
    #: 미리보기가 이 값을 보여준다(#410 AC "템플릿 미리보기에 켜짐 여부가
    #: 보인다").
    syntax_check_enabled: bool = True
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
    #: `ProblemTemplateOut.grading_strictness`와 같은 이유·같은 모양(#389).
    grading_strictness: str
    grading_guideline_text: str
    #: `ProblemTemplateOut.syntax_check_enabled`와 같은 이유·같은 모양(#410).
    syntax_check_enabled: bool = True
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
