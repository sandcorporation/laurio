"use client";

// 권한을 보유한 계정 목록 조회(#414) — `lib/deliverable-types/use-deliverable-types.ts`와
// 같은 계약. 조회는 일반 등급도 된다(정책·산출물 종류 조회와 같은 규율).
import { useCallback, useEffect, useState } from "react";

import { fetchGrantedHostingPermissionAccounts } from "./actions";
import type { HostingPermissionAccount } from "./types";

export type GrantedAccountsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; accounts: HostingPermissionAccount[] };

export function useGrantedHostingPermissionAccounts(enabled: boolean): {
  state: GrantedAccountsState;
  reload: () => void;
} {
  const [state, setState] = useState<GrantedAccountsState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchGrantedHostingPermissionAccounts();
      if (cancelled) return;

      // 401 은 클라이언트가 로그인으로 보낸다 — 여기서는 「값을 모른다」로만 남는다.
      if (!result.ok) {
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", accounts: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, version]);

  return { state, reload };
}
