"use client";

// DeliverableType 변경 이력 표(#80, #425 — 골간 표 조각으로 옮긴다) — 누가·
// 언제·무엇을·왜. 일반 등급도 본다. 고치거나 지우는 조작은 없다 —
// append-only(ADR-0023)라는 사실을 호출부(operator/app/deliverable-types/
// page.tsx)가 캡션으로 명시적으로 말한다.
import { actionLabel } from "./types";
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

const COL = {
  type: "w-[130px]",
  action: "w-[80px]",
  operator: "w-[110px]",
  changedAt: "w-[150px]",
  reason: "w-[200px]",
};

export function DeliverableTypeHistoryTable({
  changes,
  types,
}: {
  changes: DeliverableTypeChangeEntry[];
  types: DeliverableType[];
}) {
  if (changes.length === 0) {
    return (
      <p data-testid="deliverable-type-history-empty" className="text-[13px] text-ink/62">
        아직 변경 이력이 없습니다.
      </p>
    );
  }

  return (
    <div data-testid="deliverable-type-history-table" className="border border-rule bg-surface">
      <div className="flex gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
        <div className={`${COL.type} shrink-0`}>종류</div>
        <div className={`${COL.action} shrink-0`}>동작</div>
        <div className={`${COL.operator} shrink-0`}>누가</div>
        <div className={`${COL.changedAt} shrink-0`}>언제</div>
        <div className="min-w-0 flex-1">무엇을 무엇으로</div>
        <div className={`${COL.reason} shrink-0`}>왜</div>
      </div>
      {changes.map((change, i) => (
        <div
          key={change.id}
          data-testid={`deliverable-type-history-row-${change.id}`}
          className={`flex gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
            i % 2 === 1 ? "bg-ink/[2%]" : ""
          }`}
        >
          <div className={`${COL.type} shrink-0 truncate`}>
            {typeName(change.deliverable_type_id, types)}
          </div>
          <div className={`${COL.action} shrink-0 truncate`}>{actionLabel(change.action)}</div>
          <div className={`${COL.operator} shrink-0 truncate font-mono`}>{change.operator_username}</div>
          <div className={`${COL.changedAt} shrink-0 truncate font-mono text-ink/62`}>
            {new Date(change.changed_at).toLocaleString("ko-KR")}
          </div>
          <div
            className="min-w-0 flex-1 truncate"
            data-testid={`deliverable-type-history-row-${change.id}-diff`}
          >
            {formatDiff(change)}
          </div>
          <div
            className={`${COL.reason} shrink-0 truncate text-ink/62`}
            data-testid={`deliverable-type-history-row-${change.id}-reason`}
          >
            {change.reason}
          </div>
        </div>
      ))}
    </div>
  );
}
