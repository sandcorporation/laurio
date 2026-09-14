"use client";

// 인증 구역(app/console/**, ADR-0015)의 화면들이 공유하는 세션 훅.
//
// `/api/auth/session` 을 부른다(FE-07, #32) — 액세스가 만료돼 있으면 그 라우트가 조용히
// 리프레시하므로 여기서는 성공/실패만 본다. 401(리프레시까지 실패)이면 클라이언트가 로그인으로
// 보낸다(`?next=` 포함, `lib/bff/client.ts`) — "리프레시도 실패하면 로그인으로 보낸다"는 FE-07
// 인수조건을 미들웨어(쿠키가 아예 없는 경우)와 나눠 함께 지킨다: 미들웨어는 렌더링 전 게이트,
// 이 훅은 "쿠키는 있었지만 죽어버린" 세션의 런타임 게이트다.
//
// 상태기계(cancelled 플래그·loading/error/ready)는 패키지의 `useBackendQuery` 가 소유한다(#146).

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

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
  // `/api/auth/session` 은 BFF 프록시가 아니라 이 앱 자신의 라우트다 — 경로를 그대로 준다.
  const { state } = useBackendQuery<SessionUser>(bffClient, "/api/auth/session");

  if (state.status === "loading") return { status: "loading" };
  if (state.status === "error") return { status: "unauthenticated" };
  return { status: "authenticated", user: state.data };
}
