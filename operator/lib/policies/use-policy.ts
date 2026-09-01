"use client";

// 현재 정책값 조회(#77). 조회는 일반 등급 Operator도 된다(#76) — 이 훅은
// 403/forbidden 상태를 갖지 않는다(`use-operators.ts`와 다른 점). 401만
// 로그인으로 돌려보내고, 그 외 실패는 "불러오지 못했다"로 뭉뚱그린다.
//
// **조회 실패가 「값이 0」처럼 보이면 안 된다**(#77 AC) — 그래서 초기 상태도
// 실패 상태도 절대 `{ platform_fee_bps: 0, ... }` 같은 값을 만들어내지 않는다.
// `state.status`가 "loaded"일 때만 값이 존재한다는 것을 타입으로 강제한다.
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchPolicy } from "./actions";
import type { PlatformPolicy } from "./types";

export type PolicyState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; policy: PlatformPolicy };

export function usePolicy(enabled: boolean): { state: PolicyState; reload: () => void } {
  const router = useRouter();
  const [state, setState] = useState<PolicyState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  // create-operator-form과 같은 이유로 reload에서 "loading"으로 되돌리지
  // 않는다 — 이미 그려진 표를 스피너로 바꿔치기하지 않는다. 새 응답이 오면
  // 그 결과로만 갱신한다.
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      const result = await fetchPolicy();
      if (cancelled) return;

      if (!result.ok) {
        if (result.status === 401) {
          router.replace("/login");
          return;
        }
        setState({ status: "error" });
        return;
      }

      setState({ status: "loaded", policy: result.data });
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, router, version]);

  return { state, reload };
}
