"use client";

// 개최 권한 변경 이력 표(#414, #424 — 골간으로 옮긴다) — 누가·언제·누구를·부여인지
// 회수인지·왜. 일반 등급도 본다(`lib/deliverable-types/history-table.tsx`와 같은
// 관용구).
import { actionLabel } from "./types";
import type { HostingPermissionChangeEntry } from "./types";

import { TableScroll } from "@/app/components/table-scroll";

const COL = {
  action: "w-[80px]",
  operator: "w-[120px]",
  changedAt: "w-[140px]",
};

function TableHead() {
  return (
    <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className="min-w-0 flex-1">계정</div>
      <div className={`${COL.action} shrink-0`}>동작</div>
      <div className={`${COL.operator} shrink-0`}>누가</div>
      <div className={`${COL.changedAt} shrink-0`}>언제</div>
      <div className="min-w-0 flex-1">왜</div>
    </div>
  );
}

export function HostingPermissionHistoryTable({
  changes,
}: {
  changes: HostingPermissionChangeEntry[];
}) {
  if (changes.length === 0) {
    return (
      <p data-testid="hosting-permission-history-empty" className="px-[15px] py-[14px] text-[13px] text-ink/62">
        아직 변경 이력이 없습니다.
      </p>
    );
  }

  return (
    <div data-testid="hosting-permission-history-table">
      <TableScroll minWidth={720}>
        <TableHead />
        {changes.map((change, i) => (
          <div
            key={change.id}
            data-testid={`hosting-permission-history-row-${change.id}`}
            className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] ${
              i % 2 === 1 ? "bg-ink/[2%]" : ""
            }`}
          >
            <div className="min-w-0 flex-1 truncate">{change.user_email}</div>
            <div className={`${COL.action} shrink-0`}>{actionLabel(change.action)}</div>
            <div className={`${COL.operator} shrink-0 truncate font-mono`}>{change.operator_username}</div>
            <div className={`${COL.changedAt} shrink-0 truncate font-mono text-[12.5px]`}>
              {new Date(change.changed_at).toLocaleString("ko-KR")}
            </div>
            <div className="min-w-0 flex-1 truncate text-ink/62" data-testid={`hosting-permission-history-row-${change.id}-reason`}>
              {change.reason}
            </div>
          </div>
        ))}
      </TableScroll>
    </div>
  );
}
