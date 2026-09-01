"use client";

// DeliverableType 목록 조회(#80). 조회는 일반 등급도 된다(정책 조회와 같은
// 규율, #76·#77) — 활성·비활성 전부 돌려받는다. 401만 로그인으로 돌려보내고,
// 그 외 실패는 "불러오지 못했다"로 뭉뚱그린다(forbidden 상태가 없다 — 이
// 목록은 등급을 가리지 않는다).
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchDeliverableTypes } from "./actions";
import type { DeliverableType } from "./types";

export type DeliverableTypesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; types: DeliverableType[] };

export function useDeliverableTypes(enabled: boolean): {
  state: DeliverableTypesState;
  reload: () => void;
} {
  const router = useRouter();
  const [state, setState] = useState<DeliverableTypesState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchDeliverableTypes();
      if (cancelled) return;

      if (!result.ok) {
        if (result.status === 401) {
          router.replace("/login");
          return;
        }
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", types: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, router, version]);

  return { state, reload };
}
