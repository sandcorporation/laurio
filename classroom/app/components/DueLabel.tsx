// 권장 기한·마감 표기 조각(#770) — 표·격자·목록·제출 카드가 나눠 쓴다. 판단은 `lib/problems/due-dates.ts`
// 의 `describeDue` 하나이고, 여기는 그 결과를 자리마다 다른 모양(한 줄·고정 폭 두 칸·라벨/값 두 줄)으로 그린다.
// 붉은 글자는 참여자가 아직 통과하지 못한 문제의 지난 마감뿐이다.
import { describeDue, formatDueDateTime, type DueFields, type DueMark, type DueTone } from "@/lib/problems/due-dates";

const TONE_CLASS: Record<DueTone, string> = {
  normal: "text-ink",
  dim: "text-ink/60",
  faint: "text-ink/35",
  attention: "text-warning",
};

function Mark({ mark, testId }: { mark: DueMark; testId: string }) {
  return (
    <span data-testid={testId} data-tone={mark.tone} className={`whitespace-nowrap ${TONE_CLASS[mark.tone]}`}>
      {mark.label} <span className="font-mono">{mark.text}</span>
    </span>
  );
}

/** 강사 문제 표 — 제목 옆 한 줄 「마감 10/27」만. 권장은 표에 없다. 지난 마감은 흐리다(붉지 않다). */
export function DueInline({ problem, testId }: { problem: DueFields; testId: string }) {
  const { due } = describeDue(problem, { passed: null });
  if (!due) return null;
  return (
    <span className="ml-2.5 text-[11.5px]">
      <Mark mark={due} testId={testId} />
    </span>
  );
}

/** 참여자 문제 목록 — 권장 100px · 마감 150px 고정 폭, 왼쪽 정렬. 앞뒤 글자 길이와 무관하게 같은 x 에 선다.
 *  좁은 폭(<sm)에서는 칸 폭을 풀고 행(`flex-wrap`) 맨 아래 한 줄로 내려 제목 아래에 선다(#1440) — 표시할 기한이 없으면 줄도 없다. */
export function DueCells({
  problem,
  passed,
  testId,
  archived = false,
}: {
  problem: DueFields;
  passed: boolean;
  testId: string;
  /** 보관된 클래스 — 재촉하는 표시(「곧 마감」·붉은 「마감 지남」)를 끈다(#1507 B). */
  archived?: boolean;
}) {
  const { recommended, due } = describeDue(problem, { passed, archived });
  return (
    <span
      data-testid={`${testId}-due-line`}
      className={`flex shrink-0 text-[12.5px] max-sm:order-last max-sm:basis-full max-sm:gap-3 ${
        recommended || due ? "" : "max-sm:hidden"
      }`}
    >
      <span className="inline-block w-[100px] max-sm:w-auto max-sm:empty:hidden">
        {recommended ? <Mark mark={recommended} testId={`${testId}-recommended`} /> : null}
      </span>
      <span className="inline-block w-[150px] max-sm:w-auto max-sm:empty:hidden">
        {due ? <Mark mark={due} testId={`${testId}-due`} /> : null}
      </span>
    </span>
  );
}

/** 제출 카드 머리 아래 — 라벨 왼쪽, 값 오른쪽(요일 포함). 권장이 지났으면 그 줄이 흐려진다. */
export function DueRows({
  problem,
  passed,
  testId,
  archived = false,
}: {
  problem: DueFields;
  passed: boolean;
  testId: string;
  /** 보관된 클래스 — 재촉하는 표시를 끈다(#1507 A). */
  archived?: boolean;
}) {
  const { recommended, due } = describeDue(problem, { passed, archived });
  if (!recommended && !due) return null;
  const row = (label: string, iso: string, tone: DueTone, id: string) => (
    <div data-testid={id} data-tone={tone} className={`flex justify-between gap-3 ${TONE_CLASS[tone]}`}>
      <span>{label}</span>
      <span className="font-mono">{formatDueDateTime(iso)}</span>
    </div>
  );
  return (
    <div data-testid={testId} className="flex flex-col gap-1 border-b border-rule px-4 py-2.5 text-[12.5px]">
      {recommended && problem.recommended_due_at
        ? row("권장 기한", problem.recommended_due_at, recommended.tone === "dim" ? "normal" : recommended.tone, `${testId}-recommended`)
        : null}
      {due && problem.due_at ? row(due.label, problem.due_at, due.tone, `${testId}-due`) : null}
    </div>
  );
}
