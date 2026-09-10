"use client";

// 클래스 상세 상태 (#278). 남의 클래스는 백엔드가 404를 준다 — 그 사실을
// "notFound"로 구별해 화면이 "클래스를 찾을 수 없습니다"를 보여준다.
import { useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchClass, type ClassRow } from "./api";

export type ClassDetailState =
  | { status: "loading" }
  | { status: "notFound" }
  | { status: "error" }
  | { status: "ready"; classroom: ClassRow };

export function useClass(classId: number) {
  const [state, setState] = useState<ClassDetailState>({ status: "loading" });

  function load() {
    let cancelled = false;
    setState({ status: "loading" });
    fetchClass(classId)
      .then((classroom) => {
        if (!cancelled) setState({ status: "ready", classroom });
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
  }

  useEffect(() => {
    const cancel = load();
    return cancel;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId]);

  return { state, reload: load };
}
