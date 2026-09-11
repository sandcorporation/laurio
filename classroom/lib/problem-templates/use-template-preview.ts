"use client";

// 템플릿 하나의 미리보기 상태 (#316). 로그인은 middleware.ts가 이미
// 보장하므로 `app/join/[code]`의 needsLogin 분기 같은 것이 없다 — 내려간
// 템플릿이면 백엔드가 404를 준다.
import { useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchProblemTemplate, type ProblemTemplateRow } from "./api";

export type TemplatePreviewState =
  | { status: "loading" }
  | { status: "gone" }
  | { status: "error" }
  | { status: "ready"; template: ProblemTemplateRow };

export function useTemplatePreview(shareCode: string) {
  const [state, setState] = useState<TemplatePreviewState>({ status: "loading" });

  function reload() {
    setState({ status: "loading" });
    fetchProblemTemplate(shareCode)
      .then((template) => setState({ status: "ready", template }))
      .catch((error) => {
        if (error instanceof BackendError && error.status === 404) {
          setState({ status: "gone" });
        } else {
          setState({ status: "error" });
        }
      });
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shareCode]);

  return { state, reload };
}
