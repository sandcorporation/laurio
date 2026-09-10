"use client";

// 로그인한 본인의 User pk (#286) — 소스 제출의 target_ref
// (`classroom-submission:<problem_id>:<user_id>:source`)를 조립하는 데
// 필요하다. `accounts.DeveloperProfile`이 없는 강의실 참여자가 자기 pk를
// 알 수 있는 유일한 경로가 공유층의 `GET /api/accounts/me`다.
import { useEffect, useState } from "react";

import { backendJson } from "@/lib/backend/client";

type MeState = { status: "loading" } | { status: "error" } | { status: "ready"; userId: number };

export function useMe() {
  const [state, setState] = useState<MeState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    backendJson<{ id: number }>("/accounts/me")
      .then(({ id }) => {
        if (!cancelled) setState({ status: "ready", userId: id });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
