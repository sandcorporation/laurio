"use client";

// AssignmentPermissionChange 이력 조회(#206) — use-deliverable-type-history.ts와 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchAssignmentPermissionChanges } from "./actions";
import type { AssignmentPermissionChangeEntry } from "./types";

export type AssignmentPermissionHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: AssignmentPermissionChangeEntry[] };

export function useAssignmentPermissionHistory(enabled: boolean): {
  state: AssignmentPermissionHistoryState;
  reload: () => void;
} {
  const [state, setState] = useState<AssignmentPermissionHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchAssignmentPermissionChanges();
      if (cancelled) return;

      if (!result.ok) {
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", changes: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
