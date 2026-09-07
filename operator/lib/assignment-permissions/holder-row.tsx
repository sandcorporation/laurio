"use client";

// 과제 개최 자격 보유자 목록의 행 하나(#206). 회수하면 이 목록에서 사라진다 —
// SponsorProfile 자체는 지워지지 않지만(과제·제출물이 남아야 하므로), 이 화면은
// "지금 새 과제를 열 수 있는 사람"만 보여준다.
//
// 회수는 이유를 요구한다(정책·산출물 종류 변경과 같은 규율, #76·#80). 그리고
// 이미 열린 과제는 이 조작으로 영향받지 않는다는 사실을 버튼 옆에 명시한다 —
// 화면 문구가 그 약속을 말해야 한다는 것이 이 티켓의 AC다(ADR-0029).
import { useState } from "react";

import { revokeAssignmentPermission } from "./actions";
import type { AssignmentPermissionHolder } from "./types";

export function HolderRow({
  holder,
  canEdit,
  onChanged,
  onSessionExpired,
}: {
  holder: AssignmentPermissionHolder;
  canEdit: boolean;
  onChanged: () => void;
  onSessionExpired: () => void;
}) {
  const [revoking, setRevoking] = useState(false);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rowTestId = `assignment-permission-holder-${holder.sponsor_profile_id}`;

  function resetAndClose() {
    setRevoking(false);
    setReason("");
    setError(null);
  }

  async function handleConfirmRevoke() {
    setPending(true);
    setError(null);

    const result = await revokeAssignmentPermission(holder.sponsor_profile_id, reason);
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setRevoking(false);
    setReason("");
    onChanged();
  }

  return (
    <tr data-testid={rowTestId}>
      <td data-testid={`${rowTestId}-username`}>{holder.username}</td>
      <td data-testid={`${rowTestId}-display-name`}>{holder.display_name || "-"}</td>
      <td>
        {canEdit && !revoking && (
          <button
            type="button"
            data-testid={`${rowTestId}-revoke-button`}
            onClick={() => setRevoking(true)}
          >
            자격 회수
          </button>
        )}

        {revoking && (
          <div data-testid={`${rowTestId}-revoke-form`}>
            <p>
              회수해도 <strong>이미 열린 과제는 끝까지 그대로 돕니다</strong> — 학생이 이미 쓴
              시간을 버리지 않기 위해서입니다. 이 조작은 새 과제를 여는 것만 막습니다.
            </p>
            <label>
              이유
              <input
                data-testid={`${rowTestId}-revoke-reason`}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <button
              type="button"
              data-testid={`${rowTestId}-revoke-confirm`}
              onClick={handleConfirmRevoke}
              disabled={pending}
            >
              {pending ? "처리 중..." : "회수 확정"}
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
