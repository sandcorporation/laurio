"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchContestCertificates } from "./actions";
import type { CertificateList } from "./types";

export type ContestCertificatesState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "loaded"; list: CertificateList };

export function useContestCertificates(
  contestId: string,
  enabled: boolean,
): { state: ContestCertificatesState; reload: () => void } {
  const [state, setState] = useState<ContestCertificatesState>({ status: "loading" });
  const [version, setVersion] = useState(0);
  const reload = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    async function load() {
      const result = await fetchContestCertificates(contestId);
      if (cancelled) return;
      setState(result.ok ? { status: "loaded", list: result.data } : { status: "error" });
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [contestId, enabled, version]);

  return { state, reload };
}
