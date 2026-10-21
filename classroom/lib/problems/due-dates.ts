// 문제의 권장 기한·마감(#769/#770, ADR-0063) — 화면이 나눠 쓰는 표기 조각과 편집 칸의 변환.
//
// 표기 규칙(시안 `docs/design/classroom-deadline/`): 권장은 흐리게(dim) · 마감은 보통 글자 ·
// **지난 마감이 붉은(attention) 것은 참여자가 아직 통과하지 못한 문제뿐**이다. 통과한 문제의
// 기한은 전부 더 흐리고(faint), 강사 화면(참여자가 없다)의 지난 마감도 흐리다 — 강사에게는
// 경고가 아니다. 표·격자·목록·제출 카드가 이 하나를 쓴다.
//
// 시각은 브라우저 로컬이다 — 강의실의 `formatDateTime`·`relative-time.ts` 와 같은 방식.
// 편집 칸은 날짜 칸 + 시각 칸이고, 보낼 때 로컬 → ISO 8601(오프셋 포함)로 바꾼다.
import { formatDay } from "../classes/format-day";

export type DueFields = { recommended_due_at: string | null; due_at: string | null };

export type DueTone = "normal" | "dim" | "faint" | "attention";

export type DueMark = {
  label: string;
  // 「M/D」
  text: string;
  tone: DueTone;
  // 지금이 그 시각을 지났는가.
  passed: boolean;
};

export type DueDescription = { recommended: DueMark | null; due: DueMark | null };

export function formatDueDay(iso: string): string {
  return formatDay(iso);
}

const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
const two = (n: number) => String(n).padStart(2, "0");

/** 제출 카드의 「10/27 (화) 23:59」. */
export function formatDueDateTime(iso: string): string {
  const d = new Date(iso);
  return `${formatDay(iso)} (${WEEKDAY[d.getDay()]}) ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/**
 * `passed` — 참여자 화면이면 그 참여자가 이 문제를 통과했는가, 강사 화면(표·격자)이면 null.
 */
export function describeDue(
  problem: DueFields,
  { passed, now = Date.now() }: { passed: boolean | null; now?: number },
): DueDescription {
  const done = passed === true;
  let recommended: DueMark | null = null;
  if (problem.recommended_due_at) {
    const behind = Date.parse(problem.recommended_due_at) < now;
    recommended = {
      label: "권장",
      text: formatDay(problem.recommended_due_at),
      tone: done || behind ? "faint" : "dim",
      passed: behind,
    };
  }
  let due: DueMark | null = null;
  if (problem.due_at) {
    const behind = Date.parse(problem.due_at) < now;
    const attention = behind && passed === false;
    due = {
      label: attention ? "마감 지남" : "마감",
      text: formatDay(problem.due_at),
      tone: attention ? "attention" : done || behind ? "faint" : "normal",
      passed: behind,
    };
  }
  return { recommended, due };
}

/** 「통과 · 늦음」 — 「늦음」은 별도 칩이 아니라 상태 배지 글자다. */
export function withLate(label: string, late: boolean): string {
  return late ? `${label} · 늦음` : label;
}

// ── 편집 칸 ───────────────────────────────────────────────────────────────

export type DueDraft = { date: string; time: string };

export const EMPTY_DUE_DRAFT: DueDraft = { date: "", time: "" };
const DEFAULT_TIME = "23:59";

export function dueDraftFromIso(iso: string | null): DueDraft {
  if (!iso) return EMPTY_DUE_DRAFT;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EMPTY_DUE_DRAFT;
  return {
    date: `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`,
    time: `${two(d.getHours())}:${two(d.getMinutes())}`,
  };
}

function draftToDate(draft: DueDraft): Date | null {
  if (!draft.date) return null;
  const [y, m, d] = draft.date.split("-").map(Number);
  const [h, mi] = (draft.time || DEFAULT_TIME).split(":").map(Number);
  const date = new Date(y, m - 1, d, h, mi);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** 로컬 → 「2026-10-27T23:59:00+09:00」. 날짜가 비어 있으면 null(= 비움). */
export function dueDraftToIso(draft: DueDraft): string | null {
  const date = draftToDate(draft);
  if (!date) return null;
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return (
    `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}` +
    `T${two(date.getHours())}:${two(date.getMinutes())}:00${sign}${two(Math.floor(abs / 60))}:${two(abs % 60)}`
  );
}

/** 날짜를 고르면 시각은 23:59 로 채워지고(이미 있으면 그대로), 날짜를 비우면 시각도 비운다. */
export function pickDueDate(draft: DueDraft, date: string): DueDraft {
  if (!date) return EMPTY_DUE_DRAFT;
  return { date, time: draft.time || DEFAULT_TIME };
}

/** 둘 다 있을 때 권장이 마감보다 늦으면 참 — 같은 시각은 허용(서버 422 와 같은 규칙). */
export function dueOrderViolated(recommended: DueDraft, due: DueDraft): boolean {
  const r = draftToDate(recommended);
  const d = draftToDate(due);
  if (!r || !d) return false;
  return r.getTime() > d.getTime();
}

/** 서버가 순서 위반에 주는 문구 — 422 를 받으면 칸을 붉게 두는 데 쓴다. */
export const DUE_ORDER_MESSAGE = "권장 기한은 마감보다 늦을 수 없습니다.";
