"use client";

// 과제 개최 자격 보유자 목록 조회(#206). 조회는 일반 등급도 된다(정책 조회와
// 같은 규율, #76·#80) — 부여·회수만 상위 등급을 요구한다. 401만 로그인으로
// 돌려보내고, 그 외 실패는 "불러오지 못했다"로 뭉뚱그린다.
import { useCallback, useEffect, useState } from "react";

import { fetchAssignmentPermissionHolders } from "./actions";
import type { AssignmentPermissionHolder } from "./types";

export type AssignmentPermissionHoldersState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; holders: AssignmentPermissionHolder[] };

export function useAssignmentPermissionHolders(enabled: boolean): {
  state: AssignmentPermissionHoldersState;
  reload: () => void;
} {
  const [state, setState] = useState<AssignmentPermissionHoldersState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchAssignmentPermissionHolders();
      if (cancelled) return;

      // 401은 클라이언트가 로그인으로 보낸다(#148) — 여기서는 「값을 모른다」로만 남는다.
      if (!result.ok) {
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", holders: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
