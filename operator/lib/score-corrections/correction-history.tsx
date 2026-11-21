import { Badge } from "@/app/components/badge";
import { TableScroll } from "@/app/components/table-scroll";

import { correctionStatusLabel } from "./status-label";
import type { ScoreCorrection, ScoredSubmission } from "./types";

const COL = {
  submission: "w-[200px]",
  status: "w-[84px]",
  score: "w-[132px]",
  certificates: "w-[110px]",
  created: "w-[236px]",
};

function toneOf(status: string) {
  if (status === "failed") return "attention" as const;
  if (status === "done") return "pass" as const;
  return "neutral" as const;
}

export function CorrectionHistory({
  corrections,
  submissions,
}: {
  corrections: ScoreCorrection[];
  submissions: ScoredSubmission[];
}) {
  const names = new Map(submissions.map((s) => [s.submission_id, s.participant]));
  return (
    <div data-testid="correction-history" className="border border-rule bg-surface">
      <TableScroll minWidth={1100}>
        <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
          <div className={`${COL.submission} shrink-0`}>제출</div>
          <div className={`${COL.status} shrink-0`}>상태</div>
          <div className={`${COL.score} shrink-0`}>점수</div>
          <div className={`${COL.certificates} shrink-0`}>발급된 상장</div>
          <div className={`${COL.created} shrink-0`}>건 때</div>
          <div className="min-w-0 flex-1">사유</div>
        </div>
        {corrections.map((c, i) => (
          <div
            key={c.id}
            data-testid={`correction-row-${c.id}`}
            className={`flex items-start gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
              i % 2 === 1 ? "bg-ink/[2%]" : ""
            }`}
          >
            <div className={`${COL.submission} shrink-0 truncate`}>
              #{c.submission_id} {names.get(c.submission_id) ?? ""}
            </div>
            <div className={`${COL.status} shrink-0`}>
              <Badge testId={`correction-status-${c.id}`} tone={toneOf(c.status)}>
                {correctionStatusLabel(c.status)}
              </Badge>
            </div>
            <div
              data-testid={`correction-score-${c.id}`}
              className={`${COL.score} shrink-0 whitespace-nowrap font-mono text-[12.5px]`}
            >
              {c.original_percentage}% → {c.percentage === null ? "-" : `${c.percentage}%`}
            </div>
            <div data-testid={`correction-certificates-${c.id}`} className={`${COL.certificates} shrink-0`}>
              {c.certificates_issued > 0 ? `${c.certificates_issued}장` : "-"}
            </div>
            <div className={`${COL.created} shrink-0 whitespace-nowrap font-mono text-[12.5px] text-ink/62`}>
              {new Date(c.created_at).toLocaleString("ko-KR")}
            </div>
            <div className="min-w-0 flex-1 break-words">
              {c.reason}
              {c.error && (
                <span data-testid={`correction-error-${c.id}`} className="block text-[12px] text-attention">
                  {c.error}
                </span>
              )}
            </div>
          </div>
        ))}
      </TableScroll>
    </div>
  );
}
