"use client";

// 로그인한 본인의 User pk (#286) — 소스 제출의 target_ref
// (`classroom-submission:<problem_id>:<user_id>:source`)를 조립하는 데
// 필요하다. `accounts.DeveloperProfile`이 없는 강의실 참여자가 자기 pk를
// 알 수 있는 유일한 경로가 공유층의 `GET /api/accounts/me`다.
//
// `username`·`email`도 같은 응답(`accounts.schemas.MeOut`)에서 함께 받는다(#306)
// — 헤더 계정 메뉴가 "지금 누구로 들어와 있는지"를 보여줘야 하는데, 그 값을 얻는
// 유일한 경로도 이 호출뿐이라 새 요청을 늘리지 않고 이미 있는 필드를 더 읽는다.
//
// **`username`을 화면에 그대로 그리면 안 된다.** 소셜 로그인 계정의 username 은
// `kakao:5069350637` 같은 제공자 식별자다 — staging 에서 실제로 그 문자열이 헤더에
// 떠 있었다. `accountLabel`이 그 판단을 한 곳에 둔다.
import { useEffect, useState } from "react";

import { backendJson } from "@/lib/backend/client";

export { accountLabel } from "./account-label";

type MeState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; userId: number; username: string; email: string };

export function useMe() {
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

  return state;
}

