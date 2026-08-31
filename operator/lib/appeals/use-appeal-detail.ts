"use client";

// 이의 상세(#66). 존재하지 않는 이의는 "없다"고 말해야 하고(빈 상세를 그리지
// 않는다), 그건 "불러오지 못했습니다"(그 외 실패)와 다른 상태다 — 목록의
// 빈 목록/실패 구분과 같은 원칙을 상세에도 적용한다.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { AppealDetail } from "./types";

export type AppealDetailState =
  | { status: "loading" }
  | { status: "loaded"; appeal: AppealDetail }
  | { status: "not-found" }
  | { status: "error" };

export function useAppealDetail(appealId: string, enabled: boolean): AppealDetailState {
  const router = useRouter();
  const [state, setState] = useState<AppealDetailState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState({ status: "loading" });

    async function load() {
      try {
        const res = await fetch(`/api/backend/operator/appeals/${appealId}`, {
          cache: "no-store",
        });
        if (cancelled) return;

        if (res.status === 401) {
          router.replace("/login");
          return;
        }
        if (res.status === 404) {
          setState({ status: "not-found" });
          return;
        }
        if (!res.ok) {
          setState({ status: "error" });
          return;
        }

        const appeal = (await res.json()) as AppealDetail;
        if (!cancelled) setState({ status: "loaded", appeal });
      } catch {
        if (!cancelled) setState({ status: "error" });
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [appealId, enabled, router]);

  return state;
}
