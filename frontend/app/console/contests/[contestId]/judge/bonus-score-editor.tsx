"use client";

// 가산 항목 하나의 개최자 점수 입력(#905, ADR-0073) — 마감 뒤 심사 화면에서 제출작마다 0~5 와 한 줄 메모. 덮어쓰기다.
import { useState } from "react";

import { ErrorNote, buttonClass } from "@/app/components/ui";

const BONUS_SCORE_OPTIONS = [0, 1, 2, 3, 4, 5] as const;
const BONUS_MEMO_MAX_LENGTH = 200;
const FIELD_CLASS = "border border-rule bg-surface px-1.5 py-1 text-xs text-ink";

export function BonusScoreEditor({
  testId,
  initialScore,
  initialMemo,
  onSave,
}: {
  testId: string;
  initialScore: number;
  initialMemo: string;
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
      <div className="flex items-center gap-1.5">
        <select
          aria-label="가산 점수"
          data-testid={`${testId}-score`}
          value={score}
          disabled={saving}
          onChange={(event) => setScore(Number(event.target.value))}
          className={`${FIELD_CLASS} font-mono`}
        >
          {BONUS_SCORE_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value}/5
            </option>
          ))}
        </select>
        <button
          type="button"
          data-testid={`${testId}-save`}
          disabled={saving}
          onClick={() => void save()}
          className={buttonClass("primary", "sm")}
        >
          저장
        </button>
      </div>
      <input
        aria-label="가산 메모"
        data-testid={`${testId}-memo`}
        value={memo}
        maxLength={BONUS_MEMO_MAX_LENGTH}
        disabled={saving}
        onChange={(event) => setMemo(event.target.value)}
        placeholder="메모"
        className={`${FIELD_CLASS} w-full min-w-0`}
      />
      {error ? <ErrorNote>{error}</ErrorNote> : null}
    </div>
  );
}
