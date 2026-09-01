"use client";

// 새 DeliverableType 생성 폼(#80) — 상위 등급 전용(호출부가 게이트한다).
// 정책 변경과 같은 규율로 이유를 요구한다.
import { useState } from "react";
import type { FormEvent } from "react";

import { createDeliverableType } from "./actions";

export function CreateTypeForm({
  onCreated,
  onSessionExpired,
}: {
  onCreated: () => void;
  onSessionExpired: () => void;
}) {
  const [name, setName] = useState("");
  const [minimumPrize, setMinimumPrize] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);

    const parsedPrize = Number(minimumPrize.trim());
    const result = await createDeliverableType({
      name,
      // 파싱 불가한 값은 그대로 NaN을 보내지 않고, 서버의 요청 검증이
      // 422로 거절하도록 원본 문자열을 그대로 실어 보낸다 —
      // policy-editor.tsx와 같은 판단.
      minimum_prize: Number.isNaN(parsedPrize) ? (minimumPrize as unknown as number) : parsedPrize,
      reason,
    });
    setPending(false);

    if (!result.ok) {
      if (result.status === 401) {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setName("");
    setMinimumPrize("");
    setReason("");
    onCreated();
  }

  return (
    <form onSubmit={handleSubmit} data-testid="create-deliverable-type-form">
      <h2>새 산출물 종류 만들기</h2>
      <label>
        이름
        <input
          data-testid="create-deliverable-type-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        최소 제안 상금(원)
        <input
          data-testid="create-deliverable-type-minimum-prize"
          value={minimumPrize}
          onChange={(event) => setMinimumPrize(event.target.value)}
        />
      </label>
      <label>
        이유
        <input
          data-testid="create-deliverable-type-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button type="submit" data-testid="create-deliverable-type-submit" disabled={pending}>
        {pending ? "생성 중..." : "종류 생성"}
      </button>
      {error && (
        <p role="alert" data-testid="create-deliverable-type-error">
          {error}
        </p>
      )}
    </form>
  );
}
