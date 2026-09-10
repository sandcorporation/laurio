"use client";

// 가입 링크 미리보기 상태 (#280). 죽은 링크(재발급으로 죽었거나 애초에 없는
// 코드)는 백엔드가 이유를 담은 404를 준다 — 그 문구를 그대로 보여준다(둘을
// 구별해 보여줄 필요가 없다는 것도 백엔드가 이미 정한 결정이다,
// backend/classroom/api.py의 `_get_class_by_join_code_or_404`).
import { useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchJoinPreview, type JoinPreview } from "./api";

export type JoinPreviewState =
  | { status: "loading" }
  | { status: "dead"; reason: string }
  | { status: "error" }
  | { status: "ready"; preview: JoinPreview };

export function useJoinPreview(code: string): JoinPreviewState {
  const [state, setState] = useState<JoinPreviewState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchJoinPreview(code)
      .then((preview) => {
        if (!cancelled) setState({ status: "ready", preview });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "dead", reason: error.message });
        } else {
          setState({ status: "error" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  return state;
}
