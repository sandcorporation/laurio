"use client";

// 운영자 로그인 화면(#63, ADR-0018/0019, 골간으로 옮긴다 — #427 부모 #421).
// 공개 앱과 다른 지점: 소셜 버튼이 아니라 아이디·비밀번호 폼이다(Operator는
// 서로소 불변식 때문에 소셜 계정을 가질 수 없다). 색인 대상이 아니므로
// (ADR-0021) 서버 컴포넌트로 둘 이유가 없어 클라이언트 컴포넌트로 남긴다.
//
// 왼쪽 내비를 두르지 않는 유일한 화면이다(`app-shell.tsx`의 `NO_SHELL_PATHS`)
// — 로그인 전이라 보일 계정·큐 배지가 없다. 그래서 다른 골간 화면과 달리 화면
// 전체를 `bg-paper`로 채우고 가운데 카드 하나로 마무리한다 — 같은 토큰(테두리는
// `border-rule`, 입력은 `create-operator-form.tsx`와 같은 모양)이되 골간 자체는
// 이 화면에만 있는 자리다.
import { Suspense, useState } from "react";

import { normalizeDetail } from "@codemit/bff-client";
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
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
        // 백엔드가 이미 계정 존재 여부를 드러내지 않는 단일 문구로 답한다
        // (accounts/operator_api.py의 _LOGIN_FAILED) — 이 화면은 그 문구를
        // 그대로 보여주기만 하고 되돌리지 않는다.
        setError(normalizeDetail(body?.detail, `로그인에 실패했습니다 (${res.status})`));
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
    <div className="flex min-h-screen items-center justify-center bg-paper p-6">
      <div className="flex w-full max-w-sm flex-col gap-6 border border-rule bg-surface p-8">
        <div>
          <h1 className="text-[19px] font-semibold tracking-[-0.01em]">운영자 로그인</h1>
          <p className="mt-1.5 text-[12.5px] text-ink/62">Codemit 운영자 전용입니다.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
          <label className="flex flex-col gap-1 text-[12.5px] text-ink/62">
            아이디
            <input
              data-testid="login-username"
              value={username}
              autoComplete="username"
              onChange={(event) => setUsername(event.target.value)}
              className="border border-rule bg-paper px-2.5 py-1.5 text-[13px] text-ink"
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-ink/62">
            비밀번호
            <input
              data-testid="login-password"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
              className="border border-rule bg-paper px-2.5 py-1.5 text-[13px] text-ink"
            />
          </label>
          <button
            type="submit"
            data-testid="login-submit"
            disabled={pending}
            className="mt-1.5 w-fit border border-ink bg-ink px-3 py-1.5 text-[12.5px] text-paper disabled:opacity-50"
          >
            {pending ? "로그인 중..." : "로그인"}
          </button>
        </form>

        {error && (
          <p role="alert" data-testid="login-error" className="text-[12px] text-attention">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

export default function LoginForm() {
  return (
    <Suspense fallback={null}>
      <LoginFields />
    </Suspense>
  );
}
