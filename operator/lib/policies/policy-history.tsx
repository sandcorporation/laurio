"use client";

// 변경 이력 표(#77, #425 — 골간 표 조각으로 옮긴다) — 누가·언제·무엇을
// 무엇으로·왜. 일반 등급 Operator도 본다(조회는 등급을 가리지 않는다, #76).
// 고치거나 지우는 조작은 이 화면 어디에도 없다 — append-only(ADR-0023)라는
// 사실을 호출부(operator/app/policy/page.tsx)가 캡션으로 명시적으로 말한다.
import { POLICY_FIELD_LABELS } from "./types";
import type { PolicyChangeEntry, PolicyField } from "./types";

function formatDiff(change: PolicyChangeEntry): string {
  const fields = Object.keys(change.after) as PolicyField[];
  return fields
    .map((field) => {
      const label = POLICY_FIELD_LABELS[field];
      const before = change.before[field];
      const after = change.after[field];
      return `${label}: ${before} → ${after}`;
    })
    .join(", ");
}

const COL = {
  operator: "w-[110px]",
  changedAt: "w-[150px]",
  reason: "w-[220px]",
};

export function PolicyHistoryTable({ changes }: { changes: PolicyChangeEntry[] }) {
  if (changes.length === 0) {
    return (
      <p data-testid="policy-history-empty" className="text-[13px] text-ink/62">
        아직 변경 이력이 없습니다.
      </p>
    );
  }

  return (
    <div data-testid="policy-history-table" className="border border-rule bg-surface">
      <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
        <div className={COL.operator}>누가</div>
        <div className={COL.changedAt}>언제</div>
        <div className="min-w-0 flex-1">무엇을 무엇으로</div>
        <div className={COL.reason}>왜</div>
      </div>
      {changes.map((change, i) => (
        <div
          key={change.id}
          data-testid={`policy-history-row-${change.id}`}
          className={`flex gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
            i % 2 === 1 ? "bg-ink/[2%]" : ""
          }`}
        >
          <div
            className={`${COL.operator} shrink-0 truncate font-mono`}
            data-testid={`policy-history-row-${change.id}-operator`}
          >
            {change.operator_username}
          </div>
          <div
            className={`${COL.changedAt} shrink-0 truncate font-mono text-ink/62`}
            data-testid={`policy-history-row-${change.id}-changed-at`}
          >
            {new Date(change.changed_at).toLocaleString("ko-KR")}
          </div>
          <div className="min-w-0 flex-1 truncate" data-testid={`policy-history-row-${change.id}-diff`}>
            {formatDiff(change)}
          </div>
          <div
            className={`${COL.reason} shrink-0 truncate text-ink/62`}
            data-testid={`policy-history-row-${change.id}-reason`}
          >
            {change.reason}
          </div>
        </div>
      ))}
    </div>
  );
}
