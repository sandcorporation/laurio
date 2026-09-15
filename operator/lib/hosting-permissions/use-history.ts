"use client";

// 개최 권한 변경 이력 조회(#414) — `lib/deliverable-types/use-deliverable-type-history.ts`와
// 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchHostingPermissionChanges } from "./actions";
import type { HostingPermissionChangeEntry } from "./types";

export type HostingPermissionHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: HostingPermissionChangeEntry[] };

export function useHostingPermissionHistory(enabled: boolean): {
  state: HostingPermissionHistoryState;
  reload: () => void;
} {
  const [state, setState] = useState<HostingPermissionHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchHostingPermissionChanges();
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
