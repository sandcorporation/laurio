"use client";

// Category 변경 이력 조회(#231) — use-deliverable-type-history.ts와 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchCategoryChanges } from "./actions";
import type { CategoryChangeEntry } from "./types";

export type CategoryHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: CategoryChangeEntry[] };

export function useCategoryHistory(enabled: boolean): {
  state: CategoryHistoryState;
  reload: () => void;
} {
  const [state, setState] = useState<CategoryHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchCategoryChanges();
      if (cancelled) return;

      // 401은 클라이언트가 로그인으로 보낸다(#148) — 여기서는 「값을 모른다」로만 남는다.
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
