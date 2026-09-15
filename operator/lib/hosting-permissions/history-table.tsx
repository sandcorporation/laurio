"use client";

// 개최 권한 변경 이력 표(#414) — 누가·언제·누구를·부여인지 회수인지·왜. 일반
// 등급도 본다(`lib/deliverable-types/history-table.tsx`와 같은 관용구).
import { actionLabel } from "./types";
import type { HostingPermissionChangeEntry } from "./types";

export function HostingPermissionHistoryTable({
  changes,
}: {
  changes: HostingPermissionChangeEntry[];
}) {
  if (changes.length === 0) {
    return <p data-testid="hosting-permission-history-empty">아직 변경 이력이 없습니다.</p>;
  }

  return (
    <table data-testid="hosting-permission-history-table">
      <thead>
        <tr>
          <th>계정</th>
          <th>동작</th>
          <th>누가</th>
          <th>언제</th>
          <th>왜</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={change.id} data-testid={`hosting-permission-history-row-${change.id}`}>
            <td>{change.user_email}</td>
            <td>{actionLabel(change.action)}</td>
            <td>{change.operator_username}</td>
            <td>{new Date(change.changed_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`hosting-permission-history-row-${change.id}-reason`}>
              {change.reason}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
