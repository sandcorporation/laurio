"use client";

// 운영팀 알림 발송 이력 조회(#418) — use-category-history.ts와 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchOperatorNotices } from "./actions";
import type { OperatorNotice } from "./types";

export type OperatorNoticesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; notices: OperatorNotice[] };

export function useOperatorNotices(enabled: boolean): {
  state: OperatorNoticesState;
  reload: () => void;
} {
  const [state, setState] = useState<OperatorNoticesState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchOperatorNotices();
      if (cancelled) return;

      if (!result.ok) {
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", notices: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
