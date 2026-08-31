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

import { deactivateOperator, reactivateOperator } from "./actions";
import type { OperatorAccount } from "./types";

export function OperatorRow({
  operator,
  onChanged,
  onSessionExpired,
}: {
  operator: OperatorAccount;
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
      if (result.status === 401) {
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
      if (result.status === 401) {
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
    <tr data-testid={rowTestId}>
      <td data-testid={`${rowTestId}-username`}>{operator.username}</td>
      <td data-testid={`${rowTestId}-grade`}>{operator.is_superuser ? "상위 등급" : "일반 등급"}</td>
      <td data-testid={`${rowTestId}-active`}>{operator.is_active ? "활성" : "비활성"}</td>
      <td>
        {operator.is_active ? (
          <button
            type="button"
            data-testid={`${rowTestId}-deactivate`}
            onClick={handleDeactivate}
            disabled={pending}
          >
            {pending ? "처리 중..." : "비활성화"}
          </button>
        ) : (
          <button
            type="button"
            data-testid={`${rowTestId}-reactivate`}
            onClick={handleReactivate}
            disabled={pending}
          >
            {pending ? "처리 중..." : "재활성화"}
          </button>
        )}
        {error && (
          <p role="alert" data-testid={`${rowTestId}-action-error`}>
            {error}
          </p>
        )}
      </td>
    </tr>
  );
}
