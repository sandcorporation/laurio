"use client";

// 강의실의 BFF 클라이언트 (#462) — 공개 앱·운영자 앱과 같은 패키지, 운영자
// 앱과 같은 인증 방식이다: 강의실은 자기 로그인을 갖지 않으므로(ADR-0038)
// `revive`가 없다 — 되살릴 자기 세션 엔드포인트가 없다(BFF 프록시
// `forwardToBackend`가 요청마다 이미 리프레시 토큰으로 조용히 갱신을
// 시도한다, `lib/proxy/forward.ts`). 그래도 401 이면 그 자리에서 로그인으로
// 보낸다.
//
// `/login` 은 이 앱 자신의 화면이다(app/login/page.tsx) — 거기서 `next_origin`
// 을 실어 공개 앱 로그인으로 다시 보내고, 로그인이 끝나면 그 오리진으로
// 돌아온다. `?next=` 는 그 화면이 이미 검증한다(lib/auth/next-path.ts) — 여기서는
// 실어 보내기만 한다.

import { createBffClient, createLoginRedirect } from "@codemit/bff-client";
import type { ApiResult } from "@codemit/bff-client";

// 한 화면의 요청 여럿이 함께 401 을 받아도 이동은 한 번이다(#501, 패키지의 `login-redirect`).
const goToLogin = createLoginRedirect();

export const bffClient = createBffClient({ onUnauthorized: goToLogin });

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
