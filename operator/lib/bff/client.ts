"use client";

// 운영자 앱의 BFF 클라이언트 (#148, #122) — 공개 앱과 같은 패키지, 다른 인증 방식.
//
// **revive 가 없다.** 운영자 세션은 Django 세션 쿠키(ADR-0018)라 공개 앱의 JWT 리프레시 같은
// 「조용한 갱신」이 없다 — 401 이면 그 자리에서 로그인으로 보낸다. `?next=` 를 붙여 로그인 뒤
// 하던 자리로 돌아온다.

import { createBffClient } from "@laurio/bff-client";

function goToLogin(): void {
  if (typeof window === "undefined") return;
  const next = window.location.pathname + window.location.search;
  window.location.replace(`/login?next=${encodeURIComponent(next)}`);
}

export const bffClient = createBffClient({ onUnauthorized: goToLogin });
