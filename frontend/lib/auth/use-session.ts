"use client";

// 인증 구역(app/console/**, ADR-0015)의 화면들이 공유하는 세션 훅.
//
// /api/auth/session을 부른다(FE-07, #32) — 액세스가 만료돼 있으면 그 라우트가
// 조용히 리프레시하므로 여기서는 성공/실패만 본다. 401(리프레시까지 실패)이면
// 로그인으로 보낸다 — "리프레시도 실패하면 로그인으로 보낸다"는 FE-07 인수조건을
// 미들웨어(쿠키가 아예 없는 경우)와 나눠 함께 지킨다: 미들웨어는 렌더링 전 게이트,
// 이 훅은 "쿠키는 있었지만 죽어버린" 세션의 런타임 게이트다.
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { sessionFetch } from "./client-fetch";

export interface SessionUser {
  id: number;
  username: string;
  email: string;
  has_sponsor_profile: boolean;
  has_developer_profile: boolean;
}

export type SessionState =
  | { status: "loading" }
  | { status: "authenticated"; user: SessionUser }
  | { status: "unauthenticated" };

export function useSession(): SessionState {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<SessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    sessionFetch("/api/auth/session", { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setState({ status: "unauthenticated" });
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        const user = (await res.json()) as SessionUser;
        setState({ status: "authenticated", user });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "unauthenticated" });
      });

    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  return state;
}
