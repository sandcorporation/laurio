"use client";

// 가산 항목 하나의 강사 점수 입력(#905, ADR-0073) — 0~5 와 한 줄 메모, 저장. 덮어쓰기다.
import { useState } from "react";

import { ErrorNote, INPUT_CLASS, buttonClass } from "@/app/components/ui";

// INPUT_CLASS 의 w-full 이 한 줄 배치를 깨므로 뺀다 — 점수·메모·저장이 한 줄에 선다.
const INLINE_INPUT_CLASS = INPUT_CLASS.replace("w-full ", "");

export const BONUS_SCORE_OPTIONS = [0, 1, 2, 3, 4, 5] as const;
export const BONUS_MEMO_MAX_LENGTH = 200;

export function BonusScoreEditor({
  testId,
  label,
  initialScore,
  initialMemo,
  disabled = false,
  onSave,
}: {
  testId: string;
  label: string;
  initialScore: number;
  initialMemo: string;
  disabled?: boolean;
  /** 실패하면 보일 문구, 성공하면 null. */
  onSave: (score: number, memo: string) => Promise<string | null>;
}) {
  const [score, setScore] = useState(initialScore);
  const [memo, setMemo] = useState(initialMemo);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    const message = await onSave(score, memo.trim());
    setSaving(false);
    setError(message);
  };

  return (
    <div data-testid={testId} className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <select
          data-testid={`${testId}-score`}
          aria-label={`${label} 가산 점수`}
          value={score}
          disabled={disabled || saving}
          onChange={(event) => setScore(Number(event.target.value))}
          className={`${INLINE_INPUT_CLASS} w-[72px] shrink-0`}
        >
          {BONUS_SCORE_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value}/5
            </option>
          ))}
        </select>
        <input
          data-testid={`${testId}-memo`}
          aria-label={`${label} 메모`}
          value={memo}
          maxLength={BONUS_MEMO_MAX_LENGTH}
          disabled={disabled || saving}
          onChange={(event) => setMemo(event.target.value)}
          placeholder="메모"
          className={`${INLINE_INPUT_CLASS} min-w-[160px] flex-1`}
        />
        <button
          type="button"
          data-testid={`${testId}-save`}
          disabled={disabled || saving}
          onClick={() => void save()}
          className={buttonClass("primary", "sm")}
        >
          저장
        </button>
      </div>
      {error ? <ErrorNote>{error}</ErrorNote> : null}
    </div>
  );
}
