"use client";

// 새 과제 개최 자격 부여 폼(#206) — 상위 등급 전용(호출부가 게이트한다).
// 정책·산출물 종류 변경과 같은 규율로 이유를 요구한다.
//
// 대상은 사용자명으로 찾는다 — SponsorProfile은 지연 생성이라(과제를 열기
// 전에는 존재하지 않는다) id로 고를 목록 자체가 없다. 부여 API가 아직 없는
// 프로필을 만들어 붙인다(accounts.assignment_permission_services.
// grant_assignment_permission).
import { useState } from "react";
import type { FormEvent } from "react";

import { grantAssignmentPermission } from "./actions";

export function GrantForm({
  onGranted,
  onSessionExpired,
}: {
  onGranted: () => void;
  onSessionExpired: () => void;
}) {
  const [username, setUsername] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);

    const result = await grantAssignmentPermission(username, reason);
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setUsername("");
    setReason("");
    onGranted();
  }

  return (
    <form onSubmit={handleSubmit} data-testid="grant-assignment-permission-form">
      <h2>과제 개최 자격 주기</h2>
      <p>
        과제(Assignment)에는 결제가 없어 비용이 스스로 제어되지 않습니다. 개최비가 서 있던
        자리를 이 자격이 대신합니다 — 신뢰할 수 있는 강사에게만 주세요.
      </p>
      <label>
        사용자명
        <input
          data-testid="grant-assignment-permission-username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
      </label>
      <label>
        이유
        <input
          data-testid="grant-assignment-permission-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button
        type="submit"
        data-testid="grant-assignment-permission-submit"
        disabled={pending}
      >
        {pending ? "부여 중..." : "자격 부여"}
      </button>
      {error && (
        <p role="alert" data-testid="grant-assignment-permission-error">
          {error}
        </p>
      )}
    </form>
  );
}
