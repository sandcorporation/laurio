"use client";

// DeliverableType 변경 이력 조회(#80) — use-policy-history.ts와 같은 계약.
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

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
  const router = useRouter();
  const [state, setState] = useState<DeliverableTypeHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchDeliverableTypeChanges();
      if (cancelled) return;

      if (!result.ok) {
        if (result.status === 401) {
          router.replace("/login");
          return;
        }
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
  }, [enabled, router, version]);

  return { state, reload };
}
