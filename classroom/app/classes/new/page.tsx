"use client";

// 새 클래스 만들기 (#278). 이름만 받는다 — 초대 링크는 #279, 문제는 #282의
// 자리다.
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { FormEvent } from "react";

import { createClass } from "@/lib/classes/api";

export default function NewClassPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await createClass(name.trim());
      router.push(`/classes/${created.id}`);
    } catch {
      setError("클래스를 만들지 못했습니다. 잠시 후 다시 시도해주세요.");
      setSubmitting(false);
    }
  }

  return (
    <main>
      <h1 data-testid="new-class-heading">새 클래스</h1>

      <form onSubmit={handleSubmit}>
        <label htmlFor="class-name">클래스 이름</label>
        <input
          id="class-name"
          data-testid="new-class-name-input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <button type="submit" data-testid="new-class-submit" disabled={submitting || name.trim() === ""}>
          {submitting ? "만드는 중..." : "만들기"}
        </button>
      </form>

      {error ? <p data-testid="new-class-error">{error}</p> : null}
    </main>
  );
}
