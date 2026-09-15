"use client";

// 검색 결과·보유 목록 한 줄(#414). 상위 등급만 켜고 끌 수 있다 — 산출물 종류·
// 카테고리와 같은 무게의 판단이다(누가 상금 없이 공모전을 열 수 있는지를
// 정한다). 사유가 필수라 버튼 하나로 바로 실행하지 않고, 이유를 적는 인라인
// 폼을 먼저 연다(`lib/deliverable-types/type-row.tsx`와 같은 관용구).
import { useState } from "react";

import { setHostingPermission } from "./actions";
import type { HostingPermissionAccount } from "./types";

type Mode = "view" | "confirming";

export function HostingPermissionAccountRow({
  account,
  canEdit,
  onChanged,
  onSessionExpired,
}: {
  account: HostingPermissionAccount;
  canEdit: boolean;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [mode, setMode] = useState<Mode>("view");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowTestId = `hosting-permission-account-row-${account.user_id}`;
  const nextGranted = !account.is_granted;

  function resetAndClose() {
    setMode("view");
    setReason("");
    setError(null);
  }

  async function handleConfirm() {
    setPending(true);
    setError(null);

    const result = await setHostingPermission(account.user_id, nextGranted, reason);
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setMode("view");
    setReason("");
    onChanged();
  }

  return (
    <tr data-testid={rowTestId}>
      <td data-testid={`${rowTestId}-email`}>{account.email}</td>
      <td data-testid={`${rowTestId}-nickname`}>{account.nickname || "-"}</td>
      <td data-testid={`${rowTestId}-granted`}>{account.is_granted ? "있음" : "없음"}</td>
      <td>
        {canEdit && mode === "view" && (
          <button
            type="button"
            data-testid={`${rowTestId}-toggle-button`}
            onClick={() => setMode("confirming")}
          >
            {account.is_granted ? "권한 회수" : "권한 부여"}
          </button>
        )}

        {mode === "confirming" && (
          <div data-testid={`${rowTestId}-form`}>
            <label>
              이유
              <input
                data-testid={`${rowTestId}-reason`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button
              type="button"
              data-testid={`${rowTestId}-confirm`}
              onClick={handleConfirm}
              disabled={pending}
            >
              {pending ? "처리 중..." : account.is_granted ? "회수 확정" : "부여 확정"}
            </button>
            <button type="button" onClick={resetAndClose} disabled={pending}>
              취소
            </button>
          </div>
        )}

        {error && (
          <p role="alert" data-testid={`${rowTestId}-error`}>
            {error}
          </p>
        )}
      </td>
    </tr>
  );
}
