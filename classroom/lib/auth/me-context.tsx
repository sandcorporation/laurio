"use client";

// 헤더의 두 조각 — 알림 종(#304)과 계정 메뉴(#306) — 이 각자 `useMe()`를 불러
// 페이지 한 번 열 때 `GET /accounts/me`가 두 번 나갔다(#322, staging 실측). 한
// 조각만 있던 시절에는 문제가 아니었는데 둘이 나란히 서면서 드러났다.
//
// 고치는 자리는 훅이 아니라 **트리** 다 — 상태를 `useMe()` 안의 `useState`가
// 아니라 이 Context 하나에 두고, `RootLayout`이 트리 전체를 한 번 감싸 모든
// 소비자가 같은 값을 나눠 읽는다. 실제 조회는 `MeProvider`가 마운트당 정확히
// 한 번만 한다 — 소비자 개수와 무관하다.
//
// **#237의 규율은 그대로다** — 세션이 확인되기 전에는 `unread-count`를 묻지
// 않는다는 것은 `useUnreadCount`가 이 Context의 `status`를 보고 판단하는
// 문제이지, 조회가 하나냐 둘이냐와는 무관하다. 합치기 전에도 후에도 `status`가
// `"ready"`가 되기 전에는 개수를 묻지 않는다.
//
// 공유 클라이언트 위에 선다(#462) — `unauthorizedIsAnswer: true`를 준다:
// 이 Provider는 `/login`·`/join/{code}`처럼 로그인 없이도 열리는 화면에서도
// 마운트되므로(RootLayout), 익명 방문자의 401을 `bffClient`가 곧장
// 로그인으로 튕기면 그 화면 자체가 열리지 않는다(공개 앱
// `notification-bell.tsx`의 같은 경고).
import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type MeState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; userId: number; username: string; email: string };

type MeOut = { id: number; username: string; email: string };

const MeContext = createContext<MeState | null>(null);

export function MeProvider({ children }: { children: ReactNode }) {
  const { state: queryState } = useBackendQuery<MeOut>(bffClient, "/api/backend/accounts/me", {
    unauthorizedIsAnswer: true,
  });

  // useMemo 없이 매 렌더 새 객체를 만들면 이 값을 그대로 쓰는 소비자
  // (`useEventStream`의 `isReady` 판정 등)가 불필요하게 다시 돈다 — 이
  // Context 는 트리 전체가 나눠 읽으므로 그 값이 특히 잘 퍼진다(#462 코드 리뷰).
  const state: MeState = useMemo(
    () =>
      queryState.status === "loading"
        ? { status: "loading" }
        : queryState.status === "error"
          ? { status: "error" }
          : {
              status: "ready",
              userId: queryState.data.id,
              username: queryState.data.username,
              email: queryState.data.email ?? "",
            },
    [queryState],
  );

  return <MeContext.Provider value={state}>{children}</MeContext.Provider>;
}

// `RootLayout`이 `MeProvider`를 빠뜨리면 소비자마다 다시 조회하던 예전 버그가
// 조용히 돌아온다 — 그 대신 여기서 바로 던져 개발 중에 드러나게 한다.
export function useMeState(): MeState {
  const state = useContext(MeContext);
  if (state === null) {
    throw new Error("useMe()는 MeProvider 트리 안에서만 쓸 수 있다");
  }
  return state;
}
