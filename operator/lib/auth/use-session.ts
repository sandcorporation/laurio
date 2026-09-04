"use client";

// 인증 구역 전체가 공유하는 세션 훅(#63). frontend/lib/auth/use-session.ts와 같은 계약이지만
// 필드가 다르다 — Operator에게는 sponsor/developer 프로필 개념이 없고(ADR-0018의 서로소
// 불변식), 대신 등급(is_superuser)이 있다.
//
// `/api/auth/session` 을 부른다. Django 세션에는 공개 앱의 JWT 리프레시 같은 "조용히 갱신"이
// 없다 — 401이면 클라이언트가 그 자리에서 로그인으로 보낸다(`lib/bff/client.ts`, #148).

import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

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
  const { state } = useBackendQuery<OperatorSessionUser>(bffClient, "/api/auth/session");
  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "unauthenticated" };
  return { status: "authenticated", user: state.data };
}
