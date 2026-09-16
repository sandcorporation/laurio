"use client";

// 검색 결과·보유 목록 한 줄(#414, #424 — 골간으로 옮긴다). 상위 등급만 켜고 끌 수
// 있다 — 산출물 종류·카테고리와 같은 무게의 판단이다(누가 상금 없이 공모전을 열 수
// 있는지를 정한다). 사유가 필수라 버튼 하나로 바로 실행하지 않고, 이유를 적는
// 인라인 폼을 먼저 연다(`lib/deliverable-types/type-row.tsx`와 같은 관용구).
//
// **「개최 권한」은 판정이 아니라 정보다** — 그래서 초록/빨강이 아니라 중립
// 배지에 글자로만 가른다(spec #421 user story 17).
import { useState } from "react";

import { Badge } from "@/app/components/badge";

import { setHostingPermission } from "./actions";
import { HOSTING_PERMISSION_COL } from "./table-columns";
import type { HostingPermissionAccount } from "./types";

type Mode = "view" | "confirming";

const SECONDARY_BUTTON = "border border-rule bg-surface px-2.5 py-1 text-[12px] text-ink disabled:opacity-50";
const PRIMARY_BUTTON = "bg-ink px-2.5 py-1 text-[12px] text-paper disabled:opacity-50";

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
    <div data-testid={rowTestId} className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[13px]">
      <div className="min-w-0 flex-1 truncate" data-testid={`${rowTestId}-email`}>
        {account.email}
      </div>
      <div className={`${HOSTING_PERMISSION_COL.nickname} shrink-0 truncate`} data-testid={`${rowTestId}-nickname`}>
        {account.nickname || "-"}
      </div>
      <div className={`${HOSTING_PERMISSION_COL.granted} shrink-0`} data-testid={`${rowTestId}-granted`}>
        <Badge tone="neutral">{account.is_granted ? "있음" : "없음"}</Badge>
      </div>
      <div className={`${HOSTING_PERMISSION_COL.action} shrink-0`}>
        {canEdit && mode === "view" && (
          <button type="button" data-testid={`${rowTestId}-toggle-button`} onClick={() => setMode("confirming")} className={SECONDARY_BUTTON}>
            {account.is_granted ? "권한 회수" : "권한 부여"}
          </button>
        )}

        {mode === "confirming" && (
          <div data-testid={`${rowTestId}-form`} className="flex flex-col gap-[7px]">
            <label className="flex flex-col gap-[3px]">
              <span className="text-[11px] text-ink/45">이유 (필수)</span>
              <input
                data-testid={`${rowTestId}-reason`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="border border-rule bg-paper px-2 py-1 text-[12.5px] text-ink"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                data-testid={`${rowTestId}-confirm`}
                onClick={handleConfirm}
                disabled={pending}
                className={PRIMARY_BUTTON}
              >
                {pending ? "처리 중..." : account.is_granted ? "회수 확정" : "부여 확정"}
              </button>
              <button type="button" onClick={resetAndClose} disabled={pending} className={SECONDARY_BUTTON}>
                취소
              </button>
            </div>
          </div>
        )}

        {error && (
          <p role="alert" data-testid={`${rowTestId}-error`} className="mt-1 text-[12px] text-attention">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
