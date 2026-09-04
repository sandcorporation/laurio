"use client";

// DeliverableType 목록 조회(#80). 조회는 일반 등급도 된다(정책 조회와 같은
// 규율, #76·#77) — 활성·비활성 전부 돌려받는다. 401만 로그인으로 돌려보내고,
// 그 외 실패는 "불러오지 못했다"로 뭉뚱그린다(forbidden 상태가 없다 — 이
// 목록은 등급을 가리지 않는다).
import { useCallback, useEffect, useState } from "react";

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
  const [state, setState] = useState<DeliverableTypesState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchDeliverableTypes();
      if (cancelled) return;

      // 401 은 클라이언트가 로그인으로 보낸다(#148) — 여기서는 「값을 모른다」로만 남는다.
      if (!result.ok) {
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
  }, [enabled, version]);

  return { state, reload };
}
