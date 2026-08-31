"use client";

// Operator 목록 조회(#69). 세 가지 실패 상태를 서로 구별한다 — 빈 목록·403·요청
// 실패가 뭉개지면 화면이 거짓말을 한다:
//
// - **403(forbidden)**: 로그인은 됐지만 상위 등급이 아니다. "등급이 필요하다"고
//   말해야 한다 — 빈 목록도 깨진 화면도 아니다(#69 인수조건, 티켓의 "403은 빈
//   목록이 아니다"라는 요구).
// - **401**: 세션이 만료됐다. `use-queue-counts.ts`와 같은 원칙으로 로그인으로
//   돌려보낸다.
// - **그 외 실패(error)**: 알 수 없는 백엔드 오류. "불러오지 못했다"고 말한다.
//
// `reload()`는 생성·비활성화·재활성화 뒤에 목록을 다시 읽어 오는 데 쓴다 — 목록
// 화면이 자기가 만든 변화를 스스로 반영해야, 사용자가 방금 한 일이 실제로 반영됐는지
// 페이지를 새로고침하지 않고도 확인할 수 있다.
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type { OperatorAccount } from "./types";

export type OperatorsState =
  | { status: "loading" }
  | { status: "forbidden" }
  | { status: "error" }
  | { status: "loaded"; operators: OperatorAccount[] };

export function useOperators(enabled: boolean): { state: OperatorsState; reload: () => void } {
  const router = useRouter();
  const [state, setState] = useState<OperatorsState>({ status: "loading" });
  const [version, setVersion] = useState(0);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    async function load() {
      try {
        const res = await fetch("/api/backend/operator/operators", { cache: "no-store" });
        if (cancelled) return;

        if (res.status === 401) {
          router.replace("/login");
          return;
        }
        if (res.status === 403) {
          setState({ status: "forbidden" });
          return;
        }
        if (!res.ok) {
          setState({ status: "error" });
          return;
        }

        const operators = (await res.json()) as OperatorAccount[];
        if (!cancelled) setState({ status: "loaded", operators });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, router, version]);

  return { state, reload };
}
