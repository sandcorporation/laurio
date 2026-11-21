"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchScoreCorrections } from "./actions";
import { isCorrectionRunning } from "./status-label";
import type { ScoreCorrectionList } from "./types";

export type ScoreCorrectionsState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; list: ScoreCorrectionList };

const POLL_MS = 2000;

/** 정정 목록 — 진행 중인 정정이 있으면 끝날 때까지 다시 불러온다(채점은 워커가 따로 돈다). */
export function useScoreCorrections(
  contestId: string,
  enabled: boolean,
): { state: ScoreCorrectionsState; reload: () => void } {
  const [state, setState] = useState<ScoreCorrectionsState>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      const result = await fetchScoreCorrections(contestId);
      if (cancelled) return;
      if (!result.ok) {
        setState({ status: "error" });
        return;
      }
      setState({ status: "loaded", list: result.data });
      if (result.data.corrections.some((c) => isCorrectionRunning(c.status))) {
        timer = setTimeout(load, POLL_MS);
      }
    }
    load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [contestId, enabled, version]);

  return { state, reload };
}
