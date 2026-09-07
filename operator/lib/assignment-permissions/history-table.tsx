"use client";

// AssignmentPermissionChange 이력 표(#206) — 누가·언제·무엇을·왜. 일반 등급도 본다.
//
// deliverable-types/history-table.tsx와 달리 별도 목록과 조인하지 않는다 — 응답
// 자체가 `username`을 함께 준다(AssignmentPermissionChangeOut, accounts/schemas.py)
// — 회수된 뒤에는 보유자 목록에서 사라지므로 그쪽과 조인하면 이름을 잃는다.
import { actionLabel } from "./types";
import type { AssignmentPermissionChangeEntry } from "./types";

export function AssignmentPermissionHistoryTable({
  changes,
}: {
  changes: AssignmentPermissionChangeEntry[];
}) {
  if (changes.length === 0) {
    return <p data-testid="assignment-permission-history-empty">아직 변경 이력이 없습니다.</p>;
  }

  return (
    <table data-testid="assignment-permission-history-table">
      <thead>
        <tr>
          <th>Sponsor</th>
          <th>동작</th>
          <th>운영자</th>
          <th>언제</th>
          <th>왜</th>
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr
            key={change.id}
            data-testid={`assignment-permission-history-row-${change.id}`}
          >
            <td>{change.username}</td>
            <td>{actionLabel(change.action)}</td>
            <td>{change.operator_username}</td>
            <td>{new Date(change.changed_at).toLocaleString("ko-KR")}</td>
            <td data-testid={`assignment-permission-history-row-${change.id}-reason`}>
              {change.reason}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
