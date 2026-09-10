"use client";

// 참여자 × 문제 격자 상태 (#290). 남의 클래스는 백엔드가 404를 준다 — 클래스
// 상세·참여자 명단과 같은 이유로 "클래스를 찾을 수 없습니다"로 보여준다.
import { useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchRosterGrid, type RosterGrid } from "./api";

export type RosterGridState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; grid: RosterGrid };

export function useRosterGrid(classId: number) {
  const [state, setState] = useState<RosterGridState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchRosterGrid(classId)
      .then((grid) => {
        if (!cancelled) setState({ status: "ready", grid });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "notFound" });
        } else {
          setState({ status: "error" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [classId]);

  return { state };
}
