"use client";

// DeliverableType 변경 이력 조회(#80) — use-policy-history.ts와 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchDeliverableTypeChanges } from "./actions";
import type { DeliverableTypeChangeEntry } from "./types";

export type DeliverableTypeHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: DeliverableTypeChangeEntry[] };

export function useDeliverableTypeHistory(enabled: boolean): {
  state: DeliverableTypeHistoryState;
  reload: () => void;
} {
  const [state, setState] = useState<DeliverableTypeHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchDeliverableTypeChanges();
      if (cancelled) return;

      // 401 은 클라이언트가 로그인으로 보낸다(#148) — 여기서는 「값을 모른다」로만 남는다.
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
