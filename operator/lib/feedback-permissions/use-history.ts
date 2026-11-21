"use client";

// 제보 권한 변경 이력 조회(#1243) — `lib/deliverable-types/use-deliverable-type-history.ts`와
// 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchFeedbackPermissionChanges } from "./actions";
import type { FeedbackPermissionChangeEntry } from "./types";

export type FeedbackPermissionHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: FeedbackPermissionChangeEntry[] };

export function useFeedbackPermissionHistory(enabled: boolean): {
  state: FeedbackPermissionHistoryState;
  reload: () => void;
} {
  const [state, setState] = useState<FeedbackPermissionHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchFeedbackPermissionChanges();
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
