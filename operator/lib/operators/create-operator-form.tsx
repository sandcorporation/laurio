"use client";

// 새 Operator 생성 폼(#69). 서버가 준 `detail`을 그대로 보여준다 — 약한
// 비밀번호와 중복 아이디는 백엔드 메시지 자체가 서로 달라서(#69의 "약한
// 비밀번호와 중복 아이디는 서로 다른 메시지다") 이 화면이 따로 문구를 다시
// 짓지 않아도 구별된다. "생성 실패"로 뭉개지 않는 것이 핵심이다.
import { useState } from "react";
import type { FormEvent } from "react";

import { createOperator } from "./actions";

export function CreateOperatorForm({
  onCreated,
  onSessionExpired,
}: {
  onCreated: () => void;
  onSessionExpired: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isSuperuser, setIsSuperuser] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    const result = await createOperator({ username, password, is_superuser: isSuperuser });
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
    setPassword("");
    setIsSuperuser(false);
    onCreated();
  }

  return (
    <form onSubmit={handleSubmit} data-testid="create-operator-form">
      <h2>새 Operator 만들기</h2>
      <label>
        아이디
        <input
          data-testid="create-operator-username"
          value={username}
          autoComplete="off"
          onChange={(event) => setUsername(event.target.value)}
        />
      </label>
      <label>
        비밀번호
        <input
          data-testid="create-operator-password"
          type="password"
          value={password}
          autoComplete="new-password"
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      <label>
        상위 등급(계정 관리 가능)
        <input
          data-testid="create-operator-superuser"
          type="checkbox"
          checked={isSuperuser}
          onChange={(event) => setIsSuperuser(event.target.checked)}
        />
      </label>
      <button type="submit" data-testid="create-operator-submit" disabled={pending}>
        {pending ? "생성 중..." : "Operator 생성"}
      </button>
      {error && (
        <p role="alert" data-testid="create-operator-error">
          {error}
        </p>
      )}
    </form>
  );
}
