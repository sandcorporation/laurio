"use client";

// Category 변경 이력 표(#231) — 누가·언제·무엇을·왜. 일반 등급도 본다.
import { actionLabel } from "./types";
import type { Category, CategoryChangeEntry } from "./types";

function categoryName(categoryId: number, categories: Category[]): string {
  return categories.find((c) => c.id === categoryId)?.name ?? `카테고리 #${categoryId}`;
}

function formatDiff(change: CategoryChangeEntry): string {
  const keys = Object.keys(change.after);
  if (keys.length === 0) return "생성";
  return keys
    .map((key) => `${key}: ${String(change.before[key] ?? "-")} → ${String(change.after[key])}`)
    .join(", ");
}

export function CategoryHistoryTable({
  changes,
  categories,
}: {
  changes: CategoryChangeEntry[];
  categories: Category[];
}) {
  if (changes.length === 0) {
    return <p data-testid="category-history-empty">아직 변경 이력이 없습니다.</p>;
  }

  return (
    <table data-testid="category-history-table">
      <thead>
        <tr>
          <th>카테고리</th>
          <th>동작</th>
          <th>누가</th>
          <th>언제</th>
          <th>무엇을 무엇으로</th>
          <th>왜</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={change.id} data-testid={`category-history-row-${change.id}`}>
            <td>{categoryName(change.category_id, categories)}</td>
            <td>{actionLabel(change.action)}</td>
            <td>{change.operator_username}</td>
            <td>{new Date(change.changed_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`category-history-row-${change.id}-diff`}>{formatDiff(change)}</td>
            <td data-testid={`category-history-row-${change.id}-reason`}>{change.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
