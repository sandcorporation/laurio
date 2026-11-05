// 시도 하나의 항목별 판정 — 문법 검사 기본 항목과 체크리스트 항목마다 충족 여부와 AI 의 사유 (#638).
// 강사의 제출 현황이 「판정」을 펼칠 때 쓰고, 참여자 제출 화면(#640)도 같은 컴포넌트를 쓴다.
// testid 는 `${testIdPrefix}-verdicts` · `-syntax-check` · `-syntax-check-finding-n`.
import { Badge } from "@/app/components/ui";
import type { ClassroomScore } from "@/lib/submissions/api";
import { VERDICT_LABEL, verdictMarkerClass, verdictOf } from "@/lib/submissions/verdict";

// 판정 주체 표시(#409) — 파서 판정은 신뢰도가 높고(파이썬 표준 파서·tree-sitter), AI 판정은 파서가 없는
// 언어이거나 크기·시간 제한에 걸렸을 때만 쓰인다.
export function judgedByLabel(judgedBy: "parser" | "ai"): string {
  return judgedBy === "parser" ? "파서 판정" : "AI 판정";
}

export function SubmissionVerdictList({
  score,
  checklistLabelById,
  testIdPrefix,
}: {
  score: ClassroomScore;
  checklistLabelById: ReadonlyMap<number, string>;
  testIdPrefix: string;
}) {
  return (
    <ul data-testid={`${testIdPrefix}-verdicts`} className="flex flex-col gap-2">
      {score.syntax_check ? (
        <li data-testid={`${testIdPrefix}-syntax-check`} className="flex gap-2.5">
          <span
            aria-hidden
            className={`mt-1 h-[13px] w-[13px] shrink-0 border ${
              score.syntax_check.is_met ? "border-verified bg-verified" : "border-attention"
            }`}
          />
          <span className="text-[13px] leading-relaxed">
            <Badge>기본</Badge> <Badge tone="neutral">{judgedByLabel(score.syntax_check.judged_by)}</Badge>{" "}
            소스에 문법 오류가 없다
            <span className="text-ink/45"> — {score.syntax_check.is_met ? "충족" : "미충족"}</span>
            <span className="block text-ink/60">{score.syntax_check.reasoning}</span>
            {score.syntax_check.findings.map((finding, index) => (
              <span
                key={index}
                data-testid={`${testIdPrefix}-syntax-check-finding-${index}`}
                className="block font-mono text-[12px] text-ink/60"
              >
                {finding.path}
                {finding.line !== null ? `:${finding.line}` : ""} — {finding.message}
              </span>
            ))}
          </span>
        </li>
      ) : null}
      {score.reasoning.map((verdict) => {
        const value = verdictOf(verdict);
        return (
          <li key={verdict.checklist_item_id} className="flex gap-2.5">
            <span aria-hidden className={`mt-1 h-[13px] w-[13px] shrink-0 border ${verdictMarkerClass(value)}`} />
            <span className="text-[13px] leading-relaxed">
              <span className={verdict.is_met ? "" : "text-ink"}>
                {checklistLabelById.get(verdict.checklist_item_id) ?? "항목"}
              </span>{" "}
              <span className="text-ink/45">— {VERDICT_LABEL[value]}</span>
              <span className="block text-ink/60">{verdict.reasoning}</span>
            </span>
          </li>
        );
      })}
      {score.hidden_summary && score.hidden_summary.total > 0 ? (
        <li data-testid={`${testIdPrefix}-hidden-summary`} className="text-[13px] leading-relaxed">
          숨은 항목 {score.hidden_summary.total}개 중 {score.hidden_summary.met}개 충족
        </li>
      ) : null}
    </ul>
  );
}
