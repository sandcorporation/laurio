"use client";

// 과제 개최 자격 보유자 목록 조회(#206). 조회는 일반 등급도 된다(정책 조회와
// 같은 규율, #76·#80) — 부여·회수만 상위 등급을 요구한다.
//
// 상태기계 자체는 `@laurio/bff-client`의 `useBackendQuery`가 소유한다(#146·#122
// — 두 앱 합쳐 22벌이던 useEffect+useState+cancelled 플래그+reload nonce가 이
// 훅으로 모였다). `operator/lib/auth/use-session.ts`와 같은 관용구로, 그 결과를
// 이 화면의 어휘(loading/error/loaded)로 다시 이름 붙인다 — 401은 `useBackendQuery`
// 기본값대로 세션 만료로 다뤄진다(`unauthorizedIsAnswer`를 주지 않는다).
import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { AssignmentPermissionHolder } from "./types";

export type AssignmentPermissionHoldersState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; holders: AssignmentPermissionHolder[] };

export function useAssignmentPermissionHolders(enabled: boolean): {
  state: AssignmentPermissionHoldersState;
  reload: () => void;
} {
  const { state, reload } = useBackendQuery<AssignmentPermissionHolder[]>(
    bffClient,
    enabled ? "/api/backend/operator/assignment-permissions" : null,
  );

  if (state.status === "loading") return { state: { status: "loading" }, reload };
  // 401을 포함한 모든 실패를 "불러오지 못했다"로 뭉뚱그린다 — 401은 클라이언트가
  // 이미 로그인으로 보낸다(#148).
  if (state.status === "error") return { state: { status: "error" }, reload };
  return { state: { status: "loaded", holders: state.data }, reload };
}
