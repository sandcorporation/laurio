"use client";

// 정책 변경 이력 조회(#77). 조회 API의 계약과 실패 처리는 use-policy.ts와
// 같다 — 별도 훅으로 나눈 이유는 두 조회가 서로 실패해도 독립적이어야
// 하기 때문이다(값 조회는 됐는데 이력 조회만 실패해도 값 표는 그대로 보여야
// 한다).
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchPolicyChanges } from "./actions";
import type { PolicyChangeEntry } from "./types";

export type PolicyHistoryState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; changes: PolicyChangeEntry[] };

export function usePolicyHistory(enabled: boolean): {
  state: PolicyHistoryState;
  reload: () => void;
} {
  const router = useRouter();
  const [state, setState] = useState<PolicyHistoryState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchPolicyChanges();
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
