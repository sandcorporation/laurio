"use client";

import { useState } from "react";

import { TableScroll } from "@/app/components/table-scroll";

import { requestScoreCorrections } from "./actions";
import type { ScoredSubmission } from "./types";

const SKIP_LABELS: Record<string, string> = {
  not_scored: "아직 채점되지 않았습니다",
  in_progress: "이미 정정이 진행 중입니다",
};

export function CorrectionForm({
  contestId,
  submissions,
  prizeSettled,
  onRequested,
}: {
  contestId: string;
  submissions: ScoredSubmission[];
  prizeSettled: boolean;
  onRequested: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);

  const canSubmit = reason.trim().length > 0 && selected.size > 0 && !sending;

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    setSending(true);
    setError(null);
    setSkipped([]);
    const result = await requestScoreCorrections(contestId, [...selected], reason.trim());
    setSending(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setSkipped(result.result.skipped.map((s) => `#${s.submission_id} ${SKIP_LABELS[s.reason] ?? s.reason}`));
    setSelected(new Set());
    setReason("");
    onRequested();
  }

  return (
    <div data-testid="correction-form" className="flex flex-col gap-3.5 border border-rule bg-surface p-4">
      <TableScroll minWidth={300}>
        <div className="flex gap-3.5 border-b border-rule px-1 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
          <div className="w-6 shrink-0" />
          <div className="min-w-0 flex-1">제출</div>
          <div className="w-[96px] shrink-0 text-right">원래 점수</div>
        </div>
        {submissions.map((s) => (
          <label
            key={s.submission_id}
            data-testid={`correction-target-${s.submission_id}`}
            className="flex cursor-pointer items-center gap-3.5 border-b border-rule px-1 py-2.5 text-[13px] last:border-b-0"
          >
            <input
              type="checkbox"
              data-testid={`correction-target-check-${s.submission_id}`}
              checked={selected.has(s.submission_id)}
              onChange={() => toggle(s.submission_id)}
              className="w-6 shrink-0"
            />
            <span className="min-w-0 flex-1 truncate">
              #{s.submission_id} {s.participant}
            </span>
            <span className="w-[96px] shrink-0 text-right font-mono text-[12.5px]">{s.original_percentage}%</span>
          </label>
        ))}
      </TableScroll>
      <label className="flex flex-col gap-1.5 text-[11.5px] text-ink/45">
        사유
        <textarea
          data-testid="correction-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={4000}
          className="min-h-20 border border-rule bg-paper p-2.5 text-[13px] text-ink"
        />
      </label>
      {prizeSettled && (
        <p data-testid="correction-settled-notice" className="text-[12.5px] font-medium text-attention">
          배분이 끝난 공모전이다 — 순위·돈은 바뀌지 않는다
        </p>
      )}
      <div>
        <button
          type="button"
          data-testid="correction-submit"
          disabled={!canSubmit}
          onClick={submit}
          className="bg-ink px-4 py-2 text-[13.5px] font-medium text-paper disabled:opacity-50"
        >
          정정 걸기
        </button>
      </div>
      {error && (
        <p role="alert" data-testid="correction-error" className="text-[12.5px] text-attention">
          {error}
        </p>
      )}
      {skipped.length > 0 && (
        <p data-testid="correction-skipped" className="text-[12.5px] text-ink/62">
          건너뜀 — {skipped.join(", ")}
        </p>
      )}
    </div>
  );
}
