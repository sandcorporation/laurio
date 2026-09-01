"use client";

// DeliverableType 변경 이력 표(#80) — 누가·언제·무엇을·왜. 일반 등급도 본다.
import { ACTION_LABELS } from "./types";
import type { DeliverableType, DeliverableTypeChangeEntry } from "./types";

function typeName(typeId: number, types: DeliverableType[]): string {
  return types.find((t) => t.id === typeId)?.name ?? `종류 #${typeId}`;
}

function formatDiff(change: DeliverableTypeChangeEntry): string {
  const keys = Object.keys(change.after);
  if (keys.length === 0) return "생성";
  return keys
    .map((key) => `${key}: ${String(change.before[key] ?? "-")} → ${String(change.after[key])}`)
    .join(", ");
}

export function DeliverableTypeHistoryTable({
  changes,
  types,
}: {
  changes: DeliverableTypeChangeEntry[];
  types: DeliverableType[];
}) {
  if (changes.length === 0) {
    return <p data-testid="deliverable-type-history-empty">아직 변경 이력이 없습니다.</p>;
  }

  return (
    <table data-testid="deliverable-type-history-table">
      <thead>
        <tr>
          <th>종류</th>
          <th>동작</th>
          <th>누가</th>
          <th>언제</th>
          <th>무엇을 무엇으로</th>
          <th>왜</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={change.id} data-testid={`deliverable-type-history-row-${change.id}`}>
            <td>{typeName(change.deliverable_type_id, types)}</td>
            <td>{ACTION_LABELS[change.action]}</td>
            <td>{change.operator_username}</td>
            <td>{new Date(change.changed_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`deliverable-type-history-row-${change.id}-diff`}>{formatDiff(change)}</td>
            <td data-testid={`deliverable-type-history-row-${change.id}-reason`}>{change.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
