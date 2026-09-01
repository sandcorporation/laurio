"use client";

// 변경 이력 표(#77) — 누가·언제·무엇을 무엇으로·왜. 일반 등급 Operator도 본다
// (조회는 등급을 가리지 않는다, #76).
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

export function PolicyHistoryTable({ changes }: { changes: PolicyChangeEntry[] }) {
  if (changes.length === 0) {
    return <p data-testid="policy-history-empty">아직 변경 이력이 없습니다.</p>;
  }

  return (
    <table data-testid="policy-history-table">
      <thead>
        <tr>
          <th>누가</th>
          <th>언제</th>
          <th>무엇을 무엇으로</th>
          <th>왜</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={change.id} data-testid={`policy-history-row-${change.id}`}>
            <td data-testid={`policy-history-row-${change.id}-operator`}>{change.operator_username}</td>
            <td data-testid={`policy-history-row-${change.id}-changed-at`}>
              {new Date(change.changed_at).toLocaleString("ko-KR")}
            </td>
            <td data-testid={`policy-history-row-${change.id}-diff`}>{formatDiff(change)}</td>
            <td data-testid={`policy-history-row-${change.id}-reason`}>{change.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
