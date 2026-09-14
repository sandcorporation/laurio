"use client";

// 채점 모델 목록 상태 (#285, #401 — 클래스 기준). 「클래스 설정」과 「문제
// 만들기·편집」이 함께 쓴다.
import { useCallback, useEffect, useState } from "react";

import { fetchScoringModels, type ScoringModelCatalog, type ScoringModelRow } from "./api";

export type { ScoringModelRow };

export type ScoringModelsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; models: ScoringModelRow[]; source: "live" | "fallback"; unavailableReason: "no_api_key" | "fetch_failed" | null };

export function useScoringModels(classId: number): { state: ScoringModelsState; reload: () => void } {
  const [state, setState] = useState<ScoringModelsState>({ status: "loading" });

  const load = useCallback(() => {
    let cancelled = false;
    fetchScoringModels(classId)
      .then((catalog: ScoringModelCatalog) => {
        if (!cancelled) {
          setState({
            status: "ready",
            models: catalog.models,
            source: catalog.source,
            unavailableReason: catalog.unavailable_reason,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [classId]);

  useEffect(() => {
    // 클래스 키를 막 저장한 뒤의 `reload()`는 이미 그린 목록을 그대로 두고
    // 새 응답이 오면 바꾼다(`useClass`의 같은 관용구) — 보고 있는 클래스가
    // 바뀔 때만 "loading"으로 비운다.
    setState({ status: "loading" });
    return load();
  }, [load]);

  return { state, reload: load };
}
