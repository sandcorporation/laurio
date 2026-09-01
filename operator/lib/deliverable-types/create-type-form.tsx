"use client";

// 새 DeliverableType 생성 폼(#80) — 상위 등급 전용(호출부가 게이트한다).
// 정책 변경과 같은 규율로 이유를 요구한다.
import { useState } from "react";
import type { FormEvent } from "react";

import { parseIntegerFieldInput } from "@/lib/forms/parse-integer-field-input";
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

    // `Number("")`가 NaN이 아니라 0이라는 함정 때문에(코드리뷰 지적) 최소
    // 제안 상금 칸을 비운 채 생성하면 0원짜리 종류가 조용히 만들어질 뻔했다
    // — 이름은 unique이고 되살리는 경로가 없어(#80은 비활성화만 만든다) 그
    // 이름이 영구히 묶인다. parseIntegerFieldInput이 빈 문자열·숫자 아닌
    // 문자열을 구분해 서버의 422로 명시적으로 거절되게 한다.
    const parsedPrize = parseIntegerFieldInput(minimumPrize);
    const result = await createDeliverableType({
      name,
      minimum_prize: parsedPrize.valid
        ? parsedPrize.value
        : (parsedPrize.raw as unknown as number),
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
