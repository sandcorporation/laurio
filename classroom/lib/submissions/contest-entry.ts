// 「공모전에도 내기」(#549, CONTEXT.md) — 공모전 문제의 시도를 그 공모전에도 낸다. 칸은
// 공모전에 직접 낼 때와 같다: 요구사항마다 자가 응답·근거, 소스 열람 동의, 선택 자료.
// 직전에 공모전에 낸 것이 있으면 미리 채운다(요구사항이 그사이 새로 생겼으면 그 줄만 빈칸).
// 순수 함수만 둔다 — 단위 시험이 이 파일을 그대로 읽는다. 요청은 `api.ts` 에 있다.
export type EntryEvidence = { kind: string; value: string };

export type EntryRequirement = {
  requirement_id: number;
  text: string;
  required: boolean;
  previous: { is_met: boolean; note: string; evidence: EntryEvidence[] } | null;
};

export type EntryAsset = { kind: string; value: string; label: string; content_type: string };

export type ContestEntryForm = {
  contest_id: number;
  accepts_entries: boolean;
  deadline_at: string | null;
  has_entry: boolean;
  requirements: EntryRequirement[];
  optional_assets: EntryAsset[];
  upload_target_refs: Record<string, string>;
};

export type ContestEntryInput = {
  source_access_consent: boolean;
  replace_existing: boolean;
  requirement_responses: {
    requirement_id: number;
    is_met: boolean;
    note: string;
    evidence: EntryEvidence[];
  }[];
  optional_assets: EntryAsset[];
};

// 근거 종류 — 공모전 직접 제출 화면과 같은 넷(백엔드 `Evidence.Kind`).
export const EVIDENCE_KINDS: { value: string; label: string }[] = [
  { value: "video_timestamp", label: "영상 타임스탬프" },
  { value: "screenshot", label: "스크린샷" },
  { value: "demo_path", label: "데모 내 경로" },
  { value: "source_location", label: "소스 위치" },
];

export const OPTIONAL_ASSET_LABELS: Record<string, string> = {
  demo_url: "데모 주소",
  demo_video: "시연 영상",
  screenshot: "스크린샷",
};

export type EntryResponseState = { isMet: boolean; note: string; evidence: EntryEvidence[] };

export type ContestEntryState = {
  on: boolean;
  consent: boolean;
  replaceConfirmed: boolean;
  responses: Record<number, EntryResponseState>;
  optionalAssets: EntryAsset[];
};

/** 칸의 첫 상태 — 직전 공모전 제출로 미리 채운다. 스위치와 동의·바꾸기 확인은 언제나 꺼진
 *  채로 시작한다: 시도마다 참여자가 직접 고른다. */
/** 「공모전에도 내기」 칸을 여는가 — 공모전이 지금 받는 공모전 문제면 참여자도 강사도 연다(#878).
 *  강사가 학생 화면으로 보는 중(`viewing_as_instructor`)이어도 시도는 강사 본인 것이라 닫지 않는다. */
export function offersContestEntry(problem: { contest?: { accepts_entries?: boolean } | null }): boolean {
  return problem.contest?.accepts_entries === true;
}

export function initialEntryState(form: ContestEntryForm): ContestEntryState {
  const responses: Record<number, EntryResponseState> = {};
  for (const requirement of form.requirements) {
    const previous = requirement.previous;
    responses[requirement.requirement_id] = previous
      ? { isMet: previous.is_met, note: previous.note, evidence: previous.evidence.map((e) => ({ ...e })) }
      : { isMet: false, note: "", evidence: [] };
  }
  return {
    on: false,
    consent: false,
    replaceConfirmed: false,
    responses,
    optionalAssets: form.optional_assets.map((asset) => ({ ...asset })),
  };
}

/** 근거가 하나도 없는 필수 요구사항 — 그대로 내면 공모전에서 미달로 채점된다(막지는 않는다). */
export function requiredWithoutEvidence(form: ContestEntryForm, state: ContestEntryState): EntryRequirement[] {
  return form.requirements.filter(
    (requirement) =>
      requirement.required && (state.responses[requirement.requirement_id]?.evidence ?? []).length === 0,
  );
}

/** 낼 수 있는가 — 동의는 필수, 이미 낸 제출이 있으면 바꾸기 확인도 필수다. */
export function entryBlockedReason(form: ContestEntryForm, state: ContestEntryState): string | null {
  if (!state.consent) return "소스 열람에 동의해야 공모전에도 낼 수 있습니다.";
  if (form.has_entry && !state.replaceConfirmed) return "이미 낸 공모전 제출이 이 시도로 바뀐다는 것을 확인해 주세요.";
  return null;
}

/** 요청에 싣는 모양. 스위치가 꺼져 있으면 null — 공모전 제출을 건드리지 않는다. */
export function buildEntryPayload(form: ContestEntryForm, state: ContestEntryState): ContestEntryInput | null {
  if (!state.on) return null;
  return {
    source_access_consent: state.consent,
    replace_existing: form.has_entry && state.replaceConfirmed,
    requirement_responses: form.requirements.map((requirement) => {
      const response = state.responses[requirement.requirement_id] ?? { isMet: false, note: "", evidence: [] };
      return {
        requirement_id: requirement.requirement_id,
        is_met: response.isMet,
        note: response.note.trim(),
        evidence: response.evidence
          .map((e) => ({ kind: e.kind, value: e.value.trim() }))
          .filter((e) => e.value !== ""),
      };
    }),
    optional_assets: state.optionalAssets.filter((asset) => asset.value.trim() !== ""),
  };
}

/** 시도 한 줄에 붙는 결과 문구. */
export function attemptEntryLabel(entry: { status: string; reason: string }): string {
  if (entry.status === "entered") return "공모전에도 냈습니다";
  if (entry.status === "pending") return "공모전에 내는 중";
  return entry.reason ? `공모전에는 내지 못했습니다 — ${entry.reason}` : "공모전에는 내지 못했습니다";
}

// --- 강사가 보는 표시 (#550) ---------------------------------------------------
// 강사에게는 「냈는지와 어느 시도인지」만 보인다 — 근거·공모전 점수·수상은 공모전 쪽의 것이다.

export type InstructorEntryBadge = { label: string; tone: "verified" | "neutral" | "attention" };

/** 제출 현황의 시도 한 줄에 다는 표시. 공모전에 내지 않은 시도면 null. */
export function instructorEntryBadge(row: {
  contest_entry: { status: string } | null;
  is_current_contest_entry: boolean;
}): InstructorEntryBadge | null {
  if (row.contest_entry === null) return null;
  if (row.is_current_contest_entry) return { label: "지금 공모전 제출", tone: "verified" };
  if (row.contest_entry.status === "entered") return { label: "공모전에도 냈음", tone: "neutral" };
  if (row.contest_entry.status === "pending") return { label: "공모전에 내는 중", tone: "neutral" };
  return { label: "공모전에는 못 냄", tone: "attention" };
}

export type GridContestEntry = "current" | "entered" | null;

/** 명단 격자 한 칸의 공모전 표시 문구 — 칸의 title·aria-label 에 덧붙인다. */
export function gridEntryLabel(entry: GridContestEntry): string | null {
  if (entry === "current") return "지금 공모전 제출인 시도가 있음";
  if (entry === "entered") return "공모전에도 냈었음(지금 제출은 다른 시도)";
  return null;
}
