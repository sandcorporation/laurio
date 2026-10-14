// 참여자 제출 백엔드 호출 (#286/#287/#288/#388). 강사 전용 `problems/api.ts`와
// 달리 여기는 참여자가 자기 시도만 보고 낸다. 공유 클라이언트 위에
// 선다(#462).
import type { ApiResult } from "@codemit/bff-client";

import { apiRequest, bffClient } from "@/lib/bff/client";
import type { ChecklistItemRow, GradingStrictness, ProblemContest, SubmissionFormat } from "@/lib/problems/api";
import type { ContestEntryForm, ContestEntryInput } from "./contest-entry";

export type ProblemMine = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  submission_formats: SubmissionFormat[];
  // 채점 지침 단계(#388, CONTEXT.md 「채점 지침」) — 참여자가 어떤 기준으로
  // 판정되는지 알고 제출하도록 문제 화면이 체크리스트 가까이 보여준다.
  grading_strictness: GradingStrictness;
  // grading_strictness가 "custom"일 때만 채워진다.
  grading_guideline_text: string;
  // 문법 검사 기본 항목의 켜짐 여부(#408) — 참이면 화면이 체크리스트 맨
  // 앞에 「소스에 문법 오류가 없다」와 「기본」 표시를 둔다.
  syntax_check_enabled: boolean;
  checklist_items: ChecklistItemRow[];
  // 공모전 문제면 그 공모전의 지금 상태(#548), 아니면 null.
  contest: ProblemContest | null;
  // 공모전 문제의 수업용 안내(#548) — 설명 위에 보인다.
  instructor_note: string;
  // 이 문제를 한 번이라도 통과한 적이 있는가(#288) — 최신 시도가 아니라
  // 시도 전체의 OR. 한 번 통과하면 나중에 미통과가 나와도 계속 참이다.
  passed: boolean;
};

// 참여자의 문제 목록 한 줄(#288) — 통과/미통과가 한눈에 보이도록 상세보다
// 훨씬 좁다.
export type ProblemListItem = {
  id: number;
  title: string;
  submission_formats: SubmissionFormat[];
  passed: boolean;
  // 통과 이력 상태(#639) — 격자·최근 시도와 같은 낱말. 미제출은 시도 0.
  status: "passed" | "attempted_not_passed" | "scoring" | "not_submitted";
  attempt_count: number;
  last_attempted_at: string | null;
};

// 참여자의 문제 목록 응답(#372) — 그 화면 위쪽 인라인 이름 편집 칸이 쓸 지금
// 이름과, 편집 칸을 숨길지 판단할 신호 둘을 함께 싣는다. `ProblemMine.passed`와
// 달리 여기 이름은 클래스마다 따로다(ClassMember 기준).
export type MyProblems = {
  // 화면 눈썹이 말할 클래스 이름(#372 후속).
  class_name: string;
  member_display_name: string;
  member_expelled: boolean;
  archived: boolean;
  problems: ProblemListItem[];
  // 강사가 숨겼지만(#405) 이 참여자가 한 번이라도 낸 문제들(#406) — 통과
  // 여부와 함께 `problems`와 따로 온다. 낸 적 없는 숨긴 문제는 여기도
  // 실리지 않는다.
  hidden_problems: ProblemListItem[];
};

export type ChecklistVerdict = {
  checklist_item_id: number;
  is_met: boolean;
  reasoning: string;
};

// 파서가 실제로 찾은 구문 오류 하나(#408) — 어느 파일 몇 번째 줄에서 무슨
// 오류인지.
export type SyntaxCheckFinding = {
  path: string;
  line: number | null;
  message: string;
};

// 문법 검사 기본 항목의 판정 하나(#408, CONTEXT.md 「문법 검사」).
export type SyntaxCheckVerdict = {
  is_met: boolean;
  reasoning: string;
  // "parser" | "ai" — 파서가 판정했는지 AI가 판정했는지(#409).
  judged_by: "parser" | "ai";
  findings: SyntaxCheckFinding[];
};

export type ClassroomScore = {
  model_version: string;
  reasoning: ChecklistVerdict[];
  // 채점 시점에 그 문제의 기본 항목이 꺼져 있었으면 `null`이다(#408).
  syntax_check: SyntaxCheckVerdict | null;
  created_at: string;
};

// "pending"(아직 채점되지 않았다) 또는 "scored"(채점이 끝났다) — 화면이
// 「채점 중」을 구별하는 유일한 근거다(#287).
export type SubmissionStatus = "pending" | "scored";

// "no_api_key"(#346) | "model_rejected"(#403) | `null`. `status`가 "pending"일 때만
// 채워진다 — 강사가 채점 키를 아직 넣지 않았으면 "no_api_key", 키는 있는데 이 문제의
// 채점 모델을 그 키로 못 쓰면 "model_rejected"다(#629 로 사유가 둘이 됐다).
export type PendingReason = "no_api_key" | "model_rejected" | null;

export type ClassroomSubmissionRow = {
  id: number;
  problem_id: number;
  attempt_number: number;
  submission_format: SubmissionFormat;
  value: string;
  // 소스 제출에만 채워진다 — 저장소는 value 자체가 이미 열어 볼 수 있는 URL이다.
  download_url: string | null;
  created_at: string;
  status: SubmissionStatus;
  score: ClassroomScore | null;
  // 이 시도 하나가 통과인가(#288) — 미채점("pending")이면 항상 거짓이다.
  passed: boolean;
  pending_reason: PendingReason;
  // 「공모전에도 내기」로 낸 시도면 그 결과(#549), 끄고 낸 시도면 null.
  contest_entry: AttemptContestEntry | null;
};

export type AttemptContestEntry = {
  status: "pending" | "entered" | "rejected";
  // 공모전이 받지 않았을 때 그 이유.
  reason: string;
};

// 참여자가 지금 새로 낼 수 없는 이유 하나, 낼 수 있으면 `null`(#439). 우선순위는
// 보관 → 내보냄 → 숨김이고, "viewing_as_instructor"(강사가 학생 화면으로 보는
// 중)는 그 셋과 겹치지 않는 별도 판정이다. 백엔드가 이미 우선순위를 정해
// 하나만 내려주므로 화면은 이 값을 다시 계산하지 않는다
// (`classroom.participation.participant_submit_blocked_reason`).
export type SubmitBlockedReason = "archived" | "expelled" | "hidden" | "viewing_as_instructor" | null;

export type ProblemSubmissions = {
  // 화면 눈썹이 말할 클래스 이름(#372 후속).
  class_name: string;
  problem: ProblemMine;
  submissions: ClassroomSubmissionRow[];
  submit_blocked_reason: SubmitBlockedReason;
  // 강사가 볼 때만 채워지는 문제 상태 — 띠가 몇 줄을 더 말할지 이 값으로
  // 정한다. 참여자 시점에는 언제나 null이다.
  instructor_problem_status: "draft" | "open" | "hidden" | null;
  // 이 화면을 그 클래스의 강사가 열었는가(2026-09-17). 예전에는
  // `submit_blocked_reason === "viewing_as_instructor"` 하나가 「강사가 보는
  // 중」과 「그래서 못 낸다」를 함께 뜻했는데, 열린 문제에는 강사도 낼 수
  // 있게 되면서 둘이 갈렸다 — 띠는 이 값으로, 제출 잠금은
  // `submit_blocked_reason`으로 정한다.
  viewing_as_instructor: boolean;
};

// 참여자 본인이 그 클래스에서 불릴 이름을 스스로 바꾼다(#372) — 강사는 이
// 엔드포인트에 닿지 못한다, 항상 요청자 자신의 행만 바뀐다.
export function renameMyself(
  classId: number,
  displayName: string,
): Promise<ApiResult<{ display_name: string }>> {
  return apiRequest<{ display_name: string }>(
    `/api/backend/classroom/classes/${classId}/members/me`,
    "PATCH",
    { display_name: displayName },
  );
}

export function submitAttempt(
  classId: number,
  problemId: number,
  // 이 시도에서 고른 형식(#373) — 문제가 형식을 하나만 열어 뒀어도 화면이
  // 그 값을 그대로 싣는다, 서버는 문제의 허용 목록 밖이면 거절한다.
  input: {
    submission_format: SubmissionFormat;
    value: string;
    content_type?: string | null;
    // 공모전 문제에서 「공모전에도 내기」를 켰을 때만(#549).
    contest_entry?: ContestEntryInput | null;
  },
): Promise<ApiResult<ClassroomSubmissionRow>> {
  return bffClient.post<ClassroomSubmissionRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`,
    input,
  );
}

// 강사가 보는 시도 하나(#291) — 참여자용 `ClassroomSubmissionRow`와 같은 모양에
// 어느 참여자의 것인지(`member_id`·`member_display_name`)가 더 실린다. 강사는
// 자기 시도가 아니라 클래스 전체를 훑어보기 때문이다.
export type InstructorSubmissionRow = {
  id: number;
  problem_id: number;
  member_id: number;
  member_display_name: string;
  attempt_number: number;
  submission_format: SubmissionFormat;
  value: string;
  download_url: string | null;
  created_at: string;
  status: SubmissionStatus;
  score: ClassroomScore | null;
  passed: boolean;
  // 참여자용 `ClassroomSubmissionRow.pending_reason`과 같은 값·같은 이유
  // (#346) — 강사도 "학생이 안 낸 것"과 "냈는데 강사 본인이 키를 안 넣어
  // 멈춘 것"을 구별해야 한다.
  pending_reason: PendingReason;
  // 「공모전에도 내기」로 낸 시도면 그 결과(#550). 근거·공모전 점수·수상은 없다.
  contest_entry: AttemptContestEntry | null;
  // 이 시도가 지금 그 공모전의 제출인가 — 켜고 낸 가장 최근 시도이고 그 뒤에 직접 고치지 않았다.
  is_current_contest_entry: boolean;
};


// 참여자의 「공모전에도 내기」 칸(#549) — 직전 공모전 제출로 미리 채운 값이 실린다.
export function fetchContestEntryForm(
  classId: number,
  problemId: number,
): Promise<ApiResult<ContestEntryForm>> {
  return bffClient.get<ContestEntryForm>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/contest-entry`,
  );
}
