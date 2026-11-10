"use client";

// 문제 편집 오른쪽 열의 「기한」 카드(#770) — 권장 기한·마감 각각 날짜 칸 + 시각 칸, 「비우기」.
// 날짜를 고르면 시각은 23:59 로 채워지고 바꿀 수 있다(`pickDueDate`). 저장은 머리의 「저장」이
// 한다 — 이 카드는 값을 들고 있지 않고 부모의 초안(`DueDraft`)을 비춘다. 둘 다 있을 때 권장이
// 마감 뒤면 부모가 `invalid` 를 주고 두 칸이 붉어진다(서버 422 도 같은 표시).
import { Card, CardHeader } from "@/app/components/ui";
import { EMPTY_DUE_DRAFT, pickDueDate, type DueDraft } from "@/lib/problems/due-dates";

function DueField({
  label,
  testId,
  value,
  onChange,
  invalid,
  disabled,
}: {
  label: string;
  testId: string;
  value: DueDraft;
  onChange: (next: DueDraft) => void;
  invalid: boolean;
  disabled: boolean;
}) {
  const field =
    `border bg-surface px-2.5 py-1.5 font-mono text-[13px] text-ink focus:border-ink focus:outline-none ` +
    `disabled:cursor-not-allowed disabled:bg-paper disabled:text-ink/60 ${invalid ? "border-attention" : "border-rule"}`;
  return (
    <div data-testid={testId} className="flex flex-col gap-1.5 px-4 py-2.5">
      <div className="flex items-center text-[12px] text-ink/60">
        <span>{label}</span>
        {value.date ? (
          <button
            type="button"
            data-testid={`${testId}-clear`}
            disabled={disabled}
            onClick={() => onChange(EMPTY_DUE_DRAFT)}
            className="ml-auto text-[11.5px] text-ink/45 underline underline-offset-[3px] hover:text-ink disabled:opacity-50"
          >
            비우기
          </button>
        ) : null}
      </div>
      <div className="flex gap-1.5">
        <input
          type="date"
          data-testid={`${testId}-date`}
          aria-label={`${label} 날짜`}
          aria-invalid={invalid || undefined}
          value={value.date}
          disabled={disabled}
          onChange={(event) => onChange(pickDueDate(value, event.target.value))}
          className={`${field} w-[150px]`}
        />
        <input
          type="time"
          data-testid={`${testId}-time`}
          aria-label={`${label} 시각`}
          aria-invalid={invalid || undefined}
          value={value.time}
          disabled={disabled || !value.date}
          onChange={(event) => onChange({ ...value, time: event.target.value })}
          className={`${field} w-[104px]`}
        />
      </div>
    </div>
  );
}

export function ProblemDueCard({
  testIdPrefix,
  recommended,
  due,
  onRecommendedChange,
  onDueChange,
  invalid,
  disabled = false,
}: {
  testIdPrefix: string;
  recommended: DueDraft;
  due: DueDraft;
  onRecommendedChange: (next: DueDraft) => void;
  onDueChange: (next: DueDraft) => void;
  invalid: boolean;
  disabled?: boolean;
}) {
  return (
    <Card>
      <CardHeader title="기한" />
      <div className="divide-y divide-rule py-1">
        <DueField
          label="권장 기한"
          testId={`${testIdPrefix}-recommended-due`}
          value={recommended}
          onChange={onRecommendedChange}
          invalid={invalid}
          disabled={disabled}
        />
        <DueField label="마감" testId={`${testIdPrefix}-due`} value={due} onChange={onDueChange} invalid={invalid} disabled={disabled} />
      </div>
      <p className="px-4 pb-4 text-[12px] leading-relaxed text-ink/60">
        마감이 지나도 제출할 수 있고, 그 뒤 제출은 「마감 기한 뒤 제출」로 표시됩니다.
      </p>
    </Card>
  );
}
