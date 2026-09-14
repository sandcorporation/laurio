"use client";

// 헤더의 세션 판정을 한 곳에서 한다(#237).
//
// 전에는 `NotificationBell`과 `SessionSlot`이 각자 세션을 확인했다 — 벨은
// `GET /notifications/unread-count`의 401 자체로("로그인 여부를 따로 확인하지
// 않는다", notification-bell.tsx의 예전 주석), 슬롯은 `GET /api/auth/session`으로.
// 익명 방문자에게는 그 대가가 컸다: 벨의 401은 `bffClient`의 되살리기를
// 반복해서 건드리고(최대 3회 재시도), 벨은 30초마다 그 전부를 다시 한다.
// 실측(staging, 공개 공모전 상세 1회 로드): `unread-count` 3회·`auth/session`
// 7회, 그리고 30초마다 새 401 묶음(#237).
//
// 이 컴포넌트가 세션을 **한 번만** 묻고(`lib/bff/session-client.ts` — 되살리기가
// 없어 재시도도 없다) 그 결과를 두 자식에게 그대로 내려준다. 벨은 세션이
// 확인되기 전까지는(`loading`이든 `unauthenticated`든) `unread-count`를 아예
// 묻지 않는다 — 익명 방문자는 인증이 필요한 요청을 한 번도 만들지 않는다.
import { usePathname } from "next/navigation";

import { useBackendQuery } from "@codemit/bff-client";

import { sessionOnlyClient } from "@/lib/bff/session-client";
import type { HeaderSessionState } from "@/lib/auth/header-session-state";

import { NotificationBell } from "./notification-bell";
import { SessionSlot } from "./session-slot";

export function HeaderSessionZone({ classroomUrl }: { classroomUrl: string }) {
  // 세션 슬롯이 예전에 그랬듯 `pathname`을 `refetchKey`로 준다 — 헤더는 루트
  // 레이아웃에 살아 페이지 이동에도 마운트가 유지되므로, 로그인·로그아웃
  // 직후의 이동에도 다시 확인해야 한다.
  const pathname = usePathname();
  const { state } = useBackendQuery<unknown>(sessionOnlyClient, "/api/auth/session", {
    unauthorizedIsAnswer: true,
    refetchKey: pathname,
  });

  const sessionState: HeaderSessionState =
    state.status === "loading"
      ? { status: "loading" }
      : state.status === "ready"
        ? { status: "authenticated" }
        : { status: "unauthenticated" };

  return (
    <>
      <NotificationBell sessionState={sessionState} />
      <SessionSlot sessionState={sessionState} classroomUrl={classroomUrl} />
    </>
  );
}
