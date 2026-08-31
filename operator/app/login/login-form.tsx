"use client";

// 운영자 로그인 화면(#63, ADR-0018/0019). 공개 앱과 다른 지점: 소셜 버튼이
// 아니라 아이디·비밀번호 폼이다(Operator는 서로소 불변식 때문에 소셜 계정을
// 가질 수 없다). 색인 대상이 아니므로(ADR-0021) 서버 컴포넌트로 둘 이유가
// 없어 클라이언트 컴포넌트로 남긴다.
import { Suspense, useState } from "react";
import type { FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { sanitizeNextPath } from "@/lib/auth/sanitize-next";

function LoginFields() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = sanitizeNextPath(searchParams.get("next"));

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        // 백엔드가 이미 계정 존재 여부를 드러내지 않는 단일 문구로 답한다
        // (accounts/operator_api.py의 _LOGIN_FAILED) — 이 화면은 그 문구를
        // 그대로 보여주기만 하고 되돌리지 않는다.
        setError(body?.detail ?? `로그인에 실패했습니다 (${res.status})`);
        return;
      }

      router.replace(next);
      router.refresh();
    } catch {
      setError("로그인 요청을 보내지 못했습니다. 네트워크를 확인해주세요.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main>
      <div>
        <h1>운영자 로그인</h1>
        <p>Laurio 운영자 전용입니다.</p>
      </div>

      <form onSubmit={handleSubmit}>
        <label>
          아이디
          <input
            data-testid="login-username"
            value={username}
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          비밀번호
          <input
            data-testid="login-password"
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <button type="submit" data-testid="login-submit" disabled={pending}>
          {pending ? "로그인 중..." : "로그인"}
        </button>
      </form>

      {error && (
        <p role="alert" data-testid="login-error">
          {error}
        </p>
      )}
    </main>
  );
}

export default function LoginForm() {
  return (
    <Suspense fallback={null}>
      <LoginFields />
    </Suspense>
  );
}
