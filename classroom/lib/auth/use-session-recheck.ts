"use client";

// 다른 탭에서 로그아웃하거나 다른 계정으로 들어간 뒤 이 탭으로 돌아오면 세션을 다시 확인한다(#1406).
// 열려 있던 목록은 이전 사람의 것이다. 로그아웃이면 `bffClient` 의 401 처리가 로그인으로 보내고,
// 사람이 바뀌었으면 화면을 새로 읽는다 — 새 목록을 이전 사람의 목록에 합치지 않는다.
// 로그아웃은 공개 앱(다른 오리진)에서도 일어나 탭 사이 방송으로는 알 수 없다.
import { useEffect } from "react";

import { bffClient } from "@/lib/bff/client";

import { useMe } from "./use-me";

export function useSessionRecheck(): void {
  const me = useMe();
  const userId = me.status === "ready" ? me.userId : null;

  useEffect(() => {
    if (userId === null) return;
    function recheck() {
      if (document.visibilityState !== "visible") return;
      void bffClient.get<{ id: number }>("/api/backend/accounts/me").then((result) => {
        if (result.ok && result.data.id !== userId) window.location.reload();
      });
    }
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    return () => {
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", recheck);
    };
  }, [userId]);
}
