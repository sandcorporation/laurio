"use client";

// 강의실의 BFF 클라이언트 (#462) — 공개 앱·운영자 앱과 같은 패키지, 공개 앱과
// 같은 인증 방식이다.
//
// - `revive`: 이 앱의 `/api/auth/session`(#767, lib/auth/session-endpoint.ts)은 액세스가
//   만료돼 있으면 조용히 리프레시한다. 그 라우트를 한 번 부르는 것이 곧 「세션 되살리기」
//   이고, 단일 비행·재시도는 패키지가 소유한다. 강의실은 자기 로그인이 없지만(ADR-0038)
//   세션 쿠키는 부모 도메인을 두 앱이 나눠 쓰므로 되살리는 자리는 가질 수 있다 —
//   예전에는 이것이 없어, 리프레시 회전 경합에서 진 요청(BFF 프록시 `forwardToBackend`
//   가 요청마다 회전을 시도하지만 1회용 회전이라 형제 요청이 먼저 돌리면 진다,
//   `lib/auth/session.ts`)의 401 하나로 켜 둔 탭이 로그인으로 튕겼다.
// - `onUnauthorized`: 되살려도 401 이면 그 자리에서 로그인으로 보낸다.
//
// `/login` 은 이 앱 자신의 화면이다(app/login/page.tsx) — 거기서 `next_origin`
// 을 실어 공개 앱 로그인으로 다시 보내고, 로그인이 끝나면 그 오리진으로
// 돌아온다. `?next=` 는 그 화면이 이미 검증한다(lib/auth/next-path.ts) — 여기서는
// 실어 보내기만 한다.

import { createBffClient, createLoginRedirect } from "@codemit/bff-client";
import type { ApiResult } from "@codemit/bff-client";

// 한 화면의 요청 여럿이 함께 401 을 받아도 이동은 한 번이다(#501, 패키지의 `login-redirect`).
const goToLogin = createLoginRedirect();

export const bffClient = createBffClient({
  revive: () => fetch("/api/auth/session", { cache: "no-store" }),
  onUnauthorized: goToLogin,
});

/** `PATCH`·`PUT`·`DELETE` — `bffClient`는 `get`/`post` 편의만 준다(#122). 그
 * 밖의 메서드는 `request`를 이 모양으로 감싸 쓴다. */
export function apiRequest<T>(path: string, method: string, body?: unknown): Promise<ApiResult<T>> {
  return bffClient.request<T>(path, {
    method,
    ...(body !== undefined
      ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
      : {}),
  });
}

/** `ApiResult` 성공이면 데이터를, 실패면 그 자체(`ApiFailure`)를 던진다 —
 * `useLoadable`처럼 던지는 `Promise<T>`를 기대하는 자리를 위한 최소 접합부다. */
export async function unwrap<T>(result: Promise<ApiResult<T>>): Promise<T> {
  const awaited = await result;
  if (!awaited.ok) throw awaited;
  return awaited.data;
}
