"use client";

// Operator 목록의 행 하나(#69). 아이디·등급·활성 여부를 보여주고, 활성이면
// 비활성화 버튼을, 비활성이면 재활성화 버튼을 낸다 — 둘 다 동시에 보이는 상태는
// 없다(현재 상태에서 실제로 할 수 있는 행위만 보인다).
//
// 마지막 상위 등급 계정의 비활성화는 백엔드가 409(code: last_superuser)로
// 거절한다 — 여기서는 그 이유를 그대로 relay한다. 이 화면에서 별도의
// "마지막 superuser인지" 판정을 다시 하지 않는다: 그런 가드를 프론트에 한 번 더
// 얹으면, 서버 판정과 어긋나는 순간(예: 다른 탭에서 동시에 비활성화) 화면이
// 틀린 이유로 버튼을 막거나 반대로 서버가 막을 것을 화면이 허용해 버린다
// (backend/accounts/operators.py가 "자기 사건 회피 가드를 따로 두지 마라"고
// 경고하는 것과 같은 원칙 — 구조/서버가 막는 것을 규칙으로 한 번 더 막지 않는다).
import { useState } from "react";

import { Badge } from "@/app/components/badge";

import { deactivateOperator, reactivateOperator } from "./actions";
import type { OperatorAccount } from "./types";

const COL = {
  grade: "w-[96px]",
  active: "w-[80px]",
  action: "w-[160px]",
};

export function OperatorRow({
  operator,
  zebra,
  onChanged,
  onSessionExpired,
}: {
  operator: OperatorAccount;
  zebra: boolean;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDeactivate() {
    setPending(true);
    setError(null);
    const result = await deactivateOperator(operator.id);
    setPending(false);
    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }
    onChanged();
  }

  async function handleReactivate() {
    setPending(true);
    setError(null);
    const result = await reactivateOperator(operator.id);
    setPending(false);
    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }
    onChanged();
  }

  const rowTestId = `operator-row-${operator.id}`;

  return (
    <div
      data-testid={rowTestId}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px] ${
        zebra ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className="min-w-0 flex-1 truncate" data-testid={`${rowTestId}-username`}>
        {operator.username}
      </div>
      <div className={`${COL.grade} shrink-0 truncate text-[12.5px] text-ink/62`} data-testid={`${rowTestId}-grade`}>
        {operator.is_superuser ? "상위 등급" : "일반 등급"}
      </div>
      <div className={`${COL.active} shrink-0`}>
        <Badge testId={`${rowTestId}-active`}>{operator.is_active ? "활성" : "비활성"}</Badge>
      </div>
      <div className={`${COL.action} shrink-0`}>
        <span className="flex flex-col gap-1">
          {operator.is_active ? (
            <button
              type="button"
              data-testid={`${rowTestId}-deactivate`}
              onClick={handleDeactivate}
              disabled={pending}
              className="w-fit border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
            >
              {pending ? "처리 중..." : "비활성화"}
            </button>
          ) : (
            <button
              type="button"
              data-testid={`${rowTestId}-reactivate`}
              onClick={handleReactivate}
              disabled={pending}
              className="w-fit border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50"
            >
              {pending ? "처리 중..." : "재활성화"}
            </button>
          )}
          {error && (
            <p role="alert" data-testid={`${rowTestId}-action-error`} className="text-[11px] text-attention">
              {error}
            </p>
          )}
        </span>
      </div>
    </div>
  );
}
