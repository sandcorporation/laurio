"use client";

// 로그인한 본인의 User pk (#286) — 소스 제출의 target_ref
// (`classroom-submission:<problem_id>:<user_id>:source`)를 조립하는 데
// 필요하다. `accounts.DeveloperProfile`이 없는 강의실 참여자가 자기 pk를
// 알 수 있는 유일한 경로가 공유층의 `GET /api/accounts/me`다.
//
// `username`도 같은 응답(`accounts.schemas.MeOut`)에서 함께 받는다(#306) —
// 헤더 계정 메뉴가 "지금 누구로 들어와 있는지"를 보여줘야 하는데, 그 값을 얻는
// 유일한 경로도 이 호출뿐이라 새 요청을 늘리지 않고 이미 있는 필드를 하나 더
// 읽는다.
import { useEffect, useState } from "react";

import { backendJson } from "@/lib/backend/client";

type MeState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; userId: number; username: string };

export function useMe() {
  const [state, setState] = useState<MeState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    backendJson<{ id: number; username: string }>("/accounts/me")
      .then(({ id, username }) => {
        if (!cancelled) setState({ status: "ready", userId: id, username });
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
