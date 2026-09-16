"use client";

// 현재 정책값 표(#77, #425 — 골간 표 조각으로 옮긴다) — 상위 등급뿐 아니라
// 일반 등급도 본다(#76). 값이 실제로 그 자리에 있다는 것과 "값이 0"이
// 다르다는 것을 보여준다 — usePolicy가 "loaded" 상태일 때만 이 컴포넌트가
// 렌더되므로, 여기 나오는 숫자는 항상 실제 조회 결과다(조회 실패 시의
// 자리표시자가 아니다). 숫자는 고정폭(font-mono)으로 자릿수를 맞춘다.
import { POLICY_FIELDS, POLICY_FIELD_LABELS } from "./types";
import type { PlatformPolicy } from "./types";

export function PolicyValuesTable({ policy }: { policy: PlatformPolicy }) {
  return (
    <div data-testid="policy-values-table" className="border border-rule bg-surface">
      {POLICY_FIELDS.map((field, i) => (
        <div
          key={field}
          data-testid={`policy-value-row-${field}`}
          className={`flex items-center justify-between gap-4 border-b border-rule px-4 py-2.5 text-[13px] last:border-b-0 ${
            i % 2 === 1 ? "bg-ink/[2%]" : ""
          }`}
        >
          <span className="text-ink/62">{POLICY_FIELD_LABELS[field]}</span>
          <span data-testid={`policy-value-${field}`} className="font-mono text-[13px] text-ink">
            {policy[field]}
          </span>
        </div>
      ))}
    </div>
  );
}
