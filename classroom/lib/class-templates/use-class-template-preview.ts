"use client";

// 클래스 템플릿 하나의 미리보기 상태 (#319) —
// `problem-templates/use-template-preview.ts`와 같은 모양이다.
import { useEffect, useState } from "react";

import { BackendError } from "@/lib/backend/client";

import { fetchClassTemplate, type ClassTemplateRow } from "./api";

export type ClassTemplatePreviewState =
  | { status: "loading" }
  | { status: "gone" }
  | { status: "error" }
  | { status: "ready"; template: ClassTemplateRow };

export function useClassTemplatePreview(shareCode: string) {
  const [state, setState] = useState<ClassTemplatePreviewState>({ status: "loading" });

  function reload() {
    setState({ status: "loading" });
    fetchClassTemplate(shareCode)
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
