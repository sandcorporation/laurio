"use client";

// 채점 모델 목록 상태 (#285). 「채점 설정」과 「문제 편집」이 함께 쓴다.
import { useEffect, useState } from "react";

import { fetchScoringModels, type ScoringModelRow } from "./api";

export type ScoringModelsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; models: ScoringModelRow[] };

export function useScoringModels(): ScoringModelsState {
  const [state, setState] = useState<ScoringModelsState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchScoringModels()
      .then((models) => {
        if (!cancelled) setState({ status: "ready", models });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
