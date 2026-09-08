"use client";

// 새 Category 생성 폼(#231) — 상위 등급 전용(호출부가 게이트한다).
// deliverable-types/create-type-form.tsx와 같은 규율로 이유를 요구한다.
import { useState } from "react";
import type { FormEvent } from "react";

import { createCategory } from "./actions";

export function CreateCategoryForm({
  onCreated,
  onSessionExpired,
}: {
  onCreated: () => void;
  onSessionExpired: () => void;
}) {
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);

    const result = await createCategory({ name, reason });
    setPending(false);

    if (!result.ok) {
      if (result.code === "unauthorized") {
        onSessionExpired();
        return;
      }
      setError(result.detail);
      return;
    }

    setName("");
    setReason("");
    onCreated();
  }

  return (
    <form onSubmit={handleSubmit} data-testid="create-category-form">
      <h2>새 카테고리 만들기</h2>
      <label>
        이름
        <input
          data-testid="create-category-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        이유
        <input
          data-testid="create-category-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button type="submit" data-testid="create-category-submit" disabled={pending}>
        {pending ? "생성 중..." : "카테고리 생성"}
      </button>
      {error && (
        <p role="alert" data-testid="create-category-error">
          {error}
        </p>
      )}
    </form>
  );
}
