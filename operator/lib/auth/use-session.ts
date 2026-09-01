"use client";

// 인증 구역 전체가 공유하는 세션 훅(#63). frontend/lib/auth/use-session.ts와
// 같은 계약이지만 필드가 다르다 — Operator에게는 sponsor/developer 프로필
// 개념이 없고(ADR-0018의 서로소 불변식), 대신 등급(is_superuser)이 있다.
//
// /api/auth/session을 부른다. Django 세션에는 공개 앱의 JWT 리프레시 같은
// "조용히 갱신"이 없다 — 401이면 그 자리에서 로그인으로 보낸다.
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export interface OperatorSessionUser {
  id: number;
  username: string;
  is_superuser: boolean;
  is_active: boolean;
}

export type OperatorSessionState =
  | { status: "loading" }
  | { status: "authenticated"; user: OperatorSessionUser }
  | { status: "unauthenticated" };

export function useSession(): OperatorSessionState {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<OperatorSessionState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    fetch("/api/auth/session", { cache: "no-store" })
      .then(async (res) => {
        if (cancelled) return;
        if (!res.ok) {
          setState({ status: "unauthenticated" });
          router.replace(`/login?next=${encodeURIComponent(pathname)}`);
          return;
        }
        const user = (await res.json()) as OperatorSessionUser;
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
