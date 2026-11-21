"use client";

// 유료 공모전 목록 조회(#1212) — `lib/free-contests/use-free-contests.ts`와
// 같은 계약.
import { useCallback, useEffect, useState } from "react";

import { fetchPaidContests } from "./actions";
import type { PaidContest } from "./types";

export type PaidContestsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; contests: PaidContest[] };

export function usePaidContests(enabled: boolean): {
  state: PaidContestsState;
  reload: () => void;
} {
  const [state, setState] = useState<PaidContestsState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchPaidContests();
      if (cancelled) return;

      // 401 은 클라이언트가 로그인으로 보낸다 — 여기서는 「값을 모른다」로만 남는다.
      if (!result.ok) {
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", contests: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
