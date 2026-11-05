"use client";

// 운영 설정 변경 이력(#922) — 누가·언제·어느 설정·무엇에서 무엇으로. 비밀은 끝 4자리 표시만 온다.
import type { RuntimeSettingChange } from "./types";
import { changeText } from "./view";

const COL = { operator: "sm:w-[110px] sm:shrink-0", changedAt: "sm:w-[200px] sm:shrink-0", label: "sm:w-[180px] sm:shrink-0" };

export function RuntimeSettingHistoryTable({ changes }: { changes: RuntimeSettingChange[] }) {
  if (changes.length === 0) {
    return (
      <p data-testid="runtime-settings-history-empty" className="text-[13px] text-ink/62">
        변경 이력 없음
      </p>
    );
  }

  // 열이 넷뿐이라 좁은 화면에서는 가로로 넘기지 않고 한 행을 두 줄로 접는다.
  return (
    <div data-testid="runtime-settings-history" className="border border-rule bg-surface">
      <div className="hidden gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30 sm:flex">
        <div className={COL.operator}>누가</div>
        <div className={COL.changedAt}>언제</div>
        <div className={COL.label}>설정</div>
        <div className="min-w-0 flex-1">변경</div>
      </div>
      {changes.map((change, i) => (
        <div
          key={change.id}
          data-testid={`runtime-settings-history-row-${change.id}`}
          className={`flex flex-wrap gap-x-3.5 gap-y-0.5 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 sm:flex-nowrap ${
            i % 2 === 1 ? "bg-ink/[2%]" : ""
          }`}
        >
          <div className={`${COL.operator} min-w-0 truncate font-mono`}>{change.operator_username}</div>
          <div className={`${COL.changedAt} min-w-0 truncate font-mono text-ink/62`}>
            {new Date(change.changed_at).toLocaleString("ko-KR")}
          </div>
          <div className={`${COL.label} min-w-0 truncate`}>{change.label}</div>
          <div className="min-w-0 basis-full truncate font-mono sm:basis-auto sm:flex-1">{changeText(change)}</div>
        </div>
      ))}
    </div>
  );
}
