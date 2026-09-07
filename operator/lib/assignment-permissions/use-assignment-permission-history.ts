"use client";

// AssignmentPermissionChange 이력 조회(#206) — use-assignment-permission-holders.ts와
// 같은 계약, `useBackendQuery`(#146·#122) 위의 얇은 이름 다시 붙이기.
import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { AssignmentPermissionChangeEntry } from "./types";

export type AssignmentPermissionHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: AssignmentPermissionChangeEntry[] };

export function useAssignmentPermissionHistory(enabled: boolean): {
  state: AssignmentPermissionHistoryState;
  reload: () => void;
} {
  const { state, reload } = useBackendQuery<AssignmentPermissionChangeEntry[]>(
    bffClient,
    enabled ? "/api/backend/operator/assignment-permissions/changes" : null,
  );

  if (state.status === "loading") return { state: { status: "loading" }, reload };
  if (state.status === "error") return { state: { status: "error" }, reload };
  return { state: { status: "loaded", changes: state.data }, reload };
}
