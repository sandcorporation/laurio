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
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { backendJson } from "@/lib/backend/client";

export type MeState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; userId: number; username: string; email: string };

const MeContext = createContext<MeState | null>(null);

export function MeProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MeState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    backendJson<{ id: number; username: string; email: string }>("/accounts/me")
      .then(({ id, username, email }) => {
        if (!cancelled) setState({ status: "ready", userId: id, username, email: email ?? "" });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
